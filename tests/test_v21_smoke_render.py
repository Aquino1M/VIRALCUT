from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.services import layouts, render

TRACKING = {
    "backend": "test",
    "tracks": [
        {"id":"face_1","samples":[{"t":0,"center":[.25,.38],"box":[.15,.15,.2,.4],"activity":.2},{"t":1,"center":[.30,.38],"box":[.2,.15,.2,.4],"activity":.3}],"mean_activity":.25},
        {"id":"face_2","samples":[{"t":0,"center":[.75,.38],"box":[.65,.15,.2,.4],"activity":.7},{"t":1,"center":[.70,.38],"box":[.6,.15,.2,.4],"activity":.8}],"mean_activity":.75},
    ],
}


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_every_registered_layout_filtergraph_parses_in_ffmpeg():
    for preset in layouts.list_layout_presets():
        graph = layouts.build_layout_filter(preset["id"], tracking=TRACKING, config={"backgroundBlur": 8})
        proc = subprocess.run([
            "ffmpeg","-hide_banner","-loglevel","error","-y",
            "-f","lavfi","-i","testsrc2=s=1920x1080:r=10:d=0.12",
            "-filter_complex",graph,"-map","[vout]","-frames:v","1","-f","null","-",
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert proc.returncode == 0, f"{preset['id']}: {proc.stderr}"


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg/ffprobe not installed")
def test_real_split_render_outputs_vertical_video(tmp_path: Path):
    source = tmp_path / "source.mp4"
    subprocess.run([
        "ffmpeg","-hide_banner","-loglevel","error","-y",
        "-f","lavfi","-i","testsrc2=s=1280x720:r=15:d=1.2",
        "-f","lavfi","-i","sine=frequency=440:duration=1.2",
        "-shortest","-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac",str(source)
    ], check=True)
    out = tmp_path / "split.mp4"
    state = {"layout_preset_id":"split","caption_preset_id":"green-fresh","tracks":{"captions":{"visible":False}},"overlays":[]}
    result = render.render_edited_clip(source, out, 0, 1, state, tracking=TRACKING)
    assert out.exists() and out.stat().st_size > 1000
    info = render.probe_video(out)
    assert (info["width"], info["height"]) == (1080, 1920)
    assert result["resolution"] == "1080x1920"
