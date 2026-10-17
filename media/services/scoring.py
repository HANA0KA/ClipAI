"""Puntaje y selección. Funciones puras."""
from __future__ import annotations

AXES = ("hook", "story", "value", "engagement", "reach")
AXIS_WEIGHTS = {"hook": 0.30, "story": 0.25, "value": 0.20, "engagement": 0.15, "reach": 0.10}


def llm_score(j: dict) -> float:
    """S_LLM = 0.30 Hook + 0.25 Story + 0.20 Value + 0.15 Engagement + 0.10 Reach (0–10)."""
    return sum(w * max(0.0, min(10.0, float(j.get(axis, 0) or 0))) for axis, w in AXIS_WEIGHTS.items())


PAUSE_BONUS = 0.2


def hook_signal(sig: dict) -> float:
    """Gancho textual más la entrada limpia tras una pausa (≤ 1)."""
    return min(1.0, sig.get("hook", 0.0) + PAUSE_BONUS * sig.get("pause", 0.0))


def final_score(j: dict, sig: dict) -> int:
    """Score = 100 × (0.55 S_LLM/10 + 0.20 heat + 0.15 audio + 0.10 gancho).
    Sin heatmap su peso se reparte entre las demás señales. El gancho incluye
    la pausa previa (`hook_signal`)."""
    w = {"llm": 0.55, "heat": 0.20, "audio": 0.15, "hook": 0.10}
    if sig.get("heat") is None:
        w = {"llm": 0.65, "heat": 0.0, "audio": 0.22, "hook": 0.13}
    s = (w["llm"] * llm_score(j) / 10 + w["heat"] * (sig.get("heat") or 0.0)
         + w["audio"] * sig.get("audio", 0.0) + w["hook"] * hook_signal(sig))
    return int(round(100 * max(0.0, min(1.0, s))))


def quick_score(sig: dict) -> float:
    """Pre-filtro y puntaje del modo sin IA: solo señales objetivas."""
    w = {"heat": 0.35, "audio": 0.20, "density": 0.20, "hook": 0.25}
    if sig.get("heat") is None:
        w = {"heat": 0.0, "audio": 0.30, "density": 0.30, "hook": 0.40}
    return (w["heat"] * (sig.get("heat") or 0.0) + w["audio"] * sig.get("audio", 0.0)
            + w["density"] * sig.get("density", 0.0) + w["hook"] * hook_signal(sig))


def heuristic_score(sig: dict) -> int:
    """0–100 para el modo sin IA. Las señales rara vez llegan a 1 todas a la
    vez, así que se estira el rango para que el orden sea legible en la UI."""
    return int(round(100 * max(0.0, min(1.0, 0.15 + quick_score(sig) * 1.1))))


def overlap_ratio(c: dict, k: dict) -> float:
    """Solape relativo al más corto de los dos clips.

    El código del plan divide por la duración de ``c``; así un clip largo que
    contiene entero a uno mejor y corto pasa el filtro (p. ej. 26 s de 84 s =
    31 %) y la lista final repite el mismo momento. Medirlo sobre el más corto
    cumple la regla «se descarta si se solapa más de 30 % con uno mejor» en
    ambos sentidos.
    """
    inter = min(c["end"], k["end"]) - max(c["start"], k["start"])
    shorter = min(c["end"] - c["start"], k["end"] - k["start"])
    return max(0.0, inter) / max(1e-6, shorter)


def nms(clips: list[dict], max_overlap: float = 0.3, per_topic: int = 2, top: int = 8,
        key: str = "score") -> list[dict]:
    """Ordena por puntaje y descarta los que se solapan > max_overlap con uno
    mejor; máximo ``per_topic`` por tema; se queda con los ``top`` primeros."""
    keep: list[dict] = []
    topics: dict = {}
    for c in sorted(clips, key=lambda c: -c[key]):
        ov = max((overlap_ratio(c, k) for k in keep), default=0.0)
        if ov <= max_overlap and topics.get(c.get("topic"), 0) < per_topic:
            keep.append(c)
            topics[c.get("topic")] = topics.get(c.get("topic"), 0) + 1
        if len(keep) == top:
            break
    return keep


def prefilter(cands: list[dict], top: int = 30) -> list[dict]:
    """Los ``top`` mejores por señales, diversificados (sin casi-duplicados) y
    manteniendo siempre todas las propuestas del LLM.

    Primera pasada con solape ≤ 60 %; si no alcanza (videos cortos), se
    completa con variantes de solape ≤ 85 % para que el juez pueda elegir bordes.
    """
    llm = [c for c in cands if c.get("source") == "llm"]
    rest = [c for c in cands if c.get("source") != "llm"]
    for c in rest:
        c["quick"] = quick_score(c["signals"])
    ranked = sorted(rest, key=lambda c: -c["quick"])
    chosen: list[dict] = []
    for limit in (0.6, 0.85):
        for c in ranked:
            if len(chosen) >= top:
                break
            if any(c is k for k in chosen):
                continue
            if max((overlap_ratio(c, k) for k in chosen), default=0.0) <= limit:
                chosen.append(c)
    return llm + chosen
