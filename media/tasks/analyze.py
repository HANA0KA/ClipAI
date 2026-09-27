"""Tarea `analyze` (plan 6.3): detección de momentos en dos etapas.

1 frases → 2 temas (TextTiling con embeddings + capítulos) → 3 candidatos
(ventanas 30–90 s, propuestas libres del LLM, picos del heatmap, temas
completos) → 4 señales (heatmap, audio, densidad, gancho) → 5 pre-filtro →
6 juez LLM con rúbrica de 5 ejes → 7 puntaje final → 8 NMS → 9 bordes limpios
y frase más fuerte. Sin LLM: puntaje solo con señales y kit heurístico.
Después, pulido con Whisper de los clips elegidos (plan 6.2) → captions.json.
"""
from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

import numpy as np

from media.config import settings
from media.errors import PermanentError
from media.services import candidates as cand_mod
from media.services import db, scoring, segmentation, texttiling_ops, whisper
from media.services.atomic import read_json, write_json
from media.services.cut_ops import clean_edges, detect_silences
from media.services.ffmpeg import extract_audio, ffmpeg_bin
from media.services.llm import LLM, LLMError
from media.services.moments import (Judged, Proposal, build_judge_prompt, build_propose_prompt,
                                    heuristic_kit, locate_phrase, prepend_span)
from media.services.transcript import words_in_range
from media.tasks.common import check_stop, clip_folder, log, progress, project_folder, require_project

POLISH_MARGIN = 2.0


def _text(sents: list[dict], c: dict) -> str:
    return " ".join(s["text"] for s in sents[c["i"]:c["j"] + 1])


def _relevance_without_llm(query: str, cands: list[dict]) -> None:
    """Modo «búscame un momento» sin IA: similitud semántica (o léxica)."""
    e = segmentation.embed([query] + [c["text"] for c in cands])
    if e is not None:
        sims = e[1:] @ e[0]
        for c, sim in zip(cands, sims):
            c["relevance"] = float(max(0.0, sim) * 10)
        return
    q = set(texttiling_ops.tokenize(query))
    for c in cands:
        toks = set(texttiling_ops.tokenize(c["text"]))
        c["relevance"] = 10.0 * len(q & toks) / max(1, len(q))


def _silences(folder: Path) -> list[tuple[float, float]]:
    cache = folder / "silences.json"
    data = read_json(cache)
    if data is None:
        data = detect_silences(str(folder / "audio.wav"), ffmpeg=ffmpeg_bin())
        write_json(cache, data)
    return [tuple(x) for x in data]


def select_moments(project: dict, folder: Path, data: dict, llm: LLM, on_stage=lambda *a: None) -> dict:
    """Pasos 2–9. Devuelve {"clips": [...], "candidates": [...], "meta": {...}}."""
    s = settings()
    lo, hi = s.clip_min_sec, s.clip_max_sec
    words, sents = data["words"], data["sentences"]
    info = read_json(folder / "source.info.json", {}) or {}
    duration = float(info.get("duration") or project.get("durationSec") or (words[-1]["end"] if words else 0))
    hm = info.get("heatmap") or None
    query = (project.get("query") or "").strip() or None
    language = data.get("language") or "es"

    on_stage(62, "Segmentando temas")
    cuts, seg_method = segmentation.topic_cuts(sents, info.get("chapters") or ())

    on_stage(66, "Generando candidatos")
    cands = list(cand_mod.windows(sents, cuts, lo, hi))
    cands += cand_mod.topic_windows(sents, cuts, lo, hi)
    cands += cand_mod.heatmap_windows(hm, sents, cuts, duration, lo, hi)
    llm_errors: list[str] = []
    if llm.available:
        on_stage(68, "La IA propone momentos")
        try:
            props = llm.generate_list(build_propose_prompt(sents, duration, max(10, s.max_clips + 4), lo, hi,
                                                           query, llm.max_prompt_chars), Proposal)
            for p in props:
                c = cand_mod.snap_to_sentences(p.start, p.end, sents, cuts, lo, hi, source="llm")
                if c:
                    c["llm_reason"] = p.reason
                    cands.append(c)
        except LLMError as exc:
            llm_errors.append(f"propuestas: {exc}")
            log.warning("propuestas del LLM fallaron: %s", exc)
    cands = cand_mod.dedupe(cands)
    if not cands:
        # Video corto o sin frases largas: un único candidato con todo lo que quepa.
        c = cand_mod.snap_to_sentences(0, min(duration, hi), sents, cuts, min(lo, duration * 0.8), hi, "window")
        if c is None:
            raise PermanentError("No hay tramos de 30–90 s con habla suficiente en este video.")
        cands = [c]

    on_stage(70, f"Midiendo señales de {len(cands)} candidatos")
    audio_path = folder / "audio.wav"
    audio_z = cand_mod.audio_profile(audio_path) if audio_path.exists() else np.zeros(0)
    for c in cands:
        c["text"] = _text(sents, c)
        c["signals"] = cand_mod.signals_for(c, words, hm, audio_z, duration)
    pre = scoring.prefilter(cands, s.prefilter_top)

    scored: list[dict] = []
    if llm.available:
        on_stage(74, f"La IA evalúa {len(pre)} candidatos")
        try:
            judged = llm.generate_list(build_judge_prompt(sents, pre, language, query, llm.max_prompt_chars), Judged)
            by_id = {j.id: j for j in judged if 0 <= j.id < len(pre)}
            for idx, c in enumerate(pre):
                j = by_id.get(idx)
                if j is None:
                    continue
                start, end = c["start"], c["end"]
                # El juez puede mover los bordes hasta 10 s.
                js, je = max(start - 10, min(start + 10, j.start)), max(end - 10, min(end + 10, j.end))
                if lo * 0.9 <= je - js <= hi * 1.05 and 0 <= js < je <= duration + 0.5:
                    start, end = js, je
                sig = cand_mod.signals_for({"start": start, "end": end}, words, hm, audio_z, duration)
                jd = j.model_dump()
                scored.append({**c, "start": start, "end": end, "signals": sig, "judge": jd,
                               "score": scoring.final_score(jd, sig)})
        except LLMError as exc:
            llm_errors.append(f"juez: {exc}")
            log.warning("juez LLM falló; se usan solo señales: %s", exc)
    llm_used = bool(scored)
    if not scored:
        for c in pre:
            scored.append({**c, "score": scoring.heuristic_score(c["signals"]), "judge": None})

    if query:
        if llm_used:
            for c in scored:
                c["relevance"] = float(c["judge"]["value"] + c["judge"]["reach"]) / 2
        else:
            _relevance_without_llm(query, scored)
        # Primero lo que cumple el criterio, luego el resto (plan 6.3).
        for c in scored:
            c["rank_key"] = (1 if c.get("relevance", 0) >= 5 else 0) * 1000 + c["score"]
    for c in scored:
        c.setdefault("rank_key", c["score"])

    on_stage(80, "Eligiendo los mejores")
    selected = scoring.nms(scored, max_overlap=0.3, per_topic=2, top=s.max_clips, key="rank_key")

    silences = _silences(folder)
    all_counts = Counter(texttiling_ops.tokenize(" ".join(x["text"] for x in sents)))
    clips = []
    for rank, c in enumerate(selected):
        start, end, edge_path = clean_edges(c["start"], c["end"], words, silences, source_duration=duration,
                                            max_duration=hi + 5)
        clip_sents = [x for x in sents if x["end"] > start and x["start"] < end]
        j = c.get("judge")
        if j:
            kit = {"title": j["title"] or "", "description": j["description"] or "",
                   "hashtags": " ".join(j["hashtags"][:5]), "hook": j["hook_text"] or "",
                   "reason": j["reason"] or c.get("llm_reason") or ""}
            fallback = heuristic_kit(clip_sents, all_counts)
            for k in kit:
                if not kit[k].strip():
                    kit[k] = fallback[k]
            if "#shorts" not in kit["title"].lower():
                kit["title"] = (kit["title"][:90] + " #Shorts").strip()
            best_line = j["best_line"]
        else:
            kit = heuristic_kit(clip_sents, all_counts)
            best_line = ""
        bl = locate_phrase(words, best_line, start, end) if best_line else None
        pre_span = prepend_span(words, bl, start)
        clips.append({
            "rank": rank, "startSec": start, "endSec": end, "score": int(c["score"]),
            "reason": kit["reason"][:500], "hook": kit["hook"][:120], "title": kit["title"][:100],
            "description": kit["description"][:500], "hashtags": kit["hashtags"][:200],
            "topic": int(c.get("topic", 0)), "bestLine": best_line[:300] or None,
            "bestLineStart": pre_span[0] if pre_span else None,
            "bestLineEnd": pre_span[1] if pre_span else None,
            "signals": {**c["signals"], "source": c["source"], "edges": edge_path,
                        "judge": {k: j[k] for k in ("hook", "story", "value", "engagement", "reach")} if j else None,
                        "relevance": c.get("relevance")},
        })
    meta = {"segmentation": seg_method, "topics": len(cuts) + 1, "candidates": len(cands),
            "prefiltered": len(pre), "llm": llm.label if llm_used else "heuristic", "llm_errors": llm_errors,
            "heatmap": bool(hm), "query": query}
    candidates_dump = [{k: v for k, v in c.items() if k not in ("text",)} for c in scored]
    return {"clips": clips, "candidates": candidates_dump, "meta": meta}


def polish_captions(project: dict, folder: Path, clip: dict, data: dict) -> dict:
    """Subtítulos exactos del clip: Whisper con 2 s de margen e idioma forzado."""
    s = settings()
    start, end = float(clip["startSec"]), float(clip["endSec"])
    if clip.get("bestLineStart") is not None:
        start = min(start, float(clip["bestLineStart"]))
    s0 = max(0.0, start - POLISH_MARGIN)
    e0 = end + POLISH_MARGIN
    base_words = words_in_range(data["words"], s0, e0)
    source = data.get("source") or "youtube"
    words = base_words
    if s.polish_with_whisper and source != "whisper":
        cfolder = clip_folder(project["id"], clip["id"])
        wav = cfolder / "clip.wav"
        try:
            extract_audio(folder / "source.mp4", wav, s0, e0)
            ws, _lang = whisper.transcribe(wav, language=data.get("language"))
            if len(ws) >= max(3, len(base_words) * 0.4):
                words = [{"w": w["w"], "start": round(w["start"] + s0, 3), "end": round(w["end"] + s0, 3)}
                         for w in ws]
                source = "whisper"
        except Exception as exc:
            log.warning("pulido Whisper falló en %s: %s", clip["id"], exc)
        finally:
            wav.unlink(missing_ok=True)
    return {"source": source, "range": [round(s0, 3), round(e0, 3)], "edited": False, "words": words}


def run_task(project_id: str, payload: dict) -> None:
    project = require_project(project_id)
    folder = project_folder(project_id)
    data = read_json(folder / "transcript.json", {}) or {}
    if not data.get("words"):
        raise RuntimeError("falta transcript.json (la transcripción no terminó)")
    s = settings()

    def stage(value, text):
        check_stop(project_id)
        progress(project_id, value, status="ANALYZING", stage=text)

    analysis_path = folder / "analysis.json"
    existing = db.list_clips(project_id)
    if analysis_path.exists() and existing and not payload.get("force"):
        log.info("análisis ya hecho (punto de control)")
        clips = existing
    else:
        llm = LLM()
        result = select_moments(project, folder, data, llm, stage)
        write_json(analysis_path, result)
        for old in existing:  # nuevo análisis: fuera los clips anteriores y sus archivos
            shutil.rmtree(folder / "clips" / old["id"], ignore_errors=True)
        db.delete_clips(project_id)
        clips = []
        for c in result["clips"]:
            cid = db.insert_clip(project_id, {**c, "signals": json.dumps(c["signals"], ensure_ascii=False)})
            clips.append(db.get_clip(cid))
        db.update_project(project_id, llmProvider=result["meta"]["llm"])

    # Pulido de los clips elegidos (punto de control por clip).
    for k, clip in enumerate(clips):
        cap_path = clip_folder(project_id, clip["id"]) / "captions.json"
        if not cap_path.exists():
            stage(85 + 10 * k / max(1, len(clips)), f"Puliendo subtítulos del clip {k + 1}/{len(clips)}")
            write_json(cap_path, polish_captions(project, folder, clip, data))
        db.update_clip(clip["id"], captionsPath=str(cap_path.relative_to(s.data_dir)))

    db.update_project(project_id, status="READY", progress=100, error=None,
                      stage=f"{len(clips)} clips listos")
    if s.auto_render:
        for clip in clips:
            if clip.get("renderStatus") in (None, "NONE", "FAILED") and not db.has_pending_job("render", clip["id"]):
                db.update_clip(clip["id"], renderStatus="QUEUED", renderError=None)
                db.enqueue_job("render", clip["id"], {})


__all__ = ["run_task", "select_moments", "polish_captions"]
