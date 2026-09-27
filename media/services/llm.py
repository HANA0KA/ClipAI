"""Cliente LLM: Gemini con cadena de modelos, u OpenAI-compatible (Ollama).

La cadena de modelos y la clasificación de errores están adaptadas de
ClipPyMe — https://github.com/fralapo/clippyme
Ruta original: src/clippyme/pipeline/gemini_request.py (is_rate_limit_error,
backoff_seconds, build_model_chain, _is_retryable_model_error,
_is_unavailable_model_error, generate_with_model_fallback).
Copyright (c) 2026 ClippyMe — Licencia MIT (ver media/vendor/NOTICE.md).
Cambios: salida estructurada (response_schema), cadena desde
GEMINI_FALLBACK_MODELS, Gemini en Vertex AI con cuenta de servicio, proveedor
compatible con OpenAI vía LLM_BASE_URL, lectura tolerante del JSON
(services/json_repair.py) con un reintento de formato.

Prioridad de proveedor: LLM_BASE_URL (local) → Vertex AI (VERTEX_PROJECT_ID +
cuenta de servicio) → Gemini API (GEMINI_API_KEY) → sin IA.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Callable, TypeVar

import httpx
from pydantic import BaseModel

from media.config import settings
from media.services.json_repair import parse_json, parse_model_list

log = logging.getLogger(__name__)
M = TypeVar("M", bound=BaseModel)


class LLMError(RuntimeError):
    pass


# ── Clasificación de errores (ClipPyMe) ──────────────────────────────────────

def is_rate_limit_error(exc) -> bool:
    s = str(exc).lower()
    return "429" in s or "rate limit" in s or "quota" in s or "resource_exhausted" in s


def backoff_seconds(rate_limited: bool, attempt: int) -> int:
    return (10 if rate_limited else 2) * (2 ** attempt)


def build_model_chain(primary: str, fallbacks: str) -> list[str]:
    models = [primary, *(p.strip() for p in (fallbacks or "").split(","))]
    return list(dict.fromkeys(m for m in models if m))


def is_retryable_error(exc) -> bool:
    s = str(exc).lower()
    return is_rate_limit_error(exc) or any(x in s for x in (
        "500", "502", "503", "504", "unavailable", "deadline_exceeded", "high demand",
        "overloaded", "timed out", "timeout", "connection"))


def is_unavailable_model_error(exc) -> bool:
    s = str(exc).lower()
    return ("404" in s or "not_found" in s) and ("model" in s or "not available" in s)


def is_auth_error(exc) -> bool:
    s = str(exc).lower()
    return any(x in s for x in ("api key not valid", "api_key_invalid", "permission_denied", "401", "403"))


REFORMAT_PROMPT = (
    "Eres un reformateador de JSON. La respuesta anterior no era JSON válido y falló con "
    "este error:\n\nERROR: {err}\n\nRESPUESTA_ANTERIOR:\n{broken}\n\n"
    "Devuelve SOLO el JSON corregido con la misma información: comillas dobles rectas, "
    "sin comas sobrantes, sin markdown, sin texto antes ni después."
)


# Modelos que respondieron 404 (retirados para esta cuenta): no se reintentan
# en este proceso. Las cuotas (429) sí vuelven a probarse en cada proyecto.
_UNAVAILABLE: set[str] = set()
# Vertex: modelos que solo existen en el endpoint `global` (p. ej. Gemini 3.x
# cuando VERTEX_LOCATION es regional). Se recuerda para no repetir el 404.
_GLOBAL_ONLY: set[str] = set()


def vertex_credentials():
    """Credenciales de la cuenta de servicio (JSON en línea o archivo)."""
    import json as _json
    from google.oauth2 import service_account

    s = settings()
    if s.google_service_account_json:
        info = _json.loads(s.google_service_account_json)
    else:
        with open(s.google_service_account_file, encoding="utf-8") as fh:
            info = _json.load(fh)
    return service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/cloud-platform"]), info.get("project_id")


class LLM:
    """Una instancia por proyecto: la cadena de Gemini vuelve a empezar por el
    modelo preferido en cada proyecto nuevo (plan 6.8)."""

    def __init__(self, sleep_fn: Callable[[float], None] = time.sleep):
        s = settings()
        self.sleep = sleep_fn
        if s.llm_base_url and s.llm_model:
            self.provider = "openai"
            self.models = [s.llm_model]
        elif s.vertex_configured:
            self.provider = "vertex"
            self.models = [m for m in build_model_chain(s.gemini_model, s.gemini_fallback_models)
                           if m not in _UNAVAILABLE]
        elif s.gemini_api_key:
            self.provider = "gemini"
            self.models = [m for m in build_model_chain(s.gemini_model, s.gemini_fallback_models)
                           if m not in _UNAVAILABLE]
        else:
            self.provider = "none"
            self.models = []
        self.model_index = 0
        self.last_model: str | None = None
        self._gemini = None
        self._gemini_global = None

    @property
    def available(self) -> bool:
        return self.provider != "none"

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.last_model or (self.models[0] if self.models else '-')}"

    @property
    def max_prompt_chars(self) -> int:
        # Gemini 2.5 Flash acepta ~1M tokens; un modelo local con 16k de contexto no.
        return 600_000 if self.provider in ("gemini", "vertex") else 40_000

    # ── API pública ──────────────────────────────────────────────────────────
    def generate_list(self, prompt: str, item_model: type[M], key: str = "items") -> list[M]:
        """Genera y valida una lista de `item_model`. Lanza LLMError si falla."""
        text = self._generate(prompt, item_model, key)
        result = parse_json(text, retry_fn=lambda err: self._generate(
            REFORMAT_PROMPT.format(err=err, broken=text[:20000]), None, key))
        if result.data is None:
            raise LLMError(f"respuesta no es JSON válido ({result.error})")
        items = parse_model_list(result.data, item_model, key)
        if not items:
            raise LLMError("la respuesta no contenía elementos válidos")
        log.info("LLM %s: %d elementos (lectura: %s)", self.label, len(items), result.parse_path)
        return items

    # ── Proveedores ──────────────────────────────────────────────────────────
    def _generate(self, prompt: str, item_model: type[BaseModel] | None, key: str) -> str:
        if self.provider in ("gemini", "vertex"):
            return self._gemini_generate(prompt, item_model)
        if self.provider == "openai":
            return self._openai_generate(prompt, key)
        raise LLMError("no hay LLM configurado (GEMINI_API_KEY o LLM_BASE_URL)")

    def _gemini_client(self, model: str | None = None):
        from google import genai
        s = settings()
        if self.provider != "vertex":
            if self._gemini is None:
                self._gemini = genai.Client(api_key=s.gemini_api_key)
            return self._gemini
        if model in _GLOBAL_ONLY or s.vertex_location == "global":
            if self._gemini_global is None:
                creds, _ = vertex_credentials()
                self._gemini_global = genai.Client(vertexai=True, project=s.vertex_project_id,
                                                   location="global", credentials=creds)
            return self._gemini_global
        if self._gemini is None:
            creds, _ = vertex_credentials()
            self._gemini = genai.Client(vertexai=True, project=s.vertex_project_id,
                                        location=s.vertex_location, credentials=creds)
        return self._gemini

    def _gemini_generate(self, prompt: str, item_model: type[BaseModel] | None) -> str:
        from google.genai import types
        config = types.GenerateContentConfig(
            temperature=0.4,
            response_mime_type="application/json",
            response_schema=list[item_model] if item_model is not None else None,
            http_options=types.HttpOptions(timeout=300_000),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        last_error: Exception | None = None
        while self.model_index < len(self.models):
            model = self.models[self.model_index]
            for attempt in range(3):
                try:
                    resp = self._gemini_client(model).models.generate_content(
                        model=model, contents=prompt, config=config)
                    self.last_model = model
                    text = resp.text or ""
                    if not text.strip():
                        raise LLMError("respuesta vacía de Gemini")
                    return text
                except LLMError as exc:
                    last_error = exc
                    if attempt < 2:
                        self.sleep(backoff_seconds(False, attempt))
                        continue
                    break
                except Exception as exc:  # errores del SDK
                    last_error = exc
                    if is_auth_error(exc) and not is_rate_limit_error(exc):
                        raise LLMError(f"Gemini rechazó la clave: {exc}") from exc
                    if is_unavailable_model_error(exc):
                        if (self.provider == "vertex" and model not in _GLOBAL_ONLY
                                and settings().vertex_location != "global"):
                            # En Vertex los modelos más nuevos solo están en `global`.
                            log.info("modelo %s no está en %s; pruebo el endpoint global",
                                     model, settings().vertex_location)
                            _GLOBAL_ONLY.add(model)
                            continue
                        log.warning("modelo %s no disponible para esta clave; siguiente", model)
                        _UNAVAILABLE.add(model)
                        break
                    if is_rate_limit_error(exc):
                        log.warning("cuota agotada en %s; se prueba el siguiente modelo", model)
                        break
                    if not is_retryable_error(exc):
                        raise LLMError(f"Gemini: {exc}") from exc
                    if attempt < 2:
                        self.sleep(backoff_seconds(False, attempt))
            self.model_index += 1  # siguiente modelo de la cadena
        if last_error is None:
            raise LLMError("la cadena de modelos de Gemini ya se agotó en este proyecto")
        raise LLMError(f"todos los modelos de Gemini fallaron: {last_error}")

    def _openai_generate(self, prompt: str, key: str) -> str:
        s = settings()
        headers = {"Content-Type": "application/json"}
        if s.llm_api_key:
            headers["Authorization"] = f"Bearer {s.llm_api_key}"
        body = {
            "model": s.llm_model,
            "temperature": 0.4,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": f'Responde solo con un objeto JSON {{"{key}": [...]}}.'},
                {"role": "user", "content": prompt},
            ],
        }
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                r = httpx.post(f"{s.llm_base_url}/chat/completions", headers=headers,
                               content=json.dumps(body), timeout=600)
                r.raise_for_status()
                self.last_model = s.llm_model
                return r.json()["choices"][0]["message"]["content"] or ""
            except Exception as exc:
                last_error = exc
                if not is_retryable_error(exc) or attempt == 2:
                    break
                self.sleep(backoff_seconds(is_rate_limit_error(exc), attempt))
        raise LLMError(f"LLM compatible con OpenAI falló: {last_error}")
