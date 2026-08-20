from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from app.config import FFPROBE_BIN

PLATFORM_SPECS = {
    "youtube-shorts": {"ratios": {"9:16", "1:1"}, "max_seconds": 180},
    "tiktok": {"ratios": {"9:16", "1:1"}, "max_seconds": 600},
    "instagram-reels": {"ratios": {"9:16"}, "max_seconds": 180},
}


def _probe(path: Path) -> dict[str, Any]:
    cmd=[FFPROBE_BIN,'-v','error','-show_streams','-show_format','-of','json',str(path)]
    proc=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if proc.returncode!=0: return {"ok":False,"error":proc.stderr[-1200:]}
    try:
        data=json.loads(proc.stdout or '{}'); streams=data.get('streams') or []
        video=next((x for x in streams if x.get('codec_type')=='video'),{}); audio=next((x for x in streams if x.get('codec_type')=='audio'),{})
        return {"ok":True,"duration":float((data.get('format') or {}).get('duration') or 0),"width":int(video.get('width') or 0),"height":int(video.get('height') or 0),"video_codec":video.get('codec_name'),"audio_codec":audio.get('codec_name'),"has_audio":bool(audio),"fps":video.get('avg_frame_rate') or video.get('r_frame_rate')}
    except Exception as exc: return {"ok":False,"error":str(exc)}


def inspect(source: Path | None, state: dict[str, Any], timeline: dict[str, Any], output_path: Path | None = None, platform: str | None = None) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}
    if not source or not source.exists():
        errors.append("Fonte original indisponível para render final.")
    comp = timeline.get("composition") or {}
    duration = float(comp.get("duration") or 0)
    width=int(comp.get('width') or 0); height=int(comp.get('height') or 0); aspect=str(comp.get('aspectRatio') or state.get('aspect_ratio') or '')
    if duration <= 0: errors.append("Duração da composição inválida.")
    if width<2 or height<2: errors.append('Resolução da composição inválida.')
    for tr in timeline.get("tracks") or []:
        for item in tr.get("items") or []:
            start = float(item.get("from") or 0); length = float(item.get("duration") or 0)
            if length <= 0: errors.append(f"Item {item.get('id') or item.get('type')} possui duração inválida.")
            if start < 0 or (duration > 0 and start > duration + 0.05): warnings.append(f"Item {item.get('id') or item.get('type')} está fora da composição.")
            if duration>0 and start+length>duration+.25: warnings.append(f"Item {item.get('id') or item.get('type')} ultrapassa o fim da composição.")
    safe_left,safe_right=width*.04,width*.96; safe_top,safe_bottom=height*.04,height*.92
    for o in state.get("overlays") or []:
        x,y=float(o.get('x') or 0),float(o.get('y') or 0);w,h=float(o.get('width') or 0),float(o.get('height') or 0)
        if x+w<0 or y+h<0 or x>width or y>height: warnings.append(f"Overlay {o.get('id') or o.get('type') or 'camada'} está fora da área visível.")
        elif x<safe_left or x+w>safe_right or y<safe_top or y+h>safe_bottom: warnings.append(f"Overlay {o.get('id') or o.get('type') or 'camada'} encosta na safe-zone da plataforma.")
    if platform:
        spec=PLATFORM_SPECS.get(platform)
        if spec:
            if aspect and aspect not in spec['ratios']: warnings.append(f"Aspect ratio {aspect} não é o formato preferido para {platform}.")
            if duration>float(spec['max_seconds']): warnings.append(f"Duração acima do limite configurado para {platform}.")
    if output_path:
        output_path=Path(output_path)
        if not output_path.exists() or output_path.stat().st_size<1024: errors.append('Arquivo renderizado ausente ou vazio.')
        else:
            probed=_probe(output_path); checks['render_probe']=probed
            if not probed.get('ok'): errors.append('FFprobe não conseguiu validar o render final.')
            else:
                if not probed.get('video_codec'): errors.append('Render sem stream de vídeo.')
                if not probed.get('has_audio'): warnings.append('Render final não possui áudio.')
                actual=float(probed.get('duration') or 0)
                if duration>0 and abs(actual-duration)>.75: warnings.append(f'Duração do arquivo ({actual:.2f}s) difere da timeline ({duration:.2f}s).')
                if width and height and (int(probed.get('width') or 0)!=width or int(probed.get('height') or 0)!=height): warnings.append('Resolução do arquivo difere da composição.')
    checks['platform']=platform;checks['aspect_ratio']=aspect;checks['duration']=duration
    return {"errors":errors,"warnings":warnings,"checks":checks,"ok":not errors}
