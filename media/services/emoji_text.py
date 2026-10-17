"""Emoji del gancho. El gancho es a la vez el título, la descripción, el texto
de la portada y el nombre de los archivos: una frase corta con UN emoji al
final («¡Le trajo un conejo vivo de regalo! 🐰»).

* El texto del video se quema SIN el emoji (libass lo dibuja gris o como un
  cuadro vacío); el emoji se superpone a color (`services/emoji_art.py`): encima
  de la caja del gancho en el video y bajo el texto en la portada. En el título,
  la descripción y los nombres de archivo va tal cual.
* `ensure` deja el gancho con exactamente un emoji al final: el que ya trae la
  IA o, si no, uno del tema (dinero 💰, fútbol ⚽…) o del tipo de gancho.
* Misma detección en `web/lib/hook.ts` (deben coincidir).
"""
from __future__ import annotations

import re

_E = ("[\U0001F000-\U0001FAFF☀-➿⭐⭕⬛⬜⬅-⬇⌚⌛⏩-⏳"
      "⏸-⏺⤴⤵〰〽㊗㊙©®‼⁉™ℹ↔-↙"
      "↩↪Ⓜ▪▫▶◀◻-◾]")  # ≈ \p{Extended_Pictographic} de JS
_MOD = "[️\U0001F3FB-\U0001F3FF]*"
EMOJI_RE = re.compile(f"{_E}{_MOD}(?:‍{_E}{_MOD})*")
HOOK_MAX_CHARS = 64

# Emoji de cierre según cómo abre el clip (si el texto no sugiere uno del tema).
HOOK_TYPE_EMOJI = {"question": "🤔", "statistic": "📊", "story": "👀", "contrast": "⚡", "statement": "🔥"}


def has_emoji(text: str) -> bool:
    return bool(EMOJI_RE.search(text or ""))


def emojis(text: str) -> list[str]:
    return EMOJI_RE.findall(text or "")


def strip_emoji(text: str) -> str:
    """El texto sin emojis y con los espacios normalizados."""
    return re.sub(r"\s+", " ", EMOJI_RE.sub(" ", text or "")).strip()


def split(text: str) -> tuple[str, str | None]:
    """(texto sin emojis, primer emoji o None)."""
    found = emojis(text)
    return strip_emoji(text), (found[0] if found else None)


def topic_emoji(*texts: str) -> str | None:
    """Emoji del tema de la primera palabra que tenga uno (dinero, fútbol…)."""
    from media.services import caption_fx
    for text in texts:
        for raw in strip_emoji(text).split():
            e = caption_fx.lookup_emoji(caption_fx.normalize_token(raw))
            if e:
                return e
    return None


def ensure(hook: str, hook_type: str | None = None, *context: str) -> str:
    """El gancho limpio con exactamente un emoji al final (≤ 64 caracteres).
    Sin texto útil devuelve ""."""
    from media.services.moments import sanitize_hook

    text, emoji = split(sanitize_hook(hook))
    if not text:
        return ""
    emoji = emoji or topic_emoji(text, *context) or HOOK_TYPE_EMOJI.get(hook_type or "", "🔥")
    room = HOOK_MAX_CHARS - len(emoji) - 1
    if len(text) > room:
        text = text[:room + 1].rsplit(" ", 1)[0] if " " in text[:room + 1] else text[:room]
    return f"{text} {emoji}"


__all__ = ["EMOJI_RE", "HOOK_MAX_CHARS", "HOOK_TYPE_EMOJI", "emojis", "ensure", "has_emoji", "split",
           "strip_emoji", "topic_emoji"]
