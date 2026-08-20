from __future__ import annotations

from fastapi import Request

from .db import fetchone


def current_user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return fetchone("SELECT id,email,plan,credits,is_admin,created_at,performance_mode,compute_mode FROM users WHERE id=?", (user_id,))


def require_user(request: Request):
    return current_user(request)
