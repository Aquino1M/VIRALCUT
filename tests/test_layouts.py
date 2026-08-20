from __future__ import annotations

import shutil
import subprocess

import pytest

from app.services import layouts


def test_layout_registry_has_requested_presets():
    ids = {p["id"] for p in layouts.list_layout_presets()}
    assert {"auto", "single", "center", "split", "split-vertical", "tri-split", "tri-split-top", "quad", "six-split", "react", "brainrot", "talking-broll", "podcast-top-bottom"} <= ids


def test_auto_resolves_safely_without_speaker_metadata():
    assert layouts.resolve_layout_id("auto", speaker_count=0) == "single"
    assert layouts.resolve_layout_id("auto", speaker_count=2) == "split"
    assert layouts.resolve_layout_id("auto", speaker_count=3) == "tri-split"


def test_layout_filtergraphs_end_in_vout():
    for preset in layouts.list_layout_presets():
        graph = layouts.build_layout_filter(preset["id"], face_centers=[0.3, 0.7, 0.5])
        assert "[vout]" in graph
        assert "1080" in graph
        assert "1920" in graph


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
@pytest.mark.parametrize("layout_id", ["single", "center", "split", "split-vertical", "tri-split", "quad", "six-split", "react", "brainrot", "podcast-top-bottom"])
def test_requested_layout_filtergraph_is_accepted_by_ffmpeg(layout_id):
    graph = layouts.build_layout_filter(layout_id, face_centers=[0.25, 0.75, 0.5])
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=1920x1080:r=1:d=0.05",
            "-filter_complex", graph,
            "-map", "[vout]", "-frames:v", "1", "-f", "null", "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_center_layout_respects_configured_blur_amount():
    graph = layouts.build_layout_filter('center', config={'backgroundBlur': 7})
    assert 'gblur=sigma=7' in graph
