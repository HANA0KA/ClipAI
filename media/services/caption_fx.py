"""Énfasis y emojis de subtítulos estilo OpusClip (funciones puras).

* Palabras fuertes, números y porcentajes se pintan con el color de énfasis
  de la plantilla («10x», «90 %», «nunca», «secreto»…).
* Emojis de contexto junto a palabras clave, con límite de frecuencia: como
  máximo ``max_emojis`` por clip, al menos ``min_gap`` palabras entre uno y
  otro y el mismo emoji no se repite dentro de ``repeat_gap`` palabras.
* Determinista: el mismo clip siempre sale igual.

Idea tomada de SupoClip (`emoji_captions.py`); código y listas propios, en
español e inglés (SupoClip es AGPL-3.0: no se copia su código).
"""
from __future__ import annotations

import re
import unicodedata

# ── Normalización ────────────────────────────────────────────────────────────

_NON_WORD = re.compile(r"[^a-z0-9%ñ]+")


def normalize_token(text: str) -> str:
    """Minúsculas, sin tildes (salvo la ñ) ni signos: «¿Dinero?» → «dinero»."""
    out = []
    for ch in unicodedata.normalize("NFD", (text or "").lower()):
        if unicodedata.combining(ch):
            if ch == "̃" and out and out[-1] == "n":  # ñ = n + tilde combinada
                out[-1] = "ñ"
            continue
        out.append(ch)
    return _NON_WORD.sub("", "".join(out))


def _singular(token: str) -> list[str]:
    forms = []
    if len(token) > 4 and token.endswith("es"):
        forms.append(token[:-2])
    if len(token) > 3 and token.endswith("s"):
        forms.append(token[:-1])
    return forms


_NUMBER = re.compile(r"\d")

# ── Palabras fuertes ─────────────────────────────────────────────────────────

POWER_WORDS = frozenset({
    # español (sin tildes)
    "nunca", "jamas", "siempre", "nadie", "secreto", "secretos", "verdad", "mentira", "error",
    "errores", "gratis", "dinero", "millon", "millones", "millonario", "mejor", "peor", "increible",
    "importante", "clave", "rapido", "facil", "imposible", "enorme", "gigante", "cero", "unico",
    "prohibido", "peligro", "peligroso", "exito", "fracaso", "ganar", "perder", "brutal", "locura",
    "urgente", "rico", "ricos", "pobre", "deuda", "miedo", "maximo", "minimo",
    "doble", "triple", "mitad", "garantizado", "problema", "solucion", "truco",
    "trucos", "cambia", "cambio", "poder", "libertad", "odio", "amor", "muerte", "real", "nuevo",
    "primera", "primero", "ultimo", "ultima", "definitivo", "exacto", "literalmente",
    # inglés
    "never", "always", "nobody", "everyone", "secret", "secrets", "truth", "lie", "mistake",
    "mistakes", "free", "money", "million", "millions", "billion", "best", "worst", "insane",
    "crazy", "important", "key", "fast", "easy", "impossible", "huge", "zero", "only", "banned",
    "danger", "success", "fail", "failure", "win", "lose", "rich", "poor", "debt", "fear",
    "double", "half", "guaranteed", "problem", "solution", "hack", "hacks", "power",
    "freedom", "love", "hate", "death", "new", "first", "last", "ultimate", "exactly",
    "literally",
})

# ── Emojis por palabra clave (claves normalizadas) ───────────────────────────
# Solo emojis con presentación de emoji por defecto (sin selector de variación
# ni secuencias ZWJ): se dibujan como imagen en color (services/emoji_art.py).

EMOJI_KEYWORDS: dict[str, str] = {
    # dinero y negocio
    "dinero": "💰", "plata": "💰", "money": "💰", "cash": "💵", "dolares": "💵", "dolar": "💵",
    "dollars": "💵", "pesos": "💵", "euros": "💶", "rico": "🤑", "ricos": "🤑", "rich": "🤑",
    "millonario": "🤑", "millionaire": "🤑", "millones": "💰", "millions": "💰", "negocio": "💼",
    "negocios": "💼", "business": "💼", "empresa": "🏢", "company": "🏢", "trabajo": "💼",
    "work": "💼", "jefe": "💼", "boss": "💼", "invertir": "📈", "inversion": "📈", "invest": "📈",
    "investing": "📈", "bolsa": "📈", "acciones": "📈", "stocks": "📈", "crecer": "📈",
    "crecimiento": "📈", "growth": "📈", "ventas": "🛒", "vender": "🛒", "sell": "🛒",
    "comprar": "🛒", "buy": "🛒", "banco": "🏦", "bank": "🏦", "ahorrar": "🏦", "ahorro": "🏦",
    "save": "🏦", "savings": "🏦", "deuda": "💳", "debt": "💳", "tarjeta": "💳", "impuestos": "🧾",
    "taxes": "🧾", "precio": "💸", "price": "💸", "gratis": "🎁", "free": "🎁", "cripto": "🪙",
    "crypto": "🪙", "bitcoin": "🪙",
    # éxito y metas
    "exito": "🏆", "success": "🏆", "ganar": "🏆", "win": "🏆", "campeon": "🏆", "champion": "🏆",
    "meta": "🎯", "metas": "🎯", "goal": "🎯", "goals": "🎯", "objetivo": "🎯", "enfoque": "🎯",
    "focus": "🎯", "primero": "🥇", "first": "🥇", "rey": "👑", "king": "👑", "reina": "👑",
    "queen": "👑", "cohete": "🚀", "rocket": "🚀", "lanzar": "🚀", "launch": "🚀", "startup": "🚀",
    # mente y aprendizaje
    "idea": "💡", "ideas": "💡", "pensar": "🤔", "think": "🤔", "cerebro": "🧠", "brain": "🧠",
    "mente": "🧠", "mind": "🧠", "inteligente": "🧠", "smart": "🧠", "aprender": "📚",
    "learn": "📚", "estudiar": "📚", "study": "📚", "libro": "📖", "book": "📖", "libros": "📚",
    "books": "📚", "escuela": "🎓", "school": "🎓", "universidad": "🎓", "university": "🎓",
    "secreto": "🤫", "secret": "🤫", "verdad": "💯", "truth": "💯", "pregunta": "❓",
    "question": "❓", "ciencia": "🔬", "science": "🔬",
    # emociones
    "amor": "😍", "love": "😍", "corazon": "💖", "heart": "💖", "feliz": "😄", "happy": "😄",
    "triste": "😢", "sad": "😢", "miedo": "😱", "fear": "😱", "scary": "😱", "loco": "🤯",
    "locura": "🤯", "crazy": "🤯", "increible": "🤯", "insane": "🤯", "incredible": "🤯",
    "fuego": "🔥", "fire": "🔥", "risa": "😂", "reir": "😂", "chiste": "😂", "funny": "😂",
    "llorar": "😭", "cry": "😭", "enojo": "😡", "angry": "😡", "magia": "✨", "magic": "✨",
    "perfecto": "👌", "perfect": "👌",
    # fuerza y energía
    "poder": "💪", "power": "💪", "fuerte": "💪", "strong": "💪", "gimnasio": "💪", "gym": "💪",
    "musculo": "💪", "energia": "⚡", "energy": "⚡", "rapido": "⚡", "fast": "⚡",
    # tiempo
    "tiempo": "⏰", "time": "⏰", "hora": "⏰", "horas": "⏰", "hour": "⏰", "hours": "⏰",
    "calendario": "📅", "futuro": "🔮", "future": "🔮", "manana": "📅", "tomorrow": "📅",
    # lugares y cosas
    "mundo": "🌍", "world": "🌍", "planeta": "🌍", "casa": "🏠", "home": "🏠", "house": "🏠",
    "auto": "🚗", "coche": "🚗", "carro": "🚗", "car": "🚗", "viaje": "🛫", "viajar": "🛫",
    "travel": "🛫", "avion": "🛫", "comida": "🍔", "food": "🍔", "agua": "💧", "water": "💧",
    "cafe": "☕", "coffee": "☕", "dormir": "😴", "sleep": "😴", "salud": "🩺", "health": "🩺",
    "doctor": "🩺", "familia": "👪", "family": "👪", "amigos": "🤝", "friends": "🤝",
    "equipo": "🤝", "team": "🤝", "gente": "👥", "people": "👥", "telefono": "📱", "celular": "📱",
    "phone": "📱", "internet": "🌐", "video": "🎬", "videos": "🎬", "pelicula": "🎬", "movie": "🎬",
    "musica": "🎵", "music": "🎵", "juego": "🎮", "game": "🎮", "robot": "🤖", "computadora": "💻",
    "computer": "💻", "codigo": "💻", "code": "💻", "programar": "💻", "perro": "🐶", "dog": "🐶",
    "gato": "🐱", "cat": "🐱", "bebe": "👶", "baby": "👶", "estrella": "⭐", "star": "⭐",
    # alertas y resultados
    "peligro": "🚨", "danger": "🚨", "alerta": "🚨", "warning": "🚨", "error": "❌",
    "mistake": "❌", "correcto": "✅", "solucion": "✅", "solution": "✅", "ojo": "👀",
    "mira": "👀", "look": "👀", "atencion": "👀",
    # relaciones y conversación
    "novia": "💑", "novio": "💑", "pareja": "💑", "boda": "💍", "amigo": "🤝", "amiga": "🤝",
    "madre": "👩", "mama": "👩", "padre": "👨", "papa": "👨", "hijo": "👶", "hija": "👶",
    "nino": "🧒", "ninos": "🧒", "sonrisa": "😊", "smile": "😊", "esfuerzo": "💪", "effort": "💪",
    "problema": "🧩", "problemon": "🧩", "problem": "🧩", "historia": "📖", "story": "📖",
    "importante": "📌", "important": "📌", "iceberg": "🧊", "final": "🏁", "serie": "📺",
    "gracias": "🙏", "thanks": "🙏", "estilo": "😎", "style": "😎", "noche": "🌙", "night": "🌙",
    "sol": "☀", "playa": "🏖", "fiesta": "🎉", "party": "🎉", "regalo": "🎁", "gift": "🎁",
}

# Raíces verbales (conjugaciones): «escuchar», «escuchen», «escuchada»…
EMOJI_PREFIXES: tuple[tuple[str, str], ...] = (
    ("escuch", "👂"), ("sonri", "😊"), ("sonre", "😊"), ("habl", "💬"), ("llor", "😭"),
    ("piens", "🤔"), ("pens", "🤔"), ("aprend", "📚"), ("estudi", "📚"), ("trabaj", "💼"),
    ("invert", "📈"), ("invier", "📈"), ("ahorr", "🏦"), ("enamor", "😍"), ("viaj", "🛫"),
    ("entren", "💪"), ("grit", "😱"), ("celebr", "🎉"), ("listen", "👂"), ("talk", "💬"),
    ("laugh", "😂"),
)


def lookup_emoji(token: str, table: dict[str, str] | None = None) -> str | None:
    table = EMOJI_KEYWORDS if table is None else table
    if not token:
        return None
    if token in table:
        return table[token]
    for form in _singular(token):
        if form in table:
            return table[form]
    if table is EMOJI_KEYWORDS and len(token) >= 5:
        for prefix, char in EMOJI_PREFIXES:
            if token.startswith(prefix):
                return char
    return None


def is_emphasis(token: str) -> bool:
    return bool(token) and (token in POWER_WORDS or bool(_NUMBER.search(token)))


def annotate(words: list[dict], *, emoji: bool = True, emphasis: bool = True,
             max_emojis: int = 8, min_gap: int = 3, repeat_gap: int = 8) -> tuple[dict[int, str], set[int]]:
    """(emoji por índice de palabra, índices con énfasis) sobre ``words``
    (``{"w": ...}``). Las palabras con ``hl`` (marcadas a mano) siempre
    llevan énfasis."""
    emojis: dict[int, str] = {}
    emph: set[int] = set()
    last = -(min_gap + 1)
    recent: dict[str, int] = {}
    for idx, word in enumerate(words):
        if word.get("hl"):
            emph.add(idx)
        token = normalize_token(str(word.get("w", "")))
        if not token:
            continue
        if emphasis and is_emphasis(token):
            emph.add(idx)
        if not emoji or len(emojis) >= max_emojis:
            continue
        char = lookup_emoji(token)
        if not char or idx - last < min_gap or idx - recent.get(char, -(repeat_gap + 1)) < repeat_gap:
            continue
        emojis[idx] = char
        last = idx
        recent[char] = idx
    return emojis, emph


def emoji_budget(duration: float | None) -> int:
    """Un emoji cada ~8 s como máximo (8 en un clip de 60–70 s)."""
    if not duration or duration <= 0:
        return 8
    return max(1, min(10, int(duration // 8)))


__all__ = ["normalize_token", "POWER_WORDS", "EMOJI_KEYWORDS", "lookup_emoji", "is_emphasis",
           "annotate", "emoji_budget"]
