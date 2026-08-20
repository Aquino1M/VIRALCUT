from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid
from pathlib import Path
from typing import Any

from app.config import DATA_DIR
from app.db import execute, fetchone, now_iso

PAIR_STATE_PATH = DATA_DIR / "worker_pairing.json"
PAIR_TTL_SECONDS = 15 * 60


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def current_pair_code(*, force_new: bool = False) -> str:
    path = Path(PAIR_STATE_PATH)
    if not force_new and path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if float(data.get("expires_at") or 0) > time.time() and str(data.get("code") or ""):
                return str(data["code"])
        except Exception:
            pass
    code = f"{secrets.randbelow(1_000_000):06d}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"code": code, "expires_at": time.time() + PAIR_TTL_SECONDS}, indent=2), encoding="utf-8")
    return code


def issue_token(code: str, device_name: str = "Browser") -> dict[str, Any]:
    path = Path(PAIR_STATE_PATH)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raise ValueError("pairing_code_invalid")
    if float(state.get("expires_at") or 0) <= time.time() or not secrets.compare_digest(str(state.get("code") or ""), str(code or "")):
        raise ValueError("pairing_code_invalid")
    token = secrets.token_urlsafe(32)
    pairing_id = uuid.uuid4().hex
    execute(
        "INSERT INTO worker_pairings(id,device_name,token_hash,revoked,created_at,last_used_at) VALUES(?,?,?,?,?,?)",
        (pairing_id, (device_name or "Browser")[:120], _hash(token), 0, now_iso(), now_iso()),
    )
    # A code is one-time; immediately rotate it after successful pairing.
    current_pair_code(force_new=True)
    return {"id": pairing_id, "token": token, "device_name": (device_name or "Browser")[:120]}


def validate_token(token: str | None) -> bool:
    if not token:
        return False
    row = fetchone("SELECT id FROM worker_pairings WHERE token_hash=? AND revoked=0", (_hash(str(token)),))
    if not row:
        return False
    execute("UPDATE worker_pairings SET last_used_at=? WHERE id=?", (now_iso(), row["id"]))
    return True


def revoke_token(token: str) -> bool:
    row = fetchone("SELECT id FROM worker_pairings WHERE token_hash=?", (_hash(str(token)),))
    if not row:
        return False
    execute("UPDATE worker_pairings SET revoked=1 WHERE id=?", (row["id"],))
    return True
