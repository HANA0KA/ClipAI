"""Tarea `analyze`: detección de momentos en dos etapas.

1 frases → 2 temas (TextTiling con embeddings + capítulos) → 3 candidatos
(ventanas CLIP_MIN_SEC–CLIP_MAX_SEC, 60–150 s; propuestas libres del LLM,
picos del heatmap, temas completos) → 4 señales (heatmap, audio, densidad,
gancho, pausa previa) → 5 pre-filtro → 6 juez LLM con rúbrica de 5 ejes y
tipo de gancho → 7 puntaje final → 8 NMS → 9 arco narrativo de cada elegido
(gancho → contexto → desarrollo → remate: la duración la decide la historia,
máx. 150 s; apertura en frío si el inicio es flojo; hashtags por red) → 10
bordes limpios y duración dentro del rango. Sin LLM: puntaje con señales,
cierre natural por cambio de tema o pausa y kit heurístico. Después, pulido
con Whisper de los clips elegidos → captions.json.

Caché por fuente (services/source_cache.py): el mismo video con los mismos
parámetros reutiliza el análisis y el pulido sin gastar IA ni Whisper.
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
from media.services import (db, edit_doc, emoji_text, gapfill, glossary, hashtags, scoring, segmentation, source_cache,
                            story_arc, subtitle_style, texttiling_ops, whisper)
from media.services.atomic import read_json, write_json
from media.services.cut_ops import clean_edges, detect_silences, fit_duration
from media.services.ffmpeg import extract_audio, ffmpeg_bin
from media.services.llm import LLM, LLMBlocked, LLMError
from media.services.moments import (Judged, Proposal, build_judge_prompt, build_propose_prompt,
                                    heuristic_kit, locate_phrase, normalize_hook_type, pick_hook,
                                    prepend_span, sanitize_hook)
from media.services.transcript import snap_out_of_silence, words_in_range
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


MAX_JUDGE_CALLS = 12


def judge_candidates(llm: LLM, sents: list[dict], pre: list[dict], language: str, query: str | None,
                     lo: float, hi: float) -> tuple[dict[int, Judged], list[str]]:
    """Juez LLM sobre los candidatos del pre-filtro → {índice: Judged}.

    Si el proveedor bloquea el pedido por sus políticas (es determinista), se
    reintenta sin la transcripción completa y, si aún así se bloquea, se parten
    los candidatos en mitades hasta aislar el que lo provoca, que se descarta.
    Tope de llamadas para no gastar cuota. Otros errores se propagan."""
    notes: list[str] = []
    calls = {"n": 0}

    def run(idx: list[int], context: bool) -> dict[int, Judged]:
        calls["n"] += 1
        prompt = build_judge_prompt(sents, [pre[i] for i in idx], language, query, llm.max_prompt_chars,
                                    lo=lo, hi=hi, context=context)
        judged = llm.generate_list(prompt, Judged, temperature=0.2)  # calificar: consistente
        return {idx[j.id]: j for j in judged if 0 <= j.id < len(idx)}

    def bisect(idx: list[int]) -> dict[int, Judged]:
        try:
            return run(idx, False)
        except LLMBlocked:
            if len(idx) == 1 or calls["n"] >= MAX_JUDGE_CALLS:
                notes.append(f"{len(idx)} candidato(s) rechazado(s) por las políticas del proveedor")
                return {}
            mid = len(idx) // 2
            return {**bisect(idx[:mid]), **bisect(idx[mid:])}

    everything = list(range(len(pre)))
    try:
        return run(everything, True), notes
    except LLMBlocked as exc:
        log.warning("el juez fue bloqueado con la transcripción completa (%s); pruebo sin contexto", exc)
        notes.append("el proveedor rechazó la transcripción completa; se juzgó sin ella")
        return bisect(everything), notes


def clip_text_for_emoji(sents: list[dict]) -> str:
    """Texto del clip para elegir el emoji del tema si el gancho no trae uno."""
    return " ".join(x["text"] for x in sents[:6])


def plan_arcs(llm: LLM, selected: list[dict], sents: list[dict], language: str, lo: float, hi: float,
              duration: float, video: str = "") -> tuple[dict[int, story_arc.ArcPlan], list[str]]:
    """Estructura de todos los clips elegidos en una sola llamada."""
    if not llm.available or not selected:
        return {}, []
    try:
        plans = llm.generate_list(story_arc.build_arc_prompt(selected, sents, language, lo, hi, duration,
                                                             llm.max_prompt_chars, video), story_arc.ArcPlan,
                                  temperature=0.3)
        return {p.id: p for p in plans if 0 <= p.id < len(selected)}, []
    except LLMError as exc:
        log.warning("estructura de los clips con IA falló; uso el cierre natural: %s", exc)
        return {}, [f"estructura: {exc}"]


def arc_bounds(c: dict, plan, words: list[dict], sents: list[dict], cuts: list[int], *, lo: float, hi: float,
               duration: float) -> dict:
    """Bordes del clip según su historia: los del arco de la IA si son
    utilizables; si no, el cierre natural (cambio de tema o pausa); si no, los
    del candidato. {"start", "end", "hook_end", "teaser", "source"}."""
    arc = story_arc.resolve_arc(plan, c, words, sents, lo=lo, hi=hi, duration=duration) if plan else None
    if arc:
        return {**arc, "source": "llm"}
    natural = story_arc.heuristic_end(c["start"], sents, cuts, lo=lo, hi=hi, duration=duration)
    if natural:
        return {"start": c["start"], "end": natural, "hook_end": None, "teaser": None, "source": "heuristic"}
    return {"start": c["start"], "end": c["end"], "hook_end": None, "teaser": None, "source": "candidate"}


def drop_overlaps(clips: list[dict], max_overlap: float = 0.3) -> list[dict]:
    """Tras ajustar cada clip a su historia dos pueden pisarse: se queda el de
    mejor puntaje (misma regla que la selección: más de 30 % del más corto
    es el mismo momento). Mantiene el orden (del mejor al peor) y renumera."""
    kept: list[dict] = []
    for c in clips:
        ok = True
        for k in kept:
            inter = min(c["endSec"], k["endSec"]) - max(c["startSec"], k["startSec"])
            shorter = min(c["endSec"] - c["startSec"], k["endSec"] - k["startSec"])
            if inter > 0 and inter / max(1e-6, shorter) > max_overlap:
                ok = False
                break
        if ok:
            kept.append(c)
    for rank, c in enumerate(kept):
        c["rank"] = rank
    return kept


def select_moments(project: dict, folder: Path, data: dict, llm: LLM, on_stage=lambda *a: None) -> dict:
    """Pasos 2–10. Devuelve {"clips": [...], "candidates": [...], "meta": {...}}."""
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
                                                           query, llm.max_prompt_chars), Proposal,
                                      temperature=0.6)  # proponer: más variedad
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
            raise PermanentError(f"No hay tramos de {lo:.0f}–{hi:.0f} s con habla suficiente en este video.")
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
            by_id, notes = judge_candidates(llm, sents, pre, language, query, lo, hi)
            llm_errors.extend(f"juez: {n}" for n in notes)
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
        # Primero lo que cumple el criterio, luego el resto.
        for c in scored:
            c["rank_key"] = (1 if c.get("relevance", 0) >= 5 else 0) * 1000 + c["score"]
    for c in scored:
        c.setdefault("rank_key", c["score"])

    on_stage(80, "Eligiendo los mejores")
    selected = scoring.nms(scored, max_overlap=0.3, per_topic=2, top=s.max_clips, key="rank_key")

    silences = _silences(folder)
    all_counts = Counter(texttiling_ops.tokenize(" ".join(x["text"] for x in sents)))
    if llm_used:
        on_stage(82, "La IA estructura cada clip: gancho, desarrollo y remate")
    video = hashtags.video_label(info, project.get("title"))
    plans, arc_errors = plan_arcs(llm, selected, sents, language, lo, hi, duration, video) if llm_used else ({}, [])
    llm_errors.extend(arc_errors)
    clips = []
    for rank, c in enumerate(selected):
        plan = plans.get(rank)
        arc = arc_bounds(c, plan, words, sents, cuts, lo=lo, hi=hi, duration=duration)
        teaser = arc["teaser"] if s.auto_cold_open else None
        t_len = (teaser[1] - teaser[0]) if teaser else 0.0
        # El avance cuenta dentro del máximo: el clip entero nunca pasa de `hi`.
        lo_main, hi_main = max(0.0, lo - t_len), hi - t_len
        start, end, edge_path = clean_edges(arc["start"], arc["end"], words, silences, source_duration=duration,
                                            max_duration=hi_main)
        start, end, fit = fit_duration(start, end, words, lo=lo_main, hi=hi_main, source_duration=duration)
        if fit != "none":
            edge_path += "+" + fit
        if teaser and not (start + 3.0 <= teaser[0] and teaser[1] <= end):
            teaser = None  # el ajuste de bordes lo dejó fuera
        clip_sents = [x for x in sents if x["end"] > start and x["start"] < end]
        fallback = heuristic_kit(clip_sents, all_counts)
        j = c.get("judge")
        if j:
            kit = {"hashtags": " ".join(j["hashtags"][:5]), "hook": sanitize_hook(j["hook_text"]),
                   "reason": j["reason"] or c.get("llm_reason") or ""}
            for k in kit:
                if not kit[k].strip():
                    kit[k] = fallback[k]
            best_line = j["best_line"]
            hook_type = normalize_hook_type(j.get("hook_type")) or fallback["hook_type"]
        else:
            kit = fallback
            best_line = ""
            hook_type = fallback["hook_type"]
        # El arco conoce la estructura final: su gancho manda, salvo que tenga
        # defectos claros (genérico, repite lo que se oye…) y una alternativa no.
        hook_options: list[str] = []
        if plan is not None:
            hook_type = plan.hook_type or hook_type
            chosen = plan.hook_text if sanitize_hook(plan.hook_text) else kit["hook"]
            first_line = clip_sents[0]["text"] if clip_sents else ""
            picked, hook_options = pick_hook(chosen, [*plan.hook_options, kit["hook"]], first_line)
            kit["hook"] = picked or kit["hook"]
        # El gancho (con UN emoji al final) es a la vez el título, la descripción, el texto de la
        # portada y el nombre de los archivos.
        kit["hook"] = emoji_text.ensure(kit["hook"], hook_type, clip_text_for_emoji(clip_sents))
        kit["title"], kit["description"] = kit["hook"], ""
        clip_text = " ".join(x["text"] for x in clip_sents)
        tags = hashtags.heuristic_sets(clip_text, all_counts, language)
        if plan is not None:
            tags = hashtags.complete(hashtags.clean_sets(story_arc.hashtag_sets(plan), language), tags)
        if teaser:
            best_line = plan.teaser_quote if plan else best_line
            pre_span, prepend = teaser, True
        else:
            bl = locate_phrase(words, best_line, start, end) if best_line else None
            pre_span, prepend = prepend_span(words, bl, start), False
        spoken_hook = (arc["hook_end"] - start) if (arc["hook_end"] and arc["hook_end"] > start) else None
        clips.append({
            "rank": rank, "startSec": start, "endSec": end, "score": int(c["score"]),
            "reason": kit["reason"][:500], "hook": kit["hook"][:120], "hookType": hook_type,
            "title": kit["title"][:100],
            "description": kit["description"][:500], "hashtags": kit["hashtags"][:200],
            "hashtagSets": json.dumps(tags, ensure_ascii=False),
            "topic": int(c.get("topic", 0)), "bestLine": best_line[:300] or None,
            "bestLineStart": pre_span[0] if pre_span else None,
            "bestLineEnd": pre_span[1] if pre_span else None,
            "prependBestLine": bool(prepend and pre_span),
            "signals": {**c["signals"], "source": c["source"], "edges": edge_path,
                        "judge": {k: j[k] for k in ("hook", "story", "value", "engagement", "reach")} if j else None,
                        "relevance": c.get("relevance"),
                        "arc": {"source": arc["source"], "hook": (plan.hook_quote if plan else "")[:300],
                                "context": (plan.context if plan else "")[:300],
                                "payoff": (plan.payoff_quote if plan else "")[:300],
                                "reason": (plan.reason if plan else "")[:300],
                                "hook_options": hook_options,
                                "cold_open": bool(prepend), "hook_seconds": round(spoken_hook, 2) if spoken_hook else None,
                                "duration": round(end - start + (t_len if prepend else 0.0), 2)}},
        })
    clips = drop_overlaps(clips)
    meta = {"segmentation": seg_method, "topics": len(cuts) + 1, "candidates": len(cands),
            "prefiltered": len(pre), "llm": llm.label if llm_used else "heuristic", "llm_errors": llm_errors,
            "heatmap": bool(hm), "query": query, "ai_usage": dict(llm.usage) if llm.available else None}
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
    key = source_cache.project_key(project, folder)
    name = "polish-" + source_cache.signature({"range": [round(s0, 2), round(e0, 2)], "model": s.whisper_model,
                                               "engine": s.whisper_engine, "polish": s.polish_with_whisper,
                                               "lang": data.get("language")}) + ".json"
    cached = source_cache.load(key, name)
    if cached and cached.get("words"):
        return _fit_to_speech(cached, folder)
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
    result = {"source": source, "range": [round(s0, 3), round(e0, 3)], "edited": False, "words": words}
    source_cache.save(key, name, result)
    return _fit_to_speech(result, folder)


def _fit_to_speech(result: dict, folder: Path) -> dict:
    """Palabras de Whisper que cayeron dentro de un silencio real → a la voz
    de al lado (si no, la última palabra del remate queda sin subtítulo)."""
    if result.get("source") != "whisper":
        return result
    try:
        silences = _silences(folder)
    except Exception as exc:  # sin audio.wav no se corrige: el subtítulo sigue siendo válido
        log.warning("sin mapa de silencios para ajustar subtítulos: %s", exc)
        return result
    return {**result, "words": snap_out_of_silence(result["words"], silences)}


def channel_tags(folder: Path) -> tuple[list[str], list[str]]:
    """(delante, detrás): el hashtag del creador del video original y los
    fijos del canal (HASHTAGS_CREATOR, HASHTAGS_BASE)."""
    s = settings()
    creator = hashtags.creator_tag(read_json(folder / "source.info.json", {})) if s.hashtags_creator else None
    return ([creator] if creator else []) + hashtags.base_tags(s.hashtags_format), hashtags.base_tags(s.hashtags_base)


def with_channel_tags(result: dict, folder: Path) -> dict:
    """Suma las etiquetas del canal a cada clip (kit y juegos por red)."""
    lead, tail = channel_tags(folder)
    if not lead and not tail:
        return result
    video = hashtags.video_label(read_json(folder / "source.info.json", {}))
    clips = []
    for c in result.get("clips") or []:
        try:
            sets = json.loads(c.get("hashtagSets") or "{}") or {}
        except ValueError:
            sets = {}
        clips.append({**c, "hashtags": hashtags.apply_niche_line(c.get("hashtags") or "", lead, tail)[:200],
                      "hashtagSets": json.dumps(hashtags.apply_niche(sets, lead, tail, video), ensure_ascii=False)})
    return {**result, "clips": clips}


def analysis_signature(project: dict, llm: LLM) -> str:
    s = settings()
    return source_cache.signature({
        "query": (project.get("query") or "").strip().lower(), "lo": s.clip_min_sec, "hi": s.clip_max_sec,
        "arc": 1, "cold_open": s.auto_cold_open, "max_clips": s.max_clips, "prefilter": s.prefilter_top,
        "llm": llm.provider, "embeddings": s.embeddings_enabled,
    })


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
        key = source_cache.project_key(project, folder)
        cache_name = f"analysis-{analysis_signature(project, llm)}.json"
        result = None if payload.get("force") else source_cache.load(key, cache_name)
        if result and result.get("clips"):
            log.info("análisis reutilizado de la caché (%s)", key)
            stage(80, "Reutilizando el análisis de este video")
        else:
            try:
                result = select_moments(project, folder, data, llm, stage)
            finally:
                db.add_ai_usage(project_id, llm.usage)  # lo gastado cuenta aunque el análisis falle
            if result["meta"].get("llm") != "heuristic" or not llm.available:
                source_cache.save(key, cache_name, result)  # un análisis degradado no se guarda
        result = with_channel_tags(result, folder)  # después de la caché: cambiar HASHTAGS_BASE no rehace el análisis
        write_json(analysis_path, result)
        for old in existing:  # nuevo análisis: fuera los clips anteriores y sus archivos
            shutil.rmtree(folder / "clips" / old["id"], ignore_errors=True)
        db.delete_clips(project_id)
        # Mismo estilo de subtítulos en todo el proyecto, distinto al de los últimos proyectos.
        template_id = subtitle_style.resolve(project)
        clips = []
        for c in result["clips"]:
            cid = db.insert_clip(project_id, {**c, "templateId": template_id,
                                              "signals": json.dumps(c["signals"], ensure_ascii=False)})
            clips.append(db.get_clip(cid))
        db.update_project(project_id, llmProvider=result["meta"]["llm"])

    # Pulido de los clips elegidos (punto de control por clip).
    for k, clip in enumerate(clips):
        cfolder = clip_folder(project_id, clip["id"])
        cap_path = cfolder / "captions.json"
        if not cap_path.exists():
            stage(85 + 10 * k / max(1, len(clips)), f"Puliendo subtítulos del clip {k + 1}/{len(clips)}")
            caps = polish_captions(project, folder, clip, data)
            words = caps["words"]
            if caps.get("source") == "whisper":  # Whisper a veces se salta habla que YouTube sí trae
                ranges = [(float(clip["startSec"]), float(clip["endSec"]))]
                if clip.get("prependBestLine") and clip.get("bestLineStart") is not None:
                    ranges.append((float(clip["bestLineStart"]), float(clip["bestLineEnd"])))
                words, added = gapfill.fill(words, data["words"], ranges)
                if added:
                    log.info("clip %s: %d palabras que faltaban se completaron con la transcripción", clip["id"], added)
            # Glosario de correcciones (data/glossary.json): lo que siempre se transcribe mal.
            write_json(cap_path, {**caps, "words": glossary.apply(words)[0]})
        original = cfolder / "original.json"
        if not original.exists():  # base de «Restaurar original» en el estudio
            write_json(original, edit_doc.original_snapshot(clip, read_json(cap_path, {})))
        db.update_clip(clip["id"], captionsPath=str(cap_path.relative_to(s.data_dir)))

    db.update_project(project_id, status="READY", progress=100, error=None,
                      stage=f"{len(clips)} clips listos")
    if s.auto_render:
        for clip in clips:
            if clip.get("renderStatus") in (None, "NONE", "FAILED") and not db.has_pending_job("render", clip["id"]):
                db.update_clip(clip["id"], renderStatus="QUEUED", renderError=None)
                db.enqueue_job("render", clip["id"], {})


__all__ = ["run_task", "select_moments", "polish_captions"]
