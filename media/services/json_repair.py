"""Lectura tolerante de respuestas JSON de un LLM (plan 6.8).

Adaptado de ClipPyMe — https://github.com/fralapo/clippyme
Ruta original: src/clippyme/pipeline/gemini_parser.py
(_extract_json_section, _clean_json, parse_gemini_response).
Copyright (c) 2026 ClippyMe — Licencia MIT (ver media/vendor/NOTICE.md).
Cambios: desacoplado de su esquema ViralClipsResponse; extrae el primer
objeto/array JSON aunque venga rodeado de prosa; valida con cualquier modelo
Pydantic (`parse_model`), descartando ítems inválidos en vez de todo el lote.

Cadena: 1 estricto → 2 limpieza determinista → 3 librería json_repair →
4 un reintento con el error como contexto (lo aporta quien llama) → 5 None.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional, TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

_DELIMITER_PATTERN = re.compile(r"(?:\*{0,2})#{2,4}\s*json\s*#{2,4}(?:\*{0,2})", re.IGNORECASE)
_CODE_FENCE_OPEN = re.compile(r"^\s*```(?:json)?\s*", re.IGNORECASE)
_CODE_FENCE_CLOSE = re.compile(r"\s*```\s*$")
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_LONE_BACKSLASH = re.compile(r'\\(?!["\\/bfnrtu])')
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass
class ParseResult:
    data: Any
    parse_path: str  # strict | clean | json_repair | retry | fallback
    error: Optional[str] = None


def _first_json_block(text: str) -> str:
    """Desde el primer '{' o '[' hasta su cierre equilibrado (ignorando cadenas)."""
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        return text
    i0 = min(starts)
    stack, in_str, esc = [], False, False
    for k in range(i0, len(text)):
        ch = text[k]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()
                if not stack:
                    return text[i0:k + 1]
    return text[i0:]  # sin cerrar: que lo intente reparar json_repair


def extract_json_section(text: str) -> str:
    """Aísla el JSON: descarta razonamiento previo, bloques de código y prosa."""
    text = text or ""
    matches = list(_DELIMITER_PATTERN.finditer(text))
    if matches:
        text = text[matches[-1].end():]
    text = _CODE_FENCE_OPEN.sub("", text)
    text = _CODE_FENCE_CLOSE.sub("", text)
    return _first_json_block(text.strip()).strip()


def clean_json(raw: str) -> str:
    """Comillas tipográficas, comas sobrantes, barras sueltas, controles."""
    raw = (raw.replace("“", '"').replace("”", '"')
              .replace("‘", "'").replace("’", "'"))
    raw = _TRAILING_COMMA.sub(r"\1", raw)
    raw = _LONE_BACKSLASH.sub(r"\\\\", raw)
    return _CONTROL_CHARS.sub("", raw)


def parse_json(text: str, retry_fn: Optional[Callable[[str], str]] = None) -> ParseResult:
    section = extract_json_section(text)
    try:
        return ParseResult(json.loads(section), "strict")
    except json.JSONDecodeError as e1:
        strict_err = f"{e1.msg}: line {e1.lineno} col {e1.colno}"
    try:
        return ParseResult(json.loads(clean_json(section)), "clean")
    except json.JSONDecodeError:
        pass
    try:
        from json_repair import repair_json
        data = json.loads(repair_json(section))
        if data not in ("", None):
            return ParseResult(data, "json_repair")
    except Exception:
        pass
    if retry_fn is not None:
        try:
            retry_text = retry_fn(strict_err)
            return ParseResult(json.loads(clean_json(extract_json_section(retry_text))), "retry")
        except Exception as e:
            return ParseResult(None, "fallback", f"retry failed: {e}; original: {strict_err}")
    return ParseResult(None, "fallback", strict_err)


M = TypeVar("M", bound=BaseModel)


def as_list(data: Any, key: str | None = None) -> list:
    """Acepta `[...]`, `{"key": [...]}` o `{"cualquier": [...]}` (primer array)."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if key and isinstance(data.get(key), list):
            return data[key]
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


def parse_model_list(data: Any, model: type[M], key: str | None = None) -> list[M]:
    """Valida cada ítem; los inválidos se descartan (no tumban el lote)."""
    out: list[M] = []
    for i, raw in enumerate(as_list(data, key)):
        try:
            out.append(model.model_validate(raw))
        except ValidationError as exc:
            log.warning("ítem %d descartado: %s", i, str(exc).splitlines()[0][:200])
    return out
