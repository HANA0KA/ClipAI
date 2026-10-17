"""Segmentación temática léxica (sin IA), al estilo TextTiling de Hearst (1997).

Se usa como respaldo de `services/segmentation.py` cuando el modelo de embeddings no
está disponible (EMBEDDINGS_ENABLED=0 o sin descarga). Pasos: cada bloque de texto se
reduce a sus palabras con contenido; se mide qué tanto vocabulario comparten las
ventanas a ambos lados de cada hueco entre bloques; esa curva se suaviza; un valle
profundo (poca cohesión entre dos zonas muy cohesionadas) marca un cambio de tema.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

# Palabras funcionales (español primero, luego inglés). Se descartan porque aparecen en
# todos los bloques y ahogarían la señal del vocabulario propio de cada tema.
_STOPWORDS = frozenset(
    ("el la los las un una unos unas lo al del de y e o u ni que qué quien quién cual cuál "
     "cuando cuándo donde dónde como cómo cuanto porque pues pero sino aunque si no sí ya "
     "muy más menos tan tanto todo todos toda todas nada algo alguien nadie otro otra otros "
     "en a con por para sin sobre entre hasta desde hacia según tras ante bajo "
     "yo tú vos usted él ella nosotros ustedes ellos ellas me te se nos os le les mi mis tu "
     "tus su sus este esta estos estas ese esa esos esas esto eso aquí ahí allí también "
     "ser es son fue era eran soy eres somos sido estar está están estoy estaba hay había "
     "haber he has ha han hemos tener tengo tiene tienen ir va van voy vamos bueno entonces "
     "the an of to in is it and or but for on at by with as be this that these those "
     "i you he she we they him her us them my your his our their its do does did not "
     "no yes so if then than too very can will just have had was were are am been").split()
)

_WORD = re.compile(r"[^\W\d_]+")  # letras unicode, sin dígitos ni signos


def tokenize(text: str) -> list[str]:
    """Palabras en minúscula, sin dígitos y sin palabras funcionales."""
    words = (m.group(0).lower() for m in _WORD.finditer(text or ""))
    return [w for w in words if w not in _STOPWORDS]


def _cosine(left: Counter, right: Counter) -> float:
    shared = left.keys() & right.keys()
    if not shared:
        return 0.0
    dot = sum(left[t] * right[t] for t in shared)
    norms = math.sqrt(sum(v * v for v in left.values())) * math.sqrt(sum(v * v for v in right.values()))
    return dot / norms


def _pooled(blocks: Sequence[Sequence[str]], start: int, stop: int) -> Counter:
    pooled: Counter = Counter()
    for block in blocks[max(0, start):min(len(blocks), stop)]:
        pooled.update(block)
    return pooled


def _cohesion_curve(blocks: Sequence[Sequence[str]], window: int) -> list[float]:
    """Similitud entre las ``window`` bloques antes y después de cada hueco."""
    return [_cosine(_pooled(blocks, gap + 1 - window, gap + 1), _pooled(blocks, gap + 1, gap + 1 + window))
            for gap in range(len(blocks) - 1)]


def _smooth(curve: Sequence[float], width: int) -> list[float]:
    """Media móvil centrada; los bordes se extienden con su último valor."""
    if width < 3 or len(curve) < width:
        return list(curve)
    reach = width // 2
    padded = [curve[0]] * reach + list(curve) + [curve[-1]] * reach
    return [sum(padded[i:i + 2 * reach + 1]) / (2 * reach + 1) for i in range(len(curve))]


def _climb(curve: Sequence[float], start: int, step: int) -> float:
    """Cima a la que se llega subiendo desde ``start`` mientras no baje la curva."""
    best, i = curve[start], start + step
    while 0 <= i < len(curve) and curve[i] >= best:
        best = curve[i]
        i += step
    return best


def _valley_depths(curve: Sequence[float]) -> list[float]:
    return [(_climb(curve, i, -1) - curve[i]) + (_climb(curve, i, +1) - curve[i]) for i in range(len(curve))]


def _threshold(depths: Sequence[float], policy: str) -> float:
    mean = sum(depths) / len(depths)
    spread = math.sqrt(sum((d - mean) ** 2 for d in depths) / len(depths))
    return {"average": mean, "low": mean - spread}.get(policy, mean + spread)


def _boundaries(depths: Sequence[float], policy: str) -> list[int]:
    """Huecos donde la profundidad supera el umbral y es un máximo local (no una meseta)."""
    if not depths:
        return []
    floor = _threshold(depths, policy)
    low = float("-inf")
    found = []
    for i, depth in enumerate(depths):
        before = depths[i - 1] if i else low
        after = depths[i + 1] if i + 1 < len(depths) else low
        if depth > floor and depth >= before and depth >= after and not (depth == before == after):
            found.append(i)
    return found


def segment_indices(
    block_tokens: Sequence[Sequence[str]],
    k: int = 7,
    smoothing_width: int = 3,
    cutoff_policy: str = "high",
) -> list[tuple[int, int]]:
    """Agrupa bloques en temas: lista de tramos ``(primero, último)`` inclusivos que
    cubren todos los bloques. ``k`` es el tamaño de la ventana y se reduce a n/5 en
    transcripciones cortas; ``cutoff_policy``: ``high`` | ``average`` | ``low``."""
    total = len(block_tokens)
    if total == 0:
        return []
    if total == 1:
        return [(0, 0)]
    window = min(max(1, k), max(1, total // 5))
    curve = _smooth(_cohesion_curve(block_tokens, window), smoothing_width)
    cuts = _boundaries(_valley_depths(curve), cutoff_policy)
    starts = [0] + [c + 1 for c in cuts]
    ends = cuts + [total - 1]
    return [(a, b) for a, b in zip(starts, ends) if a <= b]
