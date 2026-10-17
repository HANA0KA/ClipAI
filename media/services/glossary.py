"""Glosario de correcciones: palabras que Whisper o YouTube transcriben mal
siempre («cloud code» → «Claude Code», «ibay» → «Ibai»).

Vive en ``data/glossary.json`` (``{"rules": [{"from", "to"}]}``), lo edita la
web (estudio → Palabras) y aquí se aplica a los subtítulos de cada clip nuevo
al crearlos. La misma lógica está en ``web/lib/glossary.ts`` (deben coincidir).

* Coincide sin mayúsculas ni signos pegados a la palabra («ibay,» → «Ibai,»);
  los acentos sí cuentan («esta» ≠ «está»).
* La regla puede ser de varias palabras seguidas. Con el mismo número de
  palabras se reemplaza una a una; con otro número, la primera lleva todo el
  texto y las demás quedan vacías (no se queman, pero conservan su tiempo).
"""
from __future__ import annotations

import re

from media.config import settings
from media.services.atomic import read_json

MAX_RULES = 500
MAX_TEXT = 60
_SPLIT = re.compile(r"^([\W_]*)(.*?)([\W_]*)$", re.S)


def path():
    return settings().data_dir / "glossary.json"


def _parts(word: str) -> tuple[str, str, str]:
    m = _SPLIT.match(word or "")
    return m.groups() if m else ("", word or "", "")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def clean_rules(raw) -> list[dict]:
    """Reglas válidas: texto de 1 a 60 caracteres, distintas de su reemplazo,
    una por «from» (sin mayúsculas; la última manda)."""
    seen: dict[str, dict] = {}
    for r in raw or []:
        if not isinstance(r, dict):
            continue
        src, dst = _norm(r.get("from"))[:MAX_TEXT], _norm(r.get("to"))[:MAX_TEXT]
        if src and dst and src != dst:
            seen[src.casefold()] = {"from": src, "to": dst}
    return list(seen.values())[:MAX_RULES]


def load() -> list[dict]:
    data = read_json(path(), {}) or {}
    return clean_rules(data.get("rules") if isinstance(data, dict) else None)


def _compiled(rules: list[dict]) -> list[tuple[list[str], list[str]]]:
    out = []
    for r in clean_rules(rules):
        src = [_parts(t)[1].casefold() for t in r["from"].split()]
        if all(src):
            out.append((src, r["to"].split()))
    return sorted(out, key=lambda x: -len(x[0]))  # primero las frases más largas


def apply(words: list[dict], rules: list[dict] | None = None) -> tuple[list[dict], int]:
    """(palabras corregidas, cuántas coincidencias). No modifica la lista de
    entrada; cada palabra es ``{"w", "start", "end", ...}``."""
    compiled = _compiled(load() if rules is None else rules)
    if not compiled or not words:
        return words, 0
    out = [dict(w) for w in words]
    cores = [_parts(w.get("w", ""))[1].casefold() for w in out]
    hits, i = 0, 0
    while i < len(out):
        for src, dst in compiled:
            n = len(src)
            if i + n > len(out) or cores[i:i + n] != src:
                continue
            lead, suffix = _parts(out[i].get("w", ""))[0], _parts(out[i + n - 1].get("w", ""))[2]
            same = len(dst) == n
            new = dst if same else [" ".join(dst)] + [""] * (n - 1)
            end = n - 1 if same else 0  # dónde queda el signo final («code,»)
            changed = False
            for k in range(n):
                head = lead if k == 0 else _parts(out[i + k].get("w", ""))[0]
                tail = suffix if k == end else _parts(out[i + k].get("w", ""))[2]
                text = (head + new[k] + tail) if new[k] else ""
                if text != out[i + k].get("w"):
                    out[i + k]["w"] = text
                    changed = True
            hits += changed
            i += n - 1
            break
        i += 1
    return out, hits


__all__ = ["apply", "clean_rules", "load", "path", "MAX_RULES", "MAX_TEXT"]
