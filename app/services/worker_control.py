from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from app.db import fetchone
from . import job_store


class JobCancelled(RuntimeError):
    pass


class JobControl:
    """Cooperative pause/cancel control backed by the persistent job row."""
    def __init__(self, job_id: str):
        self.job_id = job_id

    def snapshot(self) -> dict[str, Any] | None:
        row = fetchone("SELECT status,control_state,heartbeat_at FROM worker_jobs WHERE id=?", (self.job_id,))
        return dict(row) if row else None

    def is_paused(self) -> bool:
        snap = self.snapshot() or {}
        return snap.get("control_state") == "paused"

    def should_cancel(self) -> bool:
        snap = self.snapshot() or {}
        return snap.get("control_state") == "cancelled" or snap.get("status") == "cancelled"

    def wait_if_paused(self, *, poll_seconds: float = 0.2) -> None:
        while self.is_paused():
            if self.should_cancel():
                raise JobCancelled("Job cancelado pelo usuário")
            time.sleep(max(0.05, poll_seconds))

    def checkpoint(self) -> None:
        if self.should_cancel():
            raise JobCancelled("Job cancelado pelo usuário")
        self.wait_if_paused()

    def heartbeat(self, message: str | None = None) -> None:
        job_store.update_stage(self.job_id, message=message)


def is_stale(snapshot: dict[str, Any] | None, *, stale_after_seconds: int = 120) -> bool:
    if not snapshot or not snapshot.get("heartbeat_at"):
        return True
    try:
        value = datetime.fromisoformat(str(snapshot["heartbeat_at"]))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
    except Exception:
        return True
    return (datetime.now(timezone.utc) - value).total_seconds() > max(1, stale_after_seconds)


def tracking_attempts(profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    analysis = dict((profile or {}).get("analysis") or {})
    fps = max(0.5, float(analysis.get("tracking_fps") or 1.0))
    width = max(360, int(analysis.get("width") or 640))
    return [
        {"fps": fps, "width": width, "detector_backend": "auto", "timeout_factor": 2.5},
        {"fps": max(0.5, round(fps * 0.6, 2)), "width": max(360, int(width * 0.75)), "detector_backend": "auto", "timeout_factor": 2.0},
        {"fps": 0.5, "width": 360, "detector_backend": "haar", "timeout_factor": 1.5},
    ]


def asr_memory_policy(profile: dict[str, Any] | None) -> dict[str, Any]:
    """Bound resident ASR work by the detected RAM/profile tier."""
    data = profile or {}
    ram_mb = int(data.get("ram_mb") or 0)
    tier = str((data.get("profile") or {}).get("name") or "balanced").lower()
    if ram_mb and ram_mb < 8192 or tier == "eco":
        return {"warm_model": False, "max_workers": 1}
    if ram_mb >= 24576 and tier == "turbo":
        return {"warm_model": True, "max_workers": 2}
    return {"warm_model": ram_mb >= 8192 or ram_mb == 0, "max_workers": 1}
