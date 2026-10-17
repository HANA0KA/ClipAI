"""Cliente LLM: Gemini con cadena de modelos, u cualquier API compatible con OpenAI.

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

Bloqueos por política y costo, adaptados de OpenShorts —
https://github.com/mutonby/openshorts
Rutas originales: gemini_worker.py (raise_if_blocked, _calculate_cost_analysis)
y clip_selection.py (MODEL_PRICES, lookup_model_prices).
Copyright (c) 2024 OpenShorts — Licencia MIT (ver media/vendor/NOTICE.md).
Cambios: un bloqueo corta la cadena de modelos (es determinista: reintentar
solo gasta cuota) y el uso se acumula por instancia (una por proyecto o render).
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Callable, TypeVar

import httpx
from pydantic import BaseModel

from media.config import settings
from media.services.json_repair import parse_json, parse_model_list

log = logging.getLogger(__name__)
M = TypeVar("M", bound=BaseModel)

# Instrucción de sistema de todas las llamadas: fija el papel y, sobre todo,
# que nada se invente (las citas se buscan después en las palabras reales).
SYSTEM_INSTRUCTION = (
    "Eres editor experto en clips cortos para TikTok, Instagram Reels y YouTube Shorts. "
    "Trabajas solo con la transcripción que recibes: las citas son literales, los segundos salen de "
    "la transcripción y nunca inventas datos, nombres, cifras ni hechos que no se dicen. Escribes en "
    "el idioma del video, con naturalidad y sin clickbait engañoso: cada promesa la cumple el clip. "
    "Respondes solo con JSON válido que cumpla el esquema pedido."
)
DEFAULT_TEMPERATURE = 0.4


def _or_default(t: float | None) -> float:
    return DEFAULT_TEMPERATURE if t is None else t


def model_temperature(model: str | None, wanted: float | None = None) -> float | None:
    """Temperatura para ``model``: la de la tarea en Gemini 2.x y modelos
    locales; None (la del modelo, 1.0) en Gemini 3 o posterior, como pide
    Google: bajarla ahí puede provocar bucles o peor razonamiento."""
    name = str(model or "").lower().split("/")[-1]
    m = re.match(r"gemini-(\d+)", name)
    if (m and int(m.group(1)) >= 3) or (name.startswith("gemini-") and "latest" in name):
        return None
    return DEFAULT_TEMPERATURE if wanted is None else float(wanted)


class LLMError(RuntimeError):
    pass


class LLMBlocked(LLMError):
    """El proveedor rechazó el pedido por sus políticas de contenido. Es
    determinista (el mismo texto se rechaza siempre y en todos los modelos),
    así que no se reintenta: quien llama decide si parte el pedido."""


_BLOCKED_FINISH_REASONS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "IMAGE_SAFETY", "RECITATION"}


def blocked_reason(resp) -> str | None:
    """Motivo del bloqueo de una respuesta de Gemini, o None."""
    reason = getattr(getattr(resp, "prompt_feedback", None), "block_reason", None)
    if reason:
        return getattr(reason, "name", None) or str(reason)
    for cand in getattr(resp, "candidates", None) or []:
        fr = getattr(cand, "finish_reason", None)
        name = (getattr(fr, "name", None) or str(fr or "")).upper().rsplit(".", 1)[-1]
        if name in _BLOCKED_FINISH_REASONS:
            return name
    return None


# USD por millón de tokens (entrada, salida con razonamiento, ¿estimado?):
# precios de lista de Google (ai.google.dev; Vertex cobra lo mismo). Se busca
# el prefijo más largo. Los marcados como estimados, y cualquier modelo que no
# esté aquí (PRICE_FALLBACK), se muestran con «≈».
MODEL_PRICES = {
    "gemini-3.5-flash-lite": (0.25, 1.50, True),  # sin precio publicado a la vista: como 3.1-flash-lite
    "gemini-3.5-flash": (1.50, 9.00, False),
    "gemini-3.1-flash-lite": (0.25, 1.50, False),
    "gemini-3-flash": (0.50, 3.00, False),
    "gemini-2.5-flash-lite": (0.10, 0.40, False),
    "gemini-2.5-flash": (0.30, 2.50, False),
    "gemini-2.5-pro": (1.25, 10.00, False),
    "gemini-2.0-flash": (0.10, 0.40, False),
}
PRICE_FALLBACK = (0.50, 3.00, True)


def model_prices(model: str | None) -> tuple[float, float, bool]:
    """(entrada, salida, estimado) en USD por millón de tokens."""
    name = str(model or "").lower().split("/")[-1]
    best = max((k for k in MODEL_PRICES if name.startswith(k)), key=len, default=None)
    return MODEL_PRICES[best] if best else PRICE_FALLBACK


def new_usage() -> dict:
    return {"calls": 0, "prompt_tokens": 0, "output_tokens": 0, "thinking_tokens": 0,
            "cost_usd": 0.0, "estimated": False}


# ── Clasificación de errores ───────────────────────────────────────────

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


def _response_text(resp) -> str:
    """Texto de la respuesta; ``resp.text`` puede lanzar si no hay partes."""
    try:
        text = resp.text
        if text:
            return text
    except Exception:
        pass
    parts = []
    for cand in getattr(resp, "candidates", None) or []:
        for part in getattr(getattr(cand, "content", None), "parts", None) or []:
            if getattr(part, "text", None):
                parts.append(part.text)
    return "\n".join(parts)


def _drop_rejected_params(body: dict, detail: str) -> bool:
    """Quita de ``body`` los parámetros opcionales que el servidor dice no admitir
    (p. ej. ``temperature`` en los modelos de razonamiento de OpenAI o
    ``response_format`` en algunos servidores compatibles). True si quitó alguno."""
    detail = detail.lower()
    dropped = [k for k in ("temperature", "response_format") if k in body and k in detail]
    for k in dropped:
        del body[k]
    return bool(dropped)


def _is_local_url(url: str) -> bool:
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or host.endswith(".local")


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
    modelo preferido en cada proyecto nuevo."""

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
        self.usage = new_usage()  # tokens y costo de todas las llamadas de esta instancia

    def _record(self, model: str, prompt: int, output: int, thinking: int = 0, *, local: bool = False) -> None:
        """Suma el uso de una llamada. El razonamiento se cobra como salida."""
        u = self.usage
        u["calls"] += 1
        u["prompt_tokens"] += int(prompt or 0)
        u["output_tokens"] += int(output or 0)
        u["thinking_tokens"] += int(thinking or 0)
        if local:
            return  # servidor propio: sin costo por token
        pin, pout, estimated = model_prices(model)
        u["cost_usd"] += (int(prompt or 0) * pin + (int(output or 0) + int(thinking or 0)) * pout) / 1_000_000
        u["estimated"] = u["estimated"] or estimated

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
    def generate_list(self, prompt: str, item_model: type[M], key: str = "items", *,
                      temperature: float | None = None) -> list[M]:
        """Genera y valida una lista de `item_model`. Lanza LLMError si falla.
        ``temperature``: la de la tarea (baja para calificar, más alta para
        proponer); en Gemini 3+ se usa la del modelo (`model_temperature`)."""
        text = self._generate(prompt, item_model, key, temperature)
        result = parse_json(text, retry_fn=lambda err: self._generate(
            REFORMAT_PROMPT.format(err=err, broken=text[:20000]), None, key, 0.0))
        if result.data is None:
            raise LLMError(f"respuesta no es JSON válido ({result.error})")
        items = parse_model_list(result.data, item_model, key)
        if not items:
            raise LLMError("la respuesta no contenía elementos válidos")
        log.info("LLM %s: %d elementos (lectura: %s)", self.label, len(items), result.parse_path)
        return items

    # ── Proveedores ──────────────────────────────────────────────────────────
    def _generate(self, prompt: str, item_model: type[BaseModel] | None, key: str,
                  temperature: float | None = None) -> str:
        if self.provider in ("gemini", "vertex"):
            return self._gemini_generate(prompt, item_model, temperature)
        if self.provider == "openai":
            return self._openai_generate(prompt, key, temperature)
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

    def _gemini_generate(self, prompt: str, item_model: type[BaseModel] | None,
                         temperature: float | None = None) -> str:
        from google.genai import types

        def config_for(model: str):
            return types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=model_temperature(model, temperature),
                response_mime_type="application/json",
                response_schema=list[item_model] if item_model is not None else None,
                http_options=types.HttpOptions(timeout=300_000),
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )

        last_error: Exception | None = None
        while self.model_index < len(self.models):
            model = self.models[self.model_index]
            config = config_for(model)
            for attempt in range(3):
                try:
                    resp = self._gemini_client(model).models.generate_content(
                        model=model, contents=prompt, config=config)
                    self.last_model = model
                    meta = getattr(resp, "usage_metadata", None)
                    if meta is not None:
                        self._record(model, getattr(meta, "prompt_token_count", 0) or 0,
                                     getattr(meta, "candidates_token_count", 0) or 0,
                                     getattr(meta, "thoughts_token_count", 0) or 0)
                    reason = blocked_reason(resp)
                    if reason:
                        raise LLMBlocked(f"Gemini rechazó el contenido por sus políticas ({reason})")
                    text = _response_text(resp)
                    if not text.strip():
                        raise LLMError("respuesta vacía de Gemini")
                    return text
                except LLMBlocked:
                    raise  # determinista: ni reintento ni otro modelo
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

    def _openai_generate(self, prompt: str, key: str, temperature: float | None = None) -> str:
        s = settings()
        headers = {"Content-Type": "application/json"}
        if s.llm_api_key:
            headers["Authorization"] = f"Bearer {s.llm_api_key}"
        body = {
            "model": s.llm_model,
            "temperature": _or_default(model_temperature(s.llm_model, temperature)),
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_INSTRUCTION
                 + f' Responde solo con un objeto JSON {{"{key}": [...]}}.'},
                {"role": "user", "content": prompt},
            ],
        }
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                r = httpx.post(f"{s.llm_base_url}/chat/completions", headers=headers,
                               content=json.dumps(body), timeout=600)
                if r.status_code == 400 and _drop_rejected_params(body, r.text):
                    continue  # el modelo no admite esos parámetros: se reintenta sin ellos
                if r.is_error:
                    raise RuntimeError(f"{r.status_code} {r.reason_phrase}: {r.text[:300]}")
                self.last_model = s.llm_model
                data = r.json()
                usage = data.get("usage") or {}
                self._record(s.llm_model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
                             local=_is_local_url(s.llm_base_url))
                return data["choices"][0]["message"]["content"] or ""
            except Exception as exc:
                last_error = exc
                if not is_retryable_error(exc) or attempt == 2:
                    break
                self.sleep(backoff_seconds(is_rate_limit_error(exc), attempt))
        raise LLMError(f"LLM compatible con OpenAI falló: {last_error}")
