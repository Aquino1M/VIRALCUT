from __future__ import annotations

import hashlib
import json
import math
import subprocess
from array import array
from pathlib import Path

from app.config import FFMPEG_BIN, PREVIEW_DIR

WAVEFORM_VERSION = 1


def waveform_cache_path(clip_id: str, source: Path, start: float, end: float, samples: int = 320) -> Path:
    stat = source.stat()
    token = f"{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{float(start):.3f}|{float(end):.3f}|{int(samples)}|v{WAVEFORM_VERSION}"
    digest = hashlib.sha256(token.encode('utf-8')).hexdigest()[:18]
    folder = PREVIEW_DIR / 'waveforms'
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{clip_id}_{digest}.json"


def _normalize_pcm(raw: bytes, samples: int) -> list[float]:
    samples = max(1, min(2048, int(samples or 320)))
    pcm = array('h')
    usable = len(raw) - (len(raw) % 2)
    if usable:
        pcm.frombytes(raw[:usable])
    if not pcm:
        return [0.0] * samples
    chunk = max(1, math.ceil(len(pcm) / samples))
    peaks: list[float] = []
    for i in range(samples):
        part = pcm[i * chunk:(i + 1) * chunk]
        peak = max((abs(int(v)) for v in part), default=0)
        peaks.append(float(peak))
    top = max(peaks) or 1.0
    return [round(min(1.0, p / top), 4) for p in peaks]


def ensure_waveform(clip_id: str, source: Path, start: float, end: float, *, samples: int = 320) -> Path:
    if not source.exists():
        raise FileNotFoundError(source)
    out = waveform_cache_path(clip_id, source, start, end, samples)
    if out.exists() and out.stat().st_size > 20:
        return out
    duration = max(0.05, float(end) - float(start))
    cmd = [
        FFMPEG_BIN, '-v', 'error', '-ss', f'{max(0.0, float(start)):.3f}', '-t', f'{duration:.3f}', '-i', str(source),
        '-vn', '-ac', '1', '-ar', '8000', '-f', 's16le', 'pipe:1',
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        error = (proc.stderr or b'').decode('utf-8', errors='ignore').strip()
        raise RuntimeError(error or 'Falha ao gerar waveform')
    payload = {'version': WAVEFORM_VERSION, 'duration': round(duration, 3), 'samples': _normalize_pcm(proc.stdout or b'', samples)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    return out
