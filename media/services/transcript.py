"""Transcripciones: subtítulos de YouTube (json3/VTT) → palabras → frases.

Formato común de palabra: ``{"w": str, "start": float, "end": float}`` con
tiempos absolutos en segundos. Funciones puras (plan 6.2), sin dependencias.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

# Anotaciones que no son habla: [Música], [Aplausos], (risas), ♪…
_NOISE_RE = re.compile(r"^[\[\(♪].*[\]\)♪]$|^♪+$")
_SENTENCE_END_RE = re.compile(r"[.?!…]['\")\]»]*$")


def _clean_token(text: str) -> str:
    return html.unescape(text).replace("​", "").replace("\n", " ").strip()


def _spread(text: str, start: float, end: float) -> list[dict]:
    """Reparte un tramo con varias palabras en proporción a su longitud."""
    tokens = [t for t in _clean_token(text).split() if t]
    tokens = [t for t in tokens if not _NOISE_RE.match(t)]
    if not tokens:
        return []
    end = max(end, start + 0.05 * len(tokens))
    total = sum(len(t) + 1 for t in tokens)
    out, t = [], start
    for tok in tokens:
        dur = (end - start) * (len(tok) + 1) / total
        out.append({"w": tok, "start": round(t, 3), "end": round(t + dur, 3)})
        t += dur
    return out


def _finalize(words: list[dict]) -> list[dict]:
    """Orden, sin solapes ni duraciones negativas, sin ruido."""
    words = [w for w in words if w["w"] and not _NOISE_RE.match(w["w"])]
    words.sort(key=lambda w: w["start"])
    out: list[dict] = []
    for w in words:
        if out and w["start"] < out[-1]["start"] + 1e-3 and w["w"] == out[-1]["w"]:
            continue  # duplicado exacto
        if out and out[-1]["end"] > w["start"]:
            out[-1]["end"] = max(out[-1]["start"] + 0.02, w["start"])
        if w["end"] <= w["start"]:
            w["end"] = w["start"] + 0.1
        out.append(w)
    return out


def parse_json3(path: Path) -> list[dict]:
    """Subtítulos json3 de YouTube → palabras con tiempo.

    Los automáticos traen cada palabra con su desfase (``tOffsetMs``); los
    eventos ``aAppend`` son los duplicados de *rollup* y se descartan. Los
    manuales traen la línea entera en un segmento: se reparte por longitud.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    words: list[dict] = []
    for ev in data.get("events", []):
        if ev.get("aAppend") or "segs" not in ev:
            continue
        t0 = ev.get("tStartMs", 0)
        dur = ev.get("dDurationMs", 0)
        segs = [s for s in ev["segs"] if _clean_token(s.get("utf8", ""))]
        for i, s in enumerate(segs):
            start = (t0 + s.get("tOffsetMs", 0)) / 1000
            nxt = segs[i + 1].get("tOffsetMs", dur) if i + 1 < len(segs) else dur
            end = (t0 + max(nxt, s.get("tOffsetMs", 0))) / 1000
            text = _clean_token(s["utf8"])
            if " " in text:
                words.extend(_spread(text, start, end))
            else:
                words.append({"w": text, "start": round(start, 3), "end": round(end, 3)})
    return _finalize(words)


_VTT_TIME = r"(?:\d+:)?\d{2}:\d{2}\.\d{3}"
_CUE_RE = re.compile(rf"^({_VTT_TIME})\s+-->\s+({_VTT_TIME})")
_INLINE_RE = re.compile(rf"<({_VTT_TIME})>")
_TAG_RE = re.compile(r"</?[^>]+>")


def _vtt_seconds(ts: str) -> float:
    parts = ts.split(":")
    secs = float(parts[-1])
    mins = int(parts[-2]) if len(parts) >= 2 else 0
    hours = int(parts[-3]) if len(parts) >= 3 else 0
    return hours * 3600 + mins * 60 + secs


def parse_vtt(path: Path) -> list[dict]:
    """WebVTT (respaldo de json3). En los automáticos solo se usan las líneas
    con marcas por palabra ``<00:00:01.234>``: las demás repiten la anterior."""
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    cues: list[tuple[float, float, list[str]]] = []
    i = 0
    while i < len(lines):
        m = _CUE_RE.match(lines[i].strip())
        if not m:
            i += 1
            continue
        start, end = _vtt_seconds(m.group(1)), _vtt_seconds(m.group(2))
        body = []
        i += 1
        while i < len(lines) and lines[i].strip():
            body.append(lines[i])
            i += 1
        cues.append((start, end, body))

    has_inline = any(_INLINE_RE.search(line) for _, _, body in cues for line in body)
    words: list[dict] = []
    for start, end, body in cues:
        if has_inline:
            for line in body:
                if not _INLINE_RE.search(line):
                    continue
                pieces = re.split(rf"(<{_VTT_TIME}>)", line)
                t = start
                stamps: list[tuple[float, str]] = []
                for piece in pieces:
                    mm = _INLINE_RE.fullmatch(piece)
                    if mm:
                        t = _vtt_seconds(mm.group(1))
                        continue
                    text = _clean_token(_TAG_RE.sub("", piece))
                    if text:
                        stamps.append((t, text))
                for k, (t_k, text) in enumerate(stamps):
                    t_next = stamps[k + 1][0] if k + 1 < len(stamps) else end
                    words.extend(_spread(text, t_k, max(t_next, t_k + 0.05)))
        else:
            text = _clean_token(_TAG_RE.sub("", " ".join(body)))
            words.extend(_spread(text, start, end))
    return _finalize(words)


def words_from_snippets(snippets: list[dict]) -> list[dict]:
    """youtube-transcript-api: fragmentos {text, start, duration} → palabras."""
    words: list[dict] = []
    for s in snippets:
        start = float(s.get("start", 0))
        words.extend(_spread(str(s.get("text", "")), start, start + float(s.get("duration", 0) or 0)))
    return _finalize(words)


def _is_original_auto(key: str, lang: str) -> bool:
    """Automáticos originales: `es`, `es-orig` o `es-es` (yt-dlp nombra las
    traducciones `destino-origen`, p. ej. `en-es` = inglés traducido del español)."""
    return key in (lang, f"{lang}-orig", f"{lang}-{lang}")


def source_language(info: dict) -> str:
    """Idioma del video: `language` de info.json o, si falta, el de los
    subtítulos automáticos originales (`xx-orig` / `xx-xx`)."""
    lang = (info.get("language") or "").split("-")[0].lower()
    if lang:
        return lang
    for key in info.get("automatic_captions") or {}:
        parts = key.lower().split("-")
        if len(parts) == 2 and (parts[1] == "orig" or parts[0] == parts[1]):
            return parts[0]
    manual = list(info.get("subtitles") or {})
    for pref in ("es", "en"):
        if any(k.split("-")[0] == pref for k in manual):
            return pref
    return manual[0].split("-")[0] if manual else "es"


def subtitle_langs(info: dict) -> list[str]:
    """Pistas a pedir a yt-dlp: solo las del idioma del video (nunca traducciones)."""
    lang = source_language(info)
    manual = [k for k in (info.get("subtitles") or {}) if k.split("-")[0].lower() == lang]
    return list(dict.fromkeys([*manual, lang, f"{lang}-orig", f"{lang}-{lang}"]))


def pick_track(folder: Path, info: dict) -> tuple[Path | None, str | None, str]:
    """Elige subtítulos: manuales antes que automáticos, en el idioma del video,
    nunca traducciones automáticas. Devuelve (archivo, 'manual'|'auto', idioma)."""
    lang = source_language(info)
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    order = [("manual", k) for k in dict.fromkeys(
        [lang, *sorted(k for k in manual if k.split("-")[0].lower() == lang)]) if k in manual]
    order += [("auto", k) for k in (f"{lang}-orig", f"{lang}-{lang}", lang)
              if k in auto and _is_original_auto(k, lang)]
    for kind, key in order:
        for ext in ("json3", "vtt"):
            f = folder / f"source.{key}.{ext}"
            if f.exists():
                return f, kind, lang
    return None, None, lang


def parse_subtitle_file(path: Path) -> list[dict]:
    return parse_json3(path) if path.suffix == ".json3" else parse_vtt(path)


def to_sentences(words: list[dict], max_gap: float = 0.7, max_words: int = 30) -> list[dict]:
    """Frases por puntuación o, si no hay, por pausas: los subtítulos
    automáticos casi no traen puntos. Cada frase guarda sus índices de palabra."""
    out, cur, first = [], [], 0
    for i, w in enumerate(words):
        if not cur:
            first = i
        cur.append(w)
        gap = words[i + 1]["start"] - w["end"] if i + 1 < len(words) else 99.0
        if _SENTENCE_END_RE.search(w["w"]) or gap > max_gap or len(cur) >= max_words:
            out.append({"text": " ".join(x["w"] for x in cur), "start": cur[0]["start"],
                        "end": cur[-1]["end"], "w0": first, "w1": i})
            cur = []
    return out


def words_in_range(words: list[dict], start: float, end: float) -> list[dict]:
    """Palabras cuyo centro cae dentro de [start, end)."""
    return [w for w in words if start <= (w["start"] + w["end"]) / 2 < end]


def plain_text(words: list[dict]) -> str:
    return " ".join(w["w"] for w in words)
