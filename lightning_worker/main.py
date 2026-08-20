from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

API_VERSION = 3
ROOT = Path(os.getenv("VIRALCLIP_LIGHTNING_DATA", "data/lightning_worker")).resolve()
UPLOADS = ROOT / "uploads"
RESULTS = ROOT / "results"
CACHE = ROOT / "cache"
DB = ROOT / "worker.db"
TOKEN = os.getenv("VIRALCLIP_LIGHTNING_TOKEN", "").strip()
FREE_CPU_ONLY = True
HEAVY_SLOTS = 1
LEASE_SECONDS = 45
MAX_UPLOAD_BYTES = int(os.getenv('VIRALCLIP_LIGHTNING_MAX_UPLOAD_MB','2048')) * 1024 * 1024
for d in (ROOT, UPLOADS, RESULTS, CACHE):
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="ViralClip Lightning FREE CPU Worker", version="4.2.0")
executor = ThreadPoolExecutor(max_workers=HEAVY_SLOTS, thread_name_prefix="viralclip-lightning-free-cpu")
_db_lock = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS uploads(
                id TEXT PRIMARY KEY, name TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL,
                chunk_size INTEGER NOT NULL, total_chunks INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'uploading',
                final_path TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS upload_chunks(
                upload_id TEXT NOT NULL, chunk_index INTEGER NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
                created_at TEXT NOT NULL, PRIMARY KEY(upload_id,chunk_index)
            );
            CREATE TABLE IF NOT EXISTS jobs(
                id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE, task_type TEXT NOT NULL, upload_id TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}', state TEXT NOT NULL DEFAULT 'queued', progress REAL NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT 'Na fila', result_json TEXT NOT NULL DEFAULT '{}', error_message TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0, heartbeat_at TEXT, lease_expires_at TEXT,
                created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state,created_at);
            CREATE TABLE IF NOT EXISTS result_cache(
                cache_key TEXT PRIMARY KEY, task_type TEXT NOT NULL, result_json TEXT NOT NULL,
                created_at TEXT NOT NULL, last_used_at TEXT NOT NULL, hit_count INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        # Interrupted running jobs are safe to retry because every request is idempotent.
        conn.execute("UPDATE jobs SET state='queued',message='Recuperado após reinício',lease_expires_at=NULL WHERE state='running'")
        conn.commit()


init_db()


def _auth(authorization: str | None) -> None:
    if not TOKEN:
        raise HTTPException(503, "VIRALCLIP_LIGHTNING_TOKEN não configurado no worker")
    if not authorization or authorization != f"Bearer {TOKEN}":
        raise HTTPException(401, "Token inválido")


def _row(sql: str, params=()):
    with connect() as conn:
        return conn.execute(sql, tuple(params)).fetchone()


def _rows(sql: str, params=()):
    with connect() as conn:
        return conn.execute(sql, tuple(params)).fetchall()


def _execute(sql: str, params=()) -> None:
    with connect() as conn:
        conn.execute(sql, tuple(params)); conn.commit()


def _job_payload(row) -> dict[str, Any]:
    result = dict(row)
    try: result["payload"] = json.loads(result.pop("payload_json") or "{}")
    except Exception: result["payload"] = {}
    try: result["result"] = json.loads(result.pop("result_json") or "{}")
    except Exception: result["result"] = {}
    result["error"] = result.pop("error_message", None)
    result["cancel_requested"] = bool(result.get("cancel_requested"))
    return result


def _sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        while True:
            b=f.read(4*1024*1024)
            if not b: break
            h.update(b)
    return h.hexdigest()




def _effective_cpu_count() -> int:
    """Best-effort cgroup-aware CPU count for Lightning containers."""
    host=max(1,int(os.cpu_count() or 1))
    try:
        cpu_max=Path('/sys/fs/cgroup/cpu.max')
        if cpu_max.exists():
            quota,period=cpu_max.read_text(encoding='utf-8').strip().split()[:2]
            if quota!='max':
                effective=max(1,int(float(quota)/max(1.0,float(period)) + .999))
                return min(host,effective)
    except Exception:
        pass
    try:
        quota=Path('/sys/fs/cgroup/cpu/cpu.cfs_quota_us')
        period=Path('/sys/fs/cgroup/cpu/cpu.cfs_period_us')
        if quota.exists() and period.exists():
            q=float(quota.read_text().strip()); p=float(period.read_text().strip())
            if q>0 and p>0: return min(host,max(1,int(q/p + .999)))
    except Exception:
        pass
    return host


def _machine_caps() -> dict[str, Any]:
    # Detect an actually usable NVIDIA GPU, not merely environment variables.
    # Some CPU containers expose NVIDIA_* variables even when no device exists.
    gpu = False
    gpu_name = None
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            proc = subprocess.run([nvidia_smi,"--query-gpu=name","--format=csv,noheader"],capture_output=True,text=True,timeout=5)
            first = next((x.strip() for x in (proc.stdout or "").splitlines() if x.strip()), "")
            gpu = proc.returncode == 0 and bool(first)
            gpu_name = first or None
        except Exception:
            gpu = False
    cpu_count=_effective_cpu_count()
    cpu_is_free_shape=cpu_count <= 4
    return {
        "api_version": API_VERSION,
        "free_cpu_only": True,
        "cpu_count": cpu_count,
        "ram_mb": _ram_mb(),
        "gpu": gpu,
        "gpu_name": gpu_name,
        "machine_type": "gpu-rejected" if gpu else ("free-cpu" if cpu_is_free_shape else "paid-cpu-rejected"),
        "heavy_slots": HEAVY_SLOTS,
        "tasks": ["asr_segments", "asr_words", "highlights", "tracking", "embeddings", "editor_proxy"],
    }


def _ram_mb() -> int:
    try:
        pages=os.sysconf('SC_PHYS_PAGES'); size=os.sysconf('SC_PAGE_SIZE'); return int(pages*size/1024/1024)
    except Exception: return 0


def _assert_free_cpu() -> None:
    caps=_machine_caps()
    if caps["gpu"] or caps["machine_type"] != "free-cpu":
        raise RuntimeError("Worker recusou execução: V4.2 aceita somente a CPU gratuita da Lightning.")


def _queue_status() -> dict[str, int]:
    q=_row("SELECT COUNT(*) n FROM jobs WHERE state='queued'")
    a=_row("SELECT COUNT(*) n FROM jobs WHERE state='running'")
    return {"queued": int(q["n"] if q else 0), "active": int(a["n"] if a else 0)}


@app.get('/health')
def health(authorization: str | None = Header(default=None)):
    _auth(authorization)
    caps=_machine_caps()
    status="online" if (not caps["gpu"] and caps["machine_type"]=="free-cpu") else "rejected-paid-or-gpu"
    return {"ok": status=="online", "status": status, "capabilities": caps, "queue": _queue_status(), "server_time": now_iso()}


@app.get('/capabilities')
def capabilities(authorization: str | None = Header(default=None)):
    _auth(authorization); return _machine_caps()


@app.post('/uploads/init')
def upload_init(payload: dict[str, Any] = Body(...), authorization: str | None = Header(default=None)):
    _auth(authorization); _assert_free_cpu()
    sha=str(payload.get('sha256') or '').lower(); size=int(payload.get('size') or 0); total=int(payload.get('total_chunks') or 0); chunk_size=int(payload.get('chunk_size') or 0)
    if len(sha)!=64 or size<0 or total<1 or chunk_size<1024*1024:
        raise HTTPException(400,'Manifesto de upload inválido')
    if size > MAX_UPLOAD_BYTES:
        raise HTTPException(413,'Upload excede o limite seguro do worker CPU grátis')
    existing=_row("SELECT * FROM uploads WHERE sha256=? AND size=? AND state='complete' ORDER BY created_at DESC LIMIT 1",(sha,size))
    if existing and existing['final_path'] and Path(existing['final_path']).exists():
        return {"upload_id":existing['id'],"present_chunks":list(range(int(existing['total_chunks']))),"complete":True,"deduplicated":True}
    upload_id=uuid.uuid4().hex
    root=UPLOADS/upload_id; root.mkdir(parents=True,exist_ok=True)
    _execute("INSERT INTO uploads(id,name,size,sha256,chunk_size,total_chunks,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(upload_id,Path(str(payload.get('name') or 'media.bin')).name,size,sha,chunk_size,total,'uploading',now_iso(),now_iso()))
    return {"upload_id":upload_id,"present_chunks":[],"complete":False}


@app.put('/uploads/{upload_id}/chunks/{chunk_index}')
async def upload_chunk(upload_id: str, chunk_index: int, request: Request, x_chunk_sha256: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    _auth(authorization); _assert_free_cpu(); row=_row("SELECT * FROM uploads WHERE id=?",(upload_id,))
    if not row: raise HTTPException(404,'Upload inexistente')
    if chunk_index<0 or chunk_index>=int(row['total_chunks']): raise HTTPException(400,'Chunk inválido')
    data=await request.body(); actual=hashlib.sha256(data).hexdigest()
    if not x_chunk_sha256 or actual.lower()!=x_chunk_sha256.lower(): raise HTTPException(400,'SHA-256 do chunk não confere')
    root=UPLOADS/upload_id; root.mkdir(parents=True,exist_ok=True); part=root/f'{chunk_index:08d}.part'; part.write_bytes(data)
    _execute("INSERT INTO upload_chunks(upload_id,chunk_index,sha256,size,created_at) VALUES(?,?,?,?,?) ON CONFLICT(upload_id,chunk_index) DO UPDATE SET sha256=excluded.sha256,size=excluded.size",(upload_id,chunk_index,actual,len(data),now_iso()))
    return {"ok":True,"chunk":chunk_index}


@app.post('/uploads/{upload_id}/complete')
def upload_complete(upload_id: str, payload: dict[str, Any] = Body(default={}), authorization: str | None = Header(default=None)):
    _auth(authorization); _assert_free_cpu(); row=_row("SELECT * FROM uploads WHERE id=?",(upload_id,))
    if not row: raise HTTPException(404,'Upload inexistente')
    chunks=_rows("SELECT * FROM upload_chunks WHERE upload_id=? ORDER BY chunk_index",(upload_id,))
    if len(chunks)!=int(row['total_chunks']):
        missing=sorted(set(range(int(row['total_chunks'])))-{int(c['chunk_index']) for c in chunks}); raise HTTPException(409,detail={"missing_chunks":missing})
    root=UPLOADS/upload_id; final=root/Path(row['name']).name
    with final.open('wb') as out:
        for i in range(int(row['total_chunks'])):
            part=root/f'{i:08d}.part'
            if not part.exists(): raise HTTPException(409,f'Chunk {i} ausente')
            with part.open('rb') as f: shutil.copyfileobj(f,out)
    if final.stat().st_size!=int(row['size']) or _sha256(final).lower()!=str(row['sha256']).lower():
        final.unlink(missing_ok=True); raise HTTPException(400,'Arquivo final não confere com o manifesto')
    # Never trust extension/MIME alone. ffprobe must recognize the uploaded media.
    try:
        check=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(final)],capture_output=True,text=True,timeout=20)
    except Exception as exc:
        final.unlink(missing_ok=True); raise HTTPException(400,f'Não foi possível validar mídia: {exc}')
    if check.returncode != 0:
        final.unlink(missing_ok=True); raise HTTPException(400,'Arquivo enviado não é uma mídia válida para o worker')
    _execute("UPDATE uploads SET state='complete',final_path=?,updated_at=? WHERE id=?",(str(final),now_iso(),upload_id))
    return {"upload_id":upload_id,"complete":True,"sha256":row['sha256'],"size":row['size']}


def _cache_key(task_type: str, upload_sha: str, payload: dict[str, Any]) -> str:
    raw=json.dumps({"task":task_type,"media":upload_sha,"payload":payload,"worker":API_VERSION},sort_keys=True,ensure_ascii=False,separators=(',',':'))
    return hashlib.sha256(raw.encode()).hexdigest()


@app.post('/jobs')
def create_job(payload: dict[str, Any] = Body(...), authorization: str | None = Header(default=None), idempotency_key: str | None = Header(default=None)):
    _auth(authorization); _assert_free_cpu()
    if not bool(payload.get('free_cpu_only',False)): raise HTTPException(400,'Cliente deve declarar free_cpu_only=true')
    task_type=str(payload.get('task_type') or '')
    if task_type not in {'asr_segments','asr_words','highlights','tracking','embeddings','editor_proxy'}: raise HTTPException(400,'Tarefa não permitida no worker CPU grátis')
    idem=(idempotency_key or '').strip()
    if idem:
        old=_row("SELECT id FROM jobs WHERE idempotency_key=?",(idem,))
        if old: return {"job_id":old['id'],"deduplicated":True}
    upload_id=payload.get('upload_id')
    if task_type in {'asr_segments','asr_words','tracking','editor_proxy'}:
        up=_row("SELECT * FROM uploads WHERE id=? AND state='complete'",(upload_id,))
        if not up: raise HTTPException(400,'Tarefa exige upload completo')
    job_id=uuid.uuid4().hex
    _execute("INSERT INTO jobs(id,idempotency_key,task_type,upload_id,payload_json,state,progress,message,created_at,updated_at) VALUES(?,?,?,?,?,'queued',0,'Na fila',?,?)",(job_id,idem or None,task_type,upload_id,json.dumps(payload.get('payload') or {},ensure_ascii=False),now_iso(),now_iso()))
    executor.submit(_process_job,job_id)
    return {"job_id":job_id,"deduplicated":False}


@app.get('/jobs/{job_id}')
def get_job(job_id: str, authorization: str | None = Header(default=None)):
    _auth(authorization); row=_row("SELECT * FROM jobs WHERE id=?",(job_id,))
    if not row: raise HTTPException(404,'Job inexistente')
    return _job_payload(row)


@app.get('/jobs/{job_id}/result-file')
def job_result_file(job_id: str, authorization: str | None = Header(default=None)):
    _auth(authorization)
    row = _row("SELECT state,result_json FROM jobs WHERE id=?", (job_id,))
    if not row: raise HTTPException(404, 'Job inexistente')
    if row['state'] != 'done': raise HTTPException(409, 'Resultado ainda não está pronto')
    try: result = json.loads(row['result_json'] or '{}')
    except Exception: result = {}
    path = Path(str(result.get('file_path') or '')).resolve()
    if RESULTS.resolve() not in path.parents or not path.is_file():
        raise HTTPException(404, 'Arquivo de resultado indisponível')
    return FileResponse(path, media_type=str(result.get('content_type') or 'application/octet-stream'), filename=path.name)




@app.get('/jobs/{job_id}/events')
def job_events(job_id: str, authorization: str | None = Header(default=None)):
    _auth(authorization)
    if not _row("SELECT id FROM jobs WHERE id=?", (job_id,)):
        raise HTTPException(404, 'Job inexistente')

    def stream():
        last = None
        while True:
            row = _row("SELECT * FROM jobs WHERE id=?", (job_id,))
            if not row:
                yield 'event: error\ndata: {"error":"not_found"}\n\n'
                return
            payload = _job_payload(row)
            compact = json.dumps({
                "id": payload["id"], "state": payload["state"],
                "progress": payload["progress"], "message": payload["message"],
                "heartbeat_at": payload.get("heartbeat_at"), "error": payload.get("error"),
            }, ensure_ascii=False)
            if compact != last:
                yield f"event: progress\ndata: {compact}\n\n"
                last = compact
            if payload["state"] in {"done", "failed", "cancelled"}:
                yield f"event: complete\ndata: {compact}\n\n"
                return
            time.sleep(1.0)

    return StreamingResponse(stream(), media_type='text/event-stream', headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


@app.post('/jobs/{job_id}/cancel')
def cancel_job(job_id: str, authorization: str | None = Header(default=None)):
    _auth(authorization); row=_row("SELECT id,state FROM jobs WHERE id=?",(job_id,))
    if not row: raise HTTPException(404,'Job inexistente')
    if row['state'] in {'done','failed','cancelled'}: return {"ok":True,"state":row['state']}
    _execute("UPDATE jobs SET cancel_requested=1,message='Cancelamento solicitado',updated_at=? WHERE id=?",(now_iso(),job_id)); return {"ok":True,"state":"cancelling"}


def _update_job(job_id: str, *, state: str | None=None, progress: float | None=None, message: str | None=None, result: dict|None=None, error: str|None=None) -> None:
    stamp=now_iso(); lease=(datetime.now(timezone.utc)+timedelta(seconds=LEASE_SECONDS)).isoformat()
    sets=['updated_at=?','heartbeat_at=?']; params=[stamp,stamp]
    if state is not None:
        sets.append('state=?');params.append(state)
        if state=='running':
            sets.append('started_at=COALESCE(started_at,?)');params.append(stamp)
            sets.append('lease_expires_at=?');params.append(lease)
        if state in {'done','failed','cancelled'}:
            sets.append('finished_at=?');params.append(stamp)
            sets.append('lease_expires_at=NULL')
    else:
        current=_row("SELECT state FROM jobs WHERE id=?",(job_id,))
        if current and current['state']=='running': sets.append('lease_expires_at=?');params.append(lease)
    if progress is not None: sets.append('progress=?');params.append(max(0,min(1,float(progress))))
    if message is not None: sets.append('message=?');params.append(str(message)[:500])
    if result is not None: sets.append('result_json=?');params.append(json.dumps(result,ensure_ascii=False))
    if error is not None: sets.append('error_message=?');params.append(str(error)[:3000])
    params.append(job_id); _execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?",params)


def _cancelled(job_id: str) -> bool:
    row=_row("SELECT cancel_requested FROM jobs WHERE id=?",(job_id,)); return bool(row and row['cancel_requested'])


def _media(job) -> tuple[Path|None,str]:
    if not job['upload_id']: return None,''
    up=_row("SELECT * FROM uploads WHERE id=?",(job['upload_id'],))
    if not up or not up['final_path']: return None,''
    return Path(up['final_path']),str(up['sha256'])


def _worker_profile(model: str) -> dict:
    return {
        "gpu_vendor":"cpu","platform":"linux","cpu_threads":int(os.cpu_count() or 4),
        "transcription":{"backend":"cpu","model":model or 'small',"cpu_threads":max(1,min(4,int(os.cpu_count() or 4))),"num_workers":1},
        "asr":{"selected_backend":"faster-whisper-cpu"},
        "analysis":{"tracking_fps":1.2,"width":480},
    }


def _process_job(job_id: str) -> None:
    row=_row("SELECT * FROM jobs WHERE id=?",(job_id,))
    if not row: return
    job=_job_payload(row); task=job['task_type']; payload=job['payload']; media,media_sha=_media(job)
    cache_key=_cache_key(task,media_sha,payload)
    cached=_row("SELECT * FROM result_cache WHERE cache_key=?",(cache_key,))
    if cached:
        try: result=json.loads(cached['result_json'] or '{}')
        except Exception: result={}
        _execute("UPDATE result_cache SET hit_count=hit_count+1,last_used_at=? WHERE cache_key=?",(now_iso(),cache_key))
        _update_job(job_id,state='done',progress=1,message='Resultado reutilizado do cache',result=result); return
    try:
        _assert_free_cpu(); _update_job(job_id,state='running',progress=.01,message='CPU grátis iniciada')
        result=_run_task(job_id,task,payload,media)
        if _cancelled(job_id): _update_job(job_id,state='cancelled',message='Cancelado'); return
        _execute("INSERT INTO result_cache(cache_key,task_type,result_json,created_at,last_used_at,hit_count) VALUES(?,?,?,?,?,0) ON CONFLICT(cache_key) DO UPDATE SET result_json=excluded.result_json,last_used_at=excluded.last_used_at",(cache_key,task,json.dumps(result,ensure_ascii=False),now_iso(),now_iso()))
        _update_job(job_id,state='done',progress=1,message='Concluído na Lightning CPU grátis',result=result)
    except Exception as exc:
        _update_job(job_id,state='failed',message='Falha no worker CPU grátis',error=f'{type(exc).__name__}: {exc}')


def _run_task(job_id: str, task: str, payload: dict[str,Any], media: Path|None) -> dict:
    if task=='editor_proxy':
        if media is None: raise RuntimeError('Mídia ausente')
        from app.services.proxy_media import ensure_editor_proxy
        start=max(0.0,float(payload.get('start') or 0)); end=max(start+.05,float(payload.get('end') or start+.05))
        height=max(240,min(1080,int(payload.get('target_height') or 480)))
        _update_job(job_id,progress=.08,message='Preparando visualização')
        cached=ensure_editor_proxy(job_id,media,start,end,target_height=height,prefer_cloud=False)
        target=RESULTS/f'{job_id}.proxy.mp4'; shutil.copy2(cached,target)
        _update_job(job_id,progress=.98,message='Visualização pronta')
        return {'file_path':str(target.resolve()),'content_type':'video/mp4'}
    if task in {'asr_segments','asr_words'}:
        if media is None: raise RuntimeError('Mídia ausente')
        from app.services.transcriber import transcribe_segments, transcribe_words
        profile=_worker_profile(str(payload.get('model') or 'small'))
        def cb(frac: float, backend: str):
            if _cancelled(job_id): raise RuntimeError('cancelled')
            _update_job(job_id,progress=max(.02,min(.98,float(frac))),message=f'{backend} · CPU grátis')
        if task=='asr_segments': return transcribe_segments(media,language=payload.get('language'),progress_callback=cb,hardware_profile=profile,backend_id='faster-whisper-cpu')
        return transcribe_words(media,float(payload.get('start') or 0),float(payload.get('end') or 0),language=payload.get('language'),progress_callback=cb,hardware_profile=profile,backend_id='faster-whisper-cpu')
    if task=='highlights':
        from app.services.analyzer import find_highlights, sequential_highlights
        transcript=payload.get('transcript') or {}; settings=payload.get('settings') or {}; mode=str(settings.get('mode') or 'smart')
        _update_job(job_id,progress=.3,message='Analisando momentos na CPU grátis')
        if mode=='sequential': candidates=sequential_highlights(transcript,float(settings.get('target_duration',60)))
        else: candidates=find_highlights(transcript,num_clips=int(settings.get('num_clips',5)),min_duration=float(settings.get('min_duration',20)),max_duration=float(settings.get('max_duration',90)),custom_keywords=settings.get('custom_keywords','') or settings.get('prompt',''),use_llm=False)
        return {"candidates":candidates}
    if task=='tracking':
        if media is None: raise RuntimeError('Proxy ausente')
        from app.services.face_tracking import analyze_window
        from app.services.render import probe_video
        duration=max(.1,float(probe_video(media).get('duration') or .1))
        def cb(frac:float,backend:str):
            if _cancelled(job_id): return
            _update_job(job_id,progress=max(.02,min(.98,float(frac))),message=f'Face Tracking · {backend} · CPU grátis')
        return analyze_window(media,0,duration,out_path=RESULTS/f'{job_id}.tracking.json',fps=float(payload.get('fps') or 1.0),analysis_width=int(payload.get('analysis_width') or 480),progress_callback=cb,cancel_check=lambda:_cancelled(job_id))
    if task=='embeddings':
        texts=[str(x) for x in payload.get('texts') or []]
        return {"vectors":[_hash_embedding(t) for t in texts],"method":"hashing-v1","dimensions":256}
    raise RuntimeError(f'Tarefa não suportada: {task}')


def _hash_embedding(text: str, dims: int=256) -> list[float]:
    import math,re
    vec=[0.0]*dims
    for token in re.findall(r'[\wÀ-ÿ]+',text.lower()):
        h=int(hashlib.sha256(token.encode()).hexdigest()[:16],16); idx=h%dims; sign=1.0 if (h>>8)&1 else -1.0; vec[idx]+=sign
    norm=math.sqrt(sum(v*v for v in vec)) or 1.0
    return [round(v/norm,6) for v in vec]


def cleanup() -> dict[str,int]:
    media_cutoff=datetime.now(timezone.utc)-timedelta(hours=max(1,int(os.getenv('CLOUD_MEDIA_RETENTION_HOURS','24'))))
    removed=0
    for row in _rows("SELECT * FROM uploads WHERE updated_at<?",(media_cutoff.isoformat(),)):
        root=UPLOADS/row['id']; shutil.rmtree(root,ignore_errors=True); _execute("DELETE FROM upload_chunks WHERE upload_id=?",(row['id'],)); _execute("DELETE FROM uploads WHERE id=?",(row['id'],)); removed+=1
    return {"uploads_removed":removed}


@app.post('/maintenance/cleanup')
def maintenance_cleanup(authorization: str | None = Header(default=None)):
    _auth(authorization); return cleanup()
