from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from app.config import FFMPEG_BIN, FFPROBE_BIN


def detect_silence(path: str | Path, *, noise_db: float = -36.0, min_duration: float = 0.45) -> list[dict[str, float]]:
    p=Path(path)
    cmd=[FFMPEG_BIN,'-hide_banner','-i',str(p),'-af',f'silencedetect=noise={noise_db}dB:d={min_duration}','-f','null','-']
    proc=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    text=proc.stderr or ''
    starts=[float(x) for x in re.findall(r'silence_start:\s*([0-9.]+)',text)]
    ends=[(float(a),float(b)) for a,b in re.findall(r'silence_end:\s*([0-9.]+)\s*\|\s*silence_duration:\s*([0-9.]+)',text)]
    out=[]
    for i,(end,duration) in enumerate(ends):
        start=starts[i] if i<len(starts) else max(0.0,end-duration)
        out.append({'start':round(start,3),'end':round(end,3),'duration':round(duration,3)})
    return out


def detect_scenes(path: str | Path, *, threshold: float = 0.32, limit: int = 400) -> list[dict[str, float]]:
    p=Path(path)
    threshold=max(.05,min(.95,float(threshold)))
    cmd=[FFMPEG_BIN,'-hide_banner','-i',str(p),'-vf',f"select='gt(scene,{threshold})',showinfo",'-an','-f','null','-']
    proc=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    times=[]
    for m in re.finditer(r'pts_time:([0-9.]+)',proc.stderr or ''):
        times.append(float(m.group(1)))
        if len(times)>=limit: break
    return [{'time':round(t,3),'confidence_threshold':threshold} for t in times]


def loudness(path: str | Path) -> dict[str, Any]:
    p=Path(path)
    cmd=[FFMPEG_BIN,'-hide_banner','-i',str(p),'-af','loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json','-f','null','-']
    proc=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    text=proc.stderr or ''
    blocks=re.findall(r'\{\s*"input_i".*?\}',text,re.S)
    if not blocks:
        return {'ok':False,'error':'loudnorm não retornou medição'}
    try:
        data=json.loads(blocks[-1])
    except Exception as exc:
        return {'ok':False,'error':str(exc)}
    def num(k):
        try:return float(data.get(k))
        except Exception:return None
    return {'ok':True,'input_i':num('input_i'),'input_tp':num('input_tp'),'input_lra':num('input_lra'),'input_thresh':num('input_thresh'),'target_i':-14.0,'target_tp':-1.5}


def inspect_media(path: str | Path, *, include_scenes: bool = True, include_silence: bool = True) -> dict[str, Any]:
    p=Path(path)
    result={'path':str(p),'silences':[],'scenes':[],'loudness':{}}
    if include_silence:
        result['silences']=detect_silence(p)
    if include_scenes:
        result['scenes']=detect_scenes(p)
    result['loudness']=loudness(p)
    return result
