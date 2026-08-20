from __future__ import annotations

from pathlib import Path

from app.services import overlays, preview, render


def test_preview_settings_hash_is_stable_and_sensitive():
    a = {"caption_preset_id": "green-fresh", "caption_config": {"fontSize": 75}}
    b = {"caption_config": {"fontSize": 75}, "caption_preset_id": "green-fresh"}
    c = {"caption_preset_id": "green-fresh", "caption_config": {"fontSize": 76}}
    assert preview.settings_hash(a) == preview.settings_hash(b)
    assert preview.settings_hash(a) != preview.settings_hash(c)


def test_static_overlay_compositor_creates_transparent_canvas(tmp_path: Path):
    out = tmp_path / "overlay.png"
    overlays.compose_static_overlay([
        {"type": "cta", "text": "SIGA PARA MAIS", "x": 40, "y": 120, "width": 1000, "height": 140, "opacity": 0.8, "background": "#6D28D9"},
        {"type": "text", "text": "TÍTULO", "x": 80, "y": 300, "width": 920, "height": 120, "opacity": 1.0},
    ], out)
    assert out.exists()
    from PIL import Image
    im = Image.open(out)
    assert im.size == (1080, 1920)
    assert im.mode == "RGBA"


def test_render_plan_uses_editor_layout_caption_and_preview_scale():
    plan = render.build_render_plan({
        "layout_preset_id": "split",
        "caption_preset_id": "green-fresh",
        "caption_config": {"fontSize": 80},
        "overlays": [],
    }, preview=True)
    assert plan["layout_id"] == "split"
    assert plan["caption_config"]["fontSize"] == 80
    assert plan["output_size"] == (270, 480)


def test_ffmpeg_error_summary_does_not_dump_banner():
    error = "ffmpeg version abc\nconfiguration: huge\nInput #0\n[AVFilterGraph] No such filter: x\nError opening output files"
    summary = render.summarize_ffmpeg_error(error)
    assert "ffmpeg version" not in summary.lower()
    assert "No such filter" in summary
