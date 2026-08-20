from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.db import execute, fetchall, fetchone, now_iso


def _pct(current: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return round(max(0.0, min(100.0, current / total * 100.0)), 1)


def create_job(kind: str, target_id: str | None = None, *, job_id: str | None = None, message: str = "Na fila") -> str:
    jid = job_id or uuid.uuid4().hex
    now = now_iso()
    execute(
        "INSERT OR REPLACE INTO worker_jobs(id,kind,target_id,status,message,heartbeat_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (jid, kind, target_id, "queued", message, now, now, now),
    )
    return jid


def start_stage(job_id: str, stage: str, *, total: float = 0.0, backend: str | None = None, message: str | None = None, attempt: int = 1) -> None:
    now = now_iso()
    execute(
        "UPDATE worker_jobs SET status='running',stage=?,message=?,progress_current=0,progress_total=?,speed=0,eta_seconds=NULL,backend=?,attempt=?,heartbeat_at=?,updated_at=? WHERE id=?",
        (stage, message or stage, float(total or 0), backend, attempt, now, now, job_id),
    )
    execute(
        "INSERT OR REPLACE INTO worker_job_stages(job_id,stage,status,progress_current,progress_total,speed,eta_seconds,backend,message,started_at,heartbeat_at,finished_at,attempt) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (job_id, stage, "running", 0.0, float(total or 0), 0.0, None, backend, message or stage, now, now, None, attempt),
    )


def update_stage(job_id: str, *, current: float | None = None, total: float | None = None, speed: float | None = None, message: str | None = None, backend: str | None = None) -> None:
    row = fetchone("SELECT * FROM worker_jobs WHERE id=?", (job_id,))
    if not row:
        return
    cur = float(row["progress_current"] or 0) if current is None else float(current)
    tot = float(row["progress_total"] or 0) if total is None else float(total)
    spd = float(row["speed"] or 0) if speed is None else float(speed)
    eta = ((tot - cur) / spd) if spd > 0 and tot > cur else 0.0 if tot > 0 and cur >= tot else None
    msg = row["message"] if message is None else message
    be = row["backend"] if backend is None else backend
    now = now_iso()
    execute(
        "UPDATE worker_jobs SET progress_current=?,progress_total=?,speed=?,eta_seconds=?,message=?,backend=?,heartbeat_at=?,updated_at=? WHERE id=?",
        (cur, tot, spd, eta, msg, be, now, now, job_id),
    )
    if row["stage"]:
        execute(
            "UPDATE worker_job_stages SET progress_current=?,progress_total=?,speed=?,eta_seconds=?,message=?,backend=?,heartbeat_at=? WHERE job_id=? AND stage=? AND attempt=?",
            (cur, tot, spd, eta, msg, be, now, job_id, row["stage"], int(row["attempt"] or 1)),
        )


def finish_stage(job_id: str, *, message: str | None = None) -> None:
    row = fetchone("SELECT * FROM worker_jobs WHERE id=?", (job_id,))
    if not row:
        return
    now = now_iso()
    cur = float(row["progress_total"] or row["progress_current"] or 0)
    execute("UPDATE worker_jobs SET progress_current=?,message=?,heartbeat_at=?,updated_at=? WHERE id=?", (cur, message or row["message"], now, now, job_id))
    if row["stage"]:
        execute("UPDATE worker_job_stages SET status='done',progress_current=progress_total,message=?,heartbeat_at=?,finished_at=? WHERE job_id=? AND stage=? AND attempt=?", (message or row["message"], now, now, job_id, row["stage"], int(row["attempt"] or 1)))


def complete_job(job_id: str, message: str = "Concluído") -> None:
    finish_stage(job_id, message=message)
    now = now_iso()
    execute("UPDATE worker_jobs SET status='done',control_state='running',message=?,heartbeat_at=?,updated_at=? WHERE id=?", (message, now, now, job_id))


def fail_job(job_id: str, message: str, *, status: str = "error") -> None:
    row = fetchone("SELECT * FROM worker_jobs WHERE id=?", (job_id,))
    now = now_iso()
    if row and row["stage"]:
        execute("UPDATE worker_job_stages SET status=?,message=?,heartbeat_at=?,finished_at=? WHERE job_id=? AND stage=? AND attempt=?", (status, message, now, now, job_id, row["stage"], int(row["attempt"] or 1)))
    execute("UPDATE worker_jobs SET status=?,message=?,heartbeat_at=?,updated_at=? WHERE id=?", (status, message, now, now, job_id))


def set_control(job_id: str, state: str) -> None:
    if state not in {"running", "paused", "cancelled"}:
        raise ValueError("invalid control state")
    now = now_iso()
    execute("UPDATE worker_jobs SET control_state=?,status=CASE WHEN ?='paused' THEN 'paused' WHEN ?='cancelled' THEN 'cancelled' WHEN status='paused' THEN 'running' ELSE status END,heartbeat_at=?,updated_at=? WHERE id=?", (state, state, state, now, now, job_id))


def latest_job(kind: str, target_id: str) -> dict[str, Any] | None:
    row = fetchone("SELECT id FROM worker_jobs WHERE kind=? AND target_id=? ORDER BY created_at DESC LIMIT 1", (kind, target_id))
    return job_snapshot(row["id"]) if row else None


def job_snapshot(job_id: str) -> dict[str, Any] | None:
    row = fetchone("SELECT * FROM worker_jobs WHERE id=?", (job_id,))
    if not row:
        return None
    data = dict(row)
    data["percent"] = _pct(float(data.get("progress_current") or 0), float(data.get("progress_total") or 0))
    data["stages"] = [dict(x) for x in fetchall("SELECT * FROM worker_job_stages WHERE job_id=? ORDER BY id", (job_id,))]
    return data


def recover_stale_jobs(*, stale_after_seconds: int = 120) -> list[str]:
    now = datetime.now(timezone.utc)
    recovered: list[str] = []
    for row in fetchall("SELECT id,heartbeat_at FROM worker_jobs WHERE status='running'"):
        try:
            hb = datetime.fromisoformat(row["heartbeat_at"] or "")
            if hb.tzinfo is None:
                hb = hb.replace(tzinfo=timezone.utc)
        except Exception:
            hb = datetime.min.replace(tzinfo=timezone.utc)
        if (now - hb).total_seconds() > stale_after_seconds:
            msg = "Job interrompido por falta de heartbeat. Pode ser retomado ou tentado novamente."
            fail_job(row["id"], msg, status="interrupted")
            recovered.append(row["id"])
    return recovered
