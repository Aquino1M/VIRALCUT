from __future__ import annotations

import shutil
import subprocess

import pytest

from app.services import layouts


TRACKING_TWO = {
    "backend": "test",
    "tracks": [
        {"id":"face_1","samples":[{"t":0.0,"center":[0.25,0.35],"box":[0.15,0.15,0.2,0.4],"activity":0.2},{"t":1.0,"center":[0.28,0.35],"box":[0.18,0.15,0.2,0.4],"activity":0.4}]},
        {"id":"face_2","samples":[{"t":0.0,"center":[0.75,0.35],"box":[0.65,0.15,0.2,0.4],"activity":0.7},{"t":1.0,"center":[0.72,0.35],"box":[0.62,0.15,0.2,0.4],"activity":0.8}]},
    ]
}


def test_registry_contains_v21_layouts():
    ids = {p["id"] for p in layouts.list_layout_presets()}
    assert {"podcast-dynamic", "choquei-movimento", "header-news", "story-documentary"} <= ids


def test_auto_uses_face_tracking_to_choose_layout():
    assert layouts.resolve_layout_id("auto", tracking={"tracks": []}) == "single"
    assert layouts.resolve_layout_id("auto", tracking={"tracks": [TRACKING_TWO["tracks"][0]]}) == "single"
    assert layouts.resolve_layout_id("auto", tracking=TRACKING_TWO) == "podcast-dynamic"


def test_split_uses_distinct_face_tracks_in_filtergraph():
    graph = layouts.build_layout_filter("split", tracking=TRACKING_TWO)
    assert "0.25" in graph or "0.28" in graph
    assert "0.75" in graph or "0.72" in graph
    assert graph.count("crop=1080:960") == 2


def test_single_builds_time_aware_crop_expression_from_track_samples():
    graph = layouts.build_layout_filter("single", tracking=TRACKING_TWO)
    assert "lt(t" in graph
    assert "(t-" in graph  # linear interpolation between tracking samples
    assert "crop=1080:1920" in graph


def test_more_panels_than_faces_use_context_variants_not_identical_panels():
    graph = layouts.build_layout_filter("quad", tracking={"tracks": [TRACKING_TWO["tracks"][0]]})
    # Four panel chains should not be byte-for-byte identical crops.
    parts = [x for x in graph.split(";") if "crop=540:960" in x]
    assert len(parts) == 4
    assert len(set(parts)) >= 3


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
@pytest.mark.parametrize("layout_id", ["single","split","podcast-dynamic","choquei-movimento","header-news","story-documentary"])
def test_v21_face_aware_filtergraphs_are_accepted_by_ffmpeg(layout_id):
    graph = layouts.build_layout_filter(layout_id, tracking=TRACKING_TWO, config={"backgroundBlur": 7})
    proc = subprocess.run([
        "ffmpeg","-hide_banner","-loglevel","error","-y",
        "-f","lavfi","-i","testsrc2=s=1920x1080:r=10:d=0.2",
        "-filter_complex",graph,"-map","[vout]","-frames:v","1","-f","null","-",
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.returncode == 0, proc.stderr


def test_render_pipeline_forwards_tracking_to_layout_engine(monkeypatch, tmp_path):
    from app.services import render
    seen = {}
    def fake_graph(layout_id, face_centers=None, config=None, *, tracking=None, output_size=(1080, 1920), clip_duration=None):
        seen["tracking"] = tracking
        return "[0:v]null[vout]"
    monkeypatch.setattr(render.layouts, "build_layout_filter", fake_graph)
    def fake_encoded(prefix, suffix, **kwargs):
        Path(suffix[-1]).write_bytes(b"video")
        return "libx264"
    from pathlib import Path
    monkeypatch.setattr(render, "_run_encoded", fake_encoded)
    source = tmp_path / "src.mp4"; source.write_bytes(b"x")
    out = tmp_path / "out.mp4"
    tracking = {"tracks":[{"id":"face_1","samples":[{"t":0,"center":[.2,.3]}]}]}
    render.render_edited_clip(source, out, 0, 1, {"layout_preset_id":"single","tracks":{"captions":{"visible":False}}}, tracking=tracking)
    assert seen["tracking"] is tracking
