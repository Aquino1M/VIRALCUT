from __future__ import annotations

import json
import uuid
from copy import deepcopy
from typing import Any

from app.db import execute, fetchall, fetchone, now_iso
from . import editor

ALLOWED_STATE_KEYS = {"caption_preset_id", "layout_preset_id", "caption_config", "layout_config", "overlays", "tracks", "aspect_ratio", "audio_config"}


def _decode(row) -> dict[str, Any] | None:
    if not row:
        return None
    d = dict(row)
    try:
        d["config"] = json.loads(d.pop("config_json") or "{}")
    except Exception:
        d["config"] = {}
    d["favorite"] = bool(d.get("favorite"))
    return d


def create_template(user_id: int, name: str, config: dict[str, Any], *, favorite: bool = False) -> dict[str, Any]:
    template_id = uuid.uuid4().hex[:16]
    now = now_iso()
    execute(
        "INSERT INTO studio_templates(id,user_id,name,config_json,favorite,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
        (template_id, user_id, name.strip() or "Template", json.dumps(config or {}, ensure_ascii=False), int(favorite), now, now),
    )
    return get_template(user_id, template_id) or {}


def get_template(user_id: int, template_id: str) -> dict[str, Any] | None:
    return _decode(fetchone("SELECT * FROM studio_templates WHERE id=? AND user_id=?", (template_id, user_id)))


def list_templates(user_id: int) -> list[dict[str, Any]]:
    return [_decode(r) for r in fetchall("SELECT * FROM studio_templates WHERE user_id=? ORDER BY favorite DESC,updated_at DESC", (user_id,))]


def delete_template(user_id: int, template_id: str) -> bool:
    if not get_template(user_id, template_id):
        return False
    execute("DELETE FROM studio_templates WHERE id=? AND user_id=?", (template_id, user_id))
    return True


def duplicate_template(user_id: int, template_id: str) -> dict[str, Any] | None:
    item = get_template(user_id, template_id)
    if not item:
        return None
    return create_template(user_id, f"{item['name']} (cópia)", deepcopy(item["config"]), favorite=False)


def apply_template(user_id: int, template_id: str, clip_ids: list[str]) -> dict[str, Any]:
    item = get_template(user_id, template_id)
    if not item:
        return {"updated": 0, "clip_ids": [], "error": "template_not_found"}
    valid = {r["id"] for r in fetchall(
        "SELECT c.id FROM clips c JOIN projects p ON p.id=c.project_id WHERE p.user_id=?", (user_id,)
    )}
    ids = [str(x) for x in clip_ids if str(x) in valid]
    cfg = item.get("config") or {}
    state_patch = {k: deepcopy(v) for k, v in cfg.items() if k in ALLOWED_STATE_KEYS}
    for clip_id in ids:
        state = editor.get_or_create_edit_state(clip_id)
        for key, value in state_patch.items():
            if key in {"caption_config", "layout_config"}:
                state[key] = {**(state.get(key) or {}), **(value or {})}
            else:
                state[key] = deepcopy(value)
        editor.save_edit_state(clip_id, state)
    return {"updated": len(ids), "clip_ids": ids, "template": item, "auto_edit": cfg.get("auto_edit") or {}}


TEMPLATE_EXPORT_VERSION = 4

def export_template(user_id: int, template_id: str) -> dict[str, Any] | None:
    item=get_template(user_id,template_id)
    if not item: return None
    return {
        "viralclip_template_version": TEMPLATE_EXPORT_VERSION,
        "kind":"studio-template",
        "name":item["name"],
        "favorite":bool(item.get("favorite")),
        "config":deepcopy(item.get("config") or {}),
    }

def import_template(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    if str(payload.get("kind") or "studio-template") != "studio-template":
        raise ValueError("arquivo não é um Studio Template")
    version=int(payload.get("viralclip_template_version") or 1)
    if version < 1 or version > TEMPLATE_EXPORT_VERSION:
        raise ValueError("versão de template não suportada")
    config=payload.get("config") if isinstance(payload.get("config"),dict) else {}
    safe={k:deepcopy(v) for k,v in config.items() if k in ALLOWED_STATE_KEYS or k=="auto_edit"}
    return create_template(user_id,str(payload.get("name") or "Template importado"),safe,favorite=bool(payload.get("favorite")))
