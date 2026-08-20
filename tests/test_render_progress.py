from __future__ import annotations
from pathlib import Path
import shutil, subprocess
import pytest
from app.services import render


def test_render_edited_clip_reports_staged_progress(tmp_path: Path, monkeypatch):
    if not shutil.which('ffmpeg'):
        pytest.skip('ffmpeg not installed')
    src=tmp_path/'src.mp4'
    subprocess.run(['ffmpeg','-y','-f','lavfi','-i','color=c=black:s=640x360:r=24','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','1','-c:v','libx264','-preset','ultrafast','-c:a','aac',str(src)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
    monkeypatch.setattr(render,'select_video_encoder',lambda:'libx264')
    seen=[]
    render.render_edited_clip(src,tmp_path/'out.mp4',0,1,{'layout_preset_id':'single','tracks':{'captions':{'visible':False}}},progress_callback=lambda pct,msg: seen.append((pct,msg)))
    assert seen[0][0] <= 15
    assert any(40 <= p <= 70 for p,_ in seen)
    assert seen[-1][0] >= 95
