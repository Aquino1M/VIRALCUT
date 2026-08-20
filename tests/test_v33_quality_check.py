from pathlib import Path
from app.services.quality_check import inspect

def test_quality_check_rejects_missing_original(tmp_path: Path):
    result=inspect(tmp_path/'missing.mp4',{}, {'composition':{'duration':2},'tracks':[]})
    assert result['errors']

def test_quality_check_warns_overlay_outside_frame(tmp_path: Path):
    src=tmp_path/'x.mp4'; src.write_bytes(b'x')
    result=inspect(src,{'overlays':[{'id':'cta','x':2000,'y':0,'width':100,'height':100}]},{'composition':{'duration':2},'tracks':[]})
    assert result['warnings']
