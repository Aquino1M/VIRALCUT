from __future__ import annotations

import json
import math
import uuid
from statistics import median
from typing import Any

from app.db import execute, fetchall, fetchone, now_iso


def record_performance(
    user_id: int,
    *,
    clip_id: str | None,
    platform: str,
    views: int = 0,
    likes: int = 0,
    comments: int = 0,
    shares: int = 0,
    watch_seconds: float | None = None,
    completion_rate: float | None = None,
    hook_hold_rate: float | None = None,
    published_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row_id = uuid.uuid4().hex
    execute(
        """
        INSERT INTO creator_performance(id,user_id,clip_id,platform,views,likes,comments,shares,watch_seconds,completion_rate,hook_hold_rate,published_at,metadata_json,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (row_id, user_id, clip_id, (platform or "manual").lower(), max(0,int(views)), max(0,int(likes)), max(0,int(comments)), max(0,int(shares)),
         watch_seconds, completion_rate, hook_hold_rate, published_at, json.dumps(metadata or {},ensure_ascii=False), now_iso(), now_iso()),
    )
    return dict(fetchone("SELECT * FROM creator_performance WHERE id=?",(row_id,)))


def creator_profile(user_id: int) -> dict[str, Any]:
    rows=fetchall(
        """
        SELECT cp.*,c.start_time,c.end_time,c.score,c.analysis_json
        FROM creator_performance cp LEFT JOIN clips c ON c.id=cp.clip_id
        WHERE cp.user_id=? ORDER BY cp.created_at DESC LIMIT 500
        """,(user_id,)
    )
    if not rows:
        return {"samples":0,"confidence":0.0,"best_duration":None,"signals":{},"platforms":{}}
    items=[]
    for r in rows:
        views=max(0,int(r['views'] or 0)); likes=max(0,int(r['likes'] or 0)); comments=max(0,int(r['comments'] or 0)); shares=max(0,int(r['shares'] or 0))
        engagement=(likes+comments*2+shares*3)/max(1,views)
        completion=float(r['completion_rate'] or 0)
        hook=float(r['hook_hold_rate'] or 0)
        duration=max(0.0,float(r['end_time'] or 0)-float(r['start_time'] or 0)) if r['start_time'] is not None else 0.0
        quality=math.log10(views+10)*10 + min(30,engagement*300) + min(25,completion*25 if completion<=1 else completion*.25) + min(20,hook*20 if hook<=1 else hook*.2)
        items.append({"platform":r['platform'],"views":views,"duration":duration,"quality":quality,"engagement":engagement,"completion":completion,"hook":hook})
    ranked=sorted(items,key=lambda x:x['quality'],reverse=True)
    top=ranked[:max(3,min(30,len(ranked)//3 or 3))]
    durations=[x['duration'] for x in top if x['duration']>0]
    platforms={}
    for item in items:
        p=platforms.setdefault(item['platform'],{"samples":0,"views":0,"engagement_sum":0.0})
        p['samples']+=1;p['views']+=item['views'];p['engagement_sum']+=item['engagement']
    for p in platforms.values():
        p['avg_engagement']=round(p.pop('engagement_sum')/max(1,p['samples']),4)
    return {
        "samples":len(items),
        "confidence":round(min(1.0,len(items)/30.0),3),
        "best_duration":round(median(durations),1) if durations else None,
        "top_views":max(x['views'] for x in items),
        "platforms":platforms,
        "signals":{"avg_top_engagement":round(sum(x['engagement'] for x in top)/max(1,len(top)),4)},
    }


def calibrate_score(user_id: int, base_score: float, *, duration: float, platform: str | None = None) -> dict[str, Any]:
    profile=creator_profile(user_id)
    confidence=float(profile.get('confidence') or 0)
    if confidence<=0:
        return {"score":round(float(base_score),1),"delta":0.0,"confidence":0.0,"reason":"Sem histórico suficiente"}
    delta=0.0; reasons=[]
    best=profile.get('best_duration')
    if best and duration>0:
        diff=abs(float(duration)-float(best))
        duration_delta=max(-8.0,8.0-diff*.35)
        delta += duration_delta*confidence
        reasons.append(f"Duração histórica ideal ~{best:.0f}s")
    if platform and platform in (profile.get('platforms') or {}):
        p=profile['platforms'][platform]
        if float(p.get('avg_engagement') or 0)>.05:
            delta+=3.0*confidence; reasons.append(f"Bom histórico em {platform}")
    final=max(0,min(100,float(base_score)+delta))
    return {"score":round(final,1),"delta":round(final-float(base_score),1),"confidence":confidence,"reason":" · ".join(reasons) or "Calibração por histórico"}
