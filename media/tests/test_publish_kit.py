"""Gancho único con emoji (título + descripción + portada), estilo de
subtítulos por proyecto, nombres de descarga emparejados (video ↔ portada) y
prioridad baja del render."""
import subprocess

import pytest

from media.config import reset_settings
from media.services import ass_builder, cover, db, emoji_text, subtitle_style
from media.services.ffmpeg import lower_priority
from media.services.moments import heuristic_kit, hook_plain, sanitize_hook


# ── Gancho único con emoji (título + descripción + portada) ──────────────────

def test_ensure_keeps_ai_emoji_at_the_end_and_counts_it_apart():
    assert emoji_text.ensure("¡Le trajo un conejo vivo de regalo! 🐰") == "¡Le trajo un conejo vivo de regalo! 🐰"
    assert emoji_text.ensure("🐰 ¡Le trajo un conejo vivo de regalo!") == "¡Le trajo un conejo vivo de regalo! 🐰"
    assert emoji_text.ensure('"Rechazó 1 millón 😱💸" #Shorts') == "Rechazó 1 millón 😱"  # uno solo, sin hashtags ni comillas


def test_ensure_adds_topic_or_type_emoji_when_missing():
    assert emoji_text.ensure("Así perdió todo su dinero", "story").endswith(" 💰")
    assert emoji_text.ensure("¿Qué harías en su lugar?", "question").endswith(" 🤔")
    assert emoji_text.ensure("Sin tema claro aquí", None).endswith(" 🔥") and emoji_text.ensure("  ") == ""
    assert emoji_text.ensure("Sin tema claro aquí", "statement", "el dinero").endswith("💰")


def test_ensure_respects_max_length_with_emoji():
    out = emoji_text.ensure("palabra " * 20 + "fin 🔥")
    assert len(out) <= emoji_text.HOOK_MAX_CHARS and out.endswith(" 🔥")


def test_sanitize_hook_keeps_one_emoji_and_hook_plain_drops_it():
    assert sanitize_hook("«¡Le trajo un conejo vivo!» 🐰🔥 #viral") == "¡Le trajo un conejo vivo! 🐰"
    assert hook_plain("¡Le trajo un conejo vivo! 🐰") == "¡Le trajo un conejo vivo!"
    assert sanitize_hook("🐰") == "" and hook_plain("🐰") == ""
    ten = "uno dos tres cuatro cinco seis siete ocho nueve diez once 🐰"
    assert sanitize_hook(ten) == "uno dos tres cuatro cinco seis siete ocho nueve diez 🐰"  # 10 palabras + emoji


def test_video_hook_is_burned_without_emoji():
    tpl = ass_builder.load_template("bold-yellow")
    events = "\n".join(ass_builder.hook_events("¡Le trajo un conejo vivo! 🐰", tpl=tpl))
    assert "CONEJO" in events and "🐰" not in events
    same = ass_builder.hook_display_seconds("¡Le trajo un conejo vivo!", tpl)
    assert ass_builder.hook_display_seconds("¡Le trajo un conejo vivo! 🐰", tpl) == same


def test_heuristic_kit_hook_is_title_and_description():
    kit = heuristic_kit([{"text": "¿Por qué ahorrar 10 euros al mes cambia tu vida?"},
                         {"text": "El ahorro compuesto es la clave del dinero."}])
    assert kit["title"] == kit["hook"] and emoji_text.has_emoji(kit["hook"]) and kit["description"] == ""
    assert "#" not in kit["hook"] and len(kit["hook"]) <= emoji_text.HOOK_MAX_CHARS


def test_cover_layout_reserves_room_for_the_emoji_below_the_text():
    tpl = ass_builder.load_template("bold-yellow")
    plain = cover.layout("¡Le trajo un conejo vivo de regalo! 🐰", tpl=tpl, width=1080, height=1920)
    withe = cover.layout("¡Le trajo un conejo vivo de regalo! 🐰", tpl=tpl, width=1080, height=1920, emoji=True)
    assert plain["emoji"] is None and "🐰" not in withe["ass"] and "CONEJO" in withe["ass"]
    x, y, size = withe["emoji"]
    assert x == 540 and size > 60 and 1920 * 0.16 < y < 1920 * 0.84  # dentro de la zona segura
    assert withe["band"][1] > plain["band"][1]                       # la franja oscura incluye al emoji
    for pos in ("top", "center", "bottom"):
        made = cover.layout("Nadie te escucha", tpl=tpl, width=1080, height=1920, position=pos, emoji=True)
        assert 1920 * 0.16 <= made["emoji"][1] + made["emoji"][2] / 2 <= 1920 * 0.84 + 1


def test_cover_paste_emoji_draws_color_over_the_jpg(tmp_path):
    from PIL import Image
    from media.services import emoji_art
    if not emoji_art.available():
        pytest.skip("sin fuente de emojis a color")
    jpg = tmp_path / "c.jpg"
    Image.new("RGB", (400, 600), (20, 20, 20)).save(jpg)
    assert cover.paste_emoji(jpg, "🐰", (200, 300, 120)) is True
    px = Image.open(jpg).convert("RGB").crop((140, 240, 260, 360))
    assert len({p for p in px.getdata() if max(p) - min(p) > 40}) > 5  # hay color donde iba el emoji
    assert cover.paste_emoji(jpg, "🐰", (200, 300, 4)) is False       # tamaño inválido: la portada queda igual


# ── Estilo de subtítulos por proyecto ────────────────────────────────────────

ALL = ["bold-yellow", "clean-box", "hormozi", "minimal", "mrbeast", "neon-anton", "podcast", "tiktok"]


def test_pick_avoids_recent_templates():
    recent = ["hormozi", "tiktok", "mrbeast", "bold-yellow", "clean-box", "minimal", "neon-anton"]
    assert subtitle_style.pick(ALL, recent, "p1") == "podcast"  # el único sin usar
    # Todos usados: el que lleva más tiempo sin salir.
    assert subtitle_style.pick(ALL, recent + ["podcast"], "p1") == "podcast"
    assert subtitle_style.pick(ALL, ["podcast", *recent], "p1") == "neon-anton"


def test_pick_varies_between_projects_and_respects_allowed():
    picks = {subtitle_style.pick(ALL, [], f"proyecto-{i}") for i in range(40)}
    assert len(picks) >= 4
    assert subtitle_style.pick(ALL, ["tiktok"], "x", allowed=["tiktok", "hormozi"]) == "hormozi"
    assert subtitle_style.pick(ALL, [], "x", allowed=["nope"]) in ALL  # lista inválida: todas
    assert subtitle_style.pick([], [], "x") is None


def _project(pid, template=None):
    with db.connect() as conn:
        conn.execute('INSERT INTO "Project" (id, sourceType, folder, templateId, createdAt, updatedAt) '
                     'VALUES (?,?,?,?,?,?)', [pid, "youtube", "x", template, db.now_iso(), db.now_iso()])
    return db.get_project(pid)


def test_resolve_saves_choice_and_keeps_it(temp_db):
    _project("a" * 20, "hormozi")
    p = _project("b" * 20)
    chosen = subtitle_style.resolve(p)
    assert chosen != "hormozi" and db.get_project(p["id"])["templateId"] == chosen
    assert subtitle_style.resolve(db.get_project(p["id"])) == chosen  # re-análisis: el mismo
    q = _project("c" * 20, "tiktok")
    assert subtitle_style.resolve(q) == "tiktok"  # el elegido por el usuario manda


def test_resolve_uses_allowed_list(temp_db, monkeypatch):
    monkeypatch.setenv("SUBTITLE_TEMPLATES_AUTO", "minimal, podcast")
    reset_settings()
    assert subtitle_style.resolve(_project("d" * 20)) in ("minimal", "podcast")


# ── Descargas emparejadas ────────────────────────────────────────────────────

def test_cover_filename_matches_video_name():
    assert cover.filename({"hook": "x"}, "03 - Rechazó un millón") == "03 - Rechazó un millón - portada.jpg"
    assert cover.filename({"hook": "¿Por qué?"}) == "portada-por-qué.jpg"


def test_download_base_keeps_emoji_and_drops_forbidden_chars():
    from media.main import _download_base
    assert _download_base("03 - ¡Le trajo un conejo vivo! 🐰") == "03 - ¡Le trajo un conejo vivo! 🐰"
    assert _download_base("../../etc/passwd") == "etcpasswd"  # sin separadores no hay ruta que recorrer
    assert _download_base('a/b\\c:d*e?"<>|f') == "abcdef"
    assert _download_base("   ") is None and _download_base(None) is None


# ── Prioridad del render ─────────────────────────────────────────────────────

def test_lower_priority_nices_child(monkeypatch):
    import os
    monkeypatch.setenv("RENDER_NICE", "7")
    reset_settings()
    proc = subprocess.Popen(["sleep", "2"])
    try:
        lower_priority(proc)
        assert os.getpriority(os.PRIO_PROCESS, proc.pid) >= 7
    finally:
        proc.kill()
        proc.wait()
        reset_settings()
    lower_priority(object())  # sin pid (dobles de prueba): no falla


# ── Emoji del gancho en el video ─────────────────────────────────────────────

def test_hook_emoji_sits_centered_above_the_hook_box():
    tpl = ass_builder.load_template("bold-yellow")
    item = ass_builder.plan_hook_emoji("¡Le trajo un conejo vivo! 🐰", tpl=tpl, seconds=4.0, clip_duration=60)
    assert item["emoji"] == "🐰" and item["start"] == 0.0 and item["end"] == 4.0
    box_top = tpl["hook"].get("margin_v", 260) - ass_builder.HOOK_BOX_PAD
    assert abs(item["x"] + item["size"] / 2 - 540) <= 1 and item["y"] + item["size"] < box_top  # encima, sin tapar el texto
    assert ass_builder.plan_hook_emoji("Sin emoji aquí", tpl=tpl) is None
    assert ass_builder.plan_hook_emoji("🐰", tpl=tpl) is None
    short = ass_builder.plan_hook_emoji("Hola 🐰", tpl=tpl, seconds=9, clip_duration=2.5)
    assert short["end"] == 2.5                                       # nunca más que el clip
    sq = ass_builder.plan_hook_emoji("Hola 🐰", tpl=tpl, width=1080, height=1080)
    assert sq["size"] == item["size"] and sq["y"] < item["y"]        # cuadrado: margen vertical menor


def test_final_command_overlays_hook_emoji_after_smartcut(temp_db, tmp_path):
    from media.tasks import render
    png = tmp_path / "e.png"
    png.write_bytes(b"x")
    item = {"emoji": "🐰", "start": 0.0, "end": 3.0, "x": 500, "y": 100, "size": 90, "path": str(png)}
    for keep in (None, [(0.0, 4.0), (6.0, 10.0)]):
        cmd = render.final_command("r.mp4", "o.mp4", fonts_rel="f", ass_main="clip.ass",
                                   ass_hook="hook.ass" if keep else None, keep=keep, zoom=None, duration=10.0,
                                   hook_emoji=item)
        graph = cmd[cmd.index("-filter_complex") + 1]
        assert str(png) in cmd and "overlay=x=500" in graph and graph.rstrip().endswith("[a]")
        if keep:  # primero el corte y el gancho, luego el emoji, al final fps/format
            assert graph.index("hook.ass") < graph.index("overlay=x=500") < graph.index("fps=")
    plain = render.final_command("r.mp4", "o.mp4", fonts_rel="f", ass_main="clip.ass", ass_hook=None, keep=None,
                                zoom=None, duration=10.0)
    assert "-loop" not in plain  # sin emoji, el comando queda como antes


# ── Texto para publicar: el creador en título, descripción y hashtags ─────────
from media.services import publish_text as pt  # noqa: E402


def test_creator_name_from_info_json():
    assert pt.creator_name({"channel": "Luisito Comunica"}) == "Luisito Comunica"
    assert pt.creator_name({"uploader": "@westcol"}) == "westcol"
    assert pt.creator_name({"channel": "Artista - Topic", "uploader": "x"}) == "Artista"
    assert pt.creator_name({"channel": "***"}) is None and pt.creator_name({}) is None and pt.creator_name(None) is None


def test_post_title_adds_the_creator_only_when_missing():
    assert pt.post_title("¡Le trajo un conejo vivo de regalo! 🐰", "Luisito Comunica") == \
        "Luisito Comunica: ¡Le trajo un conejo vivo de regalo! 🐰"
    assert pt.post_title("Luisito Comunica no puede creer esto 😱", "Luisito Comunica") == "Luisito Comunica no puede creer esto 😱"
    assert pt.post_title("Gancho sin creador 🔥", None) == "Gancho sin creador 🔥"
    long_hook = "a" * 64
    assert len(pt.post_title(long_hook, "N" * 60)) <= pt.TITLE_MAX
    assert pt.post_title(long_hook, "N" * 60) == long_hook  # no cabe con el creador: queda el gancho


def test_post_description_names_the_creator_in_the_first_line():
    d = pt.post_description("¡Gancho! 🔥", "Westcol", "El video largo", "https://kick.com/westcol/videos/x")
    assert d.splitlines() == ["Clip de Westcol: ¡Gancho! 🔥", "Del video «El video largo».",
                              "Video completo: https://kick.com/westcol/videos/x"]
    assert pt.post_description("¡Gancho! 🔥", None, None, None) == "¡Gancho! 🔥"
    assert pt.post_description("Westcol lo dijo 🔥", "Westcol", None, "ftp://x").splitlines() == ["Westcol lo dijo 🔥"]


def test_post_hashtags_puts_creator_and_format_first_without_dropping_yours():
    got = pt.post_hashtags("#YoutubersEspañoles #luisitocomunica #Streamers", "Luisito Comunica", "#Clips")
    assert got == "#LuisitoComunica #Clips #YoutubersEspañoles #Streamers"
    assert pt.post_hashtags("#a #b", None, "#Clips") == "#Clips #a #b"
    assert pt.post_hashtags("#a, #b", "X Y", "") == "#XY #a #b"
    assert pt.post_hashtags(pt.post_hashtags("#a", "Westcol", "#Clips"), "Westcol", "#Clips") == "#Westcol #Clips #a"  # idempotente


def test_creator_for_reads_the_info_json_once(tmp_path):
    (tmp_path / "source.info.json").write_text('{"channel": "Luisito Comunica"}', "utf-8")
    assert pt.creator_for(tmp_path) == "Luisito Comunica"
    assert pt.creator_for(tmp_path / "nada") is None
