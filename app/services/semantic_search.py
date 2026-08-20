from __future__ import annotations

import hashlib
import math
import re
from typing import Any


def _tokens(text: str) -> list[str]:
    return [x for x in re.findall(r'[\wÀ-ÿ]+',(text or '').lower()) if len(x)>1]


def hash_embedding(text: str, dims: int=256) -> list[float]:
    vec=[0.0]*dims
    for token in _tokens(text):
        h=int(hashlib.sha256(token.encode()).hexdigest()[:16],16)
        idx=h%dims; sign=1.0 if ((h>>9)&1) else -1.0
        vec[idx]+=sign*(1.0+min(2.0,len(token)/10.0))
    norm=math.sqrt(sum(v*v for v in vec)) or 1.0
    return [v/norm for v in vec]


def cosine(a:list[float],b:list[float])->float:
    return sum(x*y for x,y in zip(a,b)) / ((math.sqrt(sum(x*x for x in a)) or 1)*(math.sqrt(sum(y*y for y in b)) or 1))


def search_transcript(transcript: dict[str,Any], query: str, *, limit: int=12) -> list[dict[str,Any]]:
    qvec=hash_embedding(query); qtokens=set(_tokens(query)); results=[]
    segments=transcript.get('segments') or []
    # Search single segments and short 2-segment windows to catch context crossing sentence boundaries.
    windows=[]
    for i,seg in enumerate(segments):
        windows.append((i,i,[seg]))
        if i+1<len(segments): windows.append((i,i+1,[seg,segments[i+1]]))
    for i,j,items in windows:
        text=' '.join(str(x.get('text') or '') for x in items).strip()
        if not text: continue
        toks=set(_tokens(text)); lexical=len(qtokens&toks)/max(1,len(qtokens))
        semantic=(cosine(qvec,hash_embedding(text))+1)/2
        score=.65*semantic+.35*lexical
        results.append({"start":float(items[0].get('start') or 0),"end":float(items[-1].get('end') or 0),"text":text,"score":round(score,4),"segment_start":i,"segment_end":j})
    results.sort(key=lambda x:x['score'],reverse=True)
    # Avoid near-duplicate overlapping windows.
    out=[]
    for item in results:
        if any(abs(item['start']-x['start'])<.25 for x in out): continue
        out.append(item)
        if len(out)>=max(1,min(50,int(limit))): break
    return out


def answer_from_transcript(transcript: dict[str, Any], question: str, *, limit: int = 5) -> dict[str, Any]:
    """Grounded local Q&A: returns only transcript evidence, never invents facts."""
    hits=search_transcript(transcript,question,limit=max(1,min(8,limit)))
    if not hits:
        return {"answer":"Não encontrei um trecho do transcript que responda com segurança.","evidence":[],"grounded":True}
    top=hits[:3]
    excerpts=[]
    for h in top:
        text=str(h.get('text') or '').strip()
        if text: excerpts.append(text)
    # Extractive by design: no remote LLM and no unsupported synthesis.
    answer=' '.join(excerpts)
    if len(answer)>900: answer=answer[:897].rstrip()+'…'
    return {"answer":answer,"evidence":top,"grounded":True,"method":"local-semantic-extractive"}
