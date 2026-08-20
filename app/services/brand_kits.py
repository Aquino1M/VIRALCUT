from __future__ import annotations

import json
import uuid
from copy import deepcopy
from typing import Any

from app.db import execute, fetchall, fetchone, now_iso
from . import editor


def _decode(row) -> dict[str, Any] | None:
    if not row:
        return None
    d = dict(row)
    try:
        d["config"] = json.loads(d.pop("config_json") or "{}")
    except Exception:
        d["config"] = {}
    return d


def create_brand_kit(user_id: int, name: str, config: dict[str, Any]) -> dict[str, Any]:
    kit_id = uuid.uuid4().hex[:16]
    now = now_iso()
    execute("INSERT INTO brand_kits(id,user_id,name,config_json,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (kit_id, user_id, name.strip() or "Brand Kit", json.dumps(config or {}, ensure_ascii=False), now, now))
    return get_brand_kit(user_id, kit_id) or {}


def get_brand_kit(user_id: int, kit_id: str) -> dict[str, Any] | None:
    return _decode(fetchone("SELECT * FROM brand_kits WHERE id=? AND user_id=?", (kit_id, user_id)))


def update_brand_kit(user_id: int, kit_id: str, *, name: str | None = None, config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    current = get_brand_kit(user_id, kit_id)
    if not current:
        return None
    next_name = (str(name).strip() if name is not None else current["name"]) or current["name"]
    next_config = dict(config) if config is not None else dict(current.get("config") or {})
    execute("UPDATE brand_kits SET name=?,config_json=?,updated_at=? WHERE id=? AND user_id=?",
            (next_name, json.dumps(next_config, ensure_ascii=False), now_iso(), kit_id, user_id))
    return get_brand_kit(user_id, kit_id)


def list_brand_kits(user_id: int) -> list[dict[str, Any]]:
    return [_decode(r) for r in fetchall("SELECT * FROM brand_kits WHERE user_id=? ORDER BY updated_at DESC", (user_id,))]


def delete_brand_kit(user_id: int, kit_id: str) -> bool:
    if not get_brand_kit(user_id, kit_id):
        return False
    execute("DELETE FROM brand_kits WHERE id=? AND user_id=?", (kit_id, user_id))
    return True


def apply_brand_kit(user_id: int, kit_id: str, clip_ids: list[str], *, platform: str | None = None) -> dict[str, Any]:
    item = get_brand_kit(user_id, kit_id)
    if not item:
        return {"updated": 0, "clip_ids": [], "error": "brand_kit_not_found"}
    valid = {r["id"] for r in fetchall("SELECT c.id FROM clips c JOIN projects p ON p.id=c.project_id WHERE p.user_id=?", (user_id,))}
    ids = [str(x) for x in clip_ids if str(x) in valid]
    cfg = deepcopy(item.get("config") or {})
    platform = str(platform or "").strip() or None
    if platform:
        override=(cfg.get("platform_overrides") or {}).get(platform) if isinstance(cfg.get("platform_overrides"),dict) else None
        if isinstance(override,dict): cfg={**cfg,**deepcopy(override)}
    asset_ids = [str(x) for x in cfg.get("asset_ids") or []]
    assets = {}
    if asset_ids:
        placeholders = ",".join("?" for _ in asset_ids)
        for row in fetchall(f"SELECT * FROM brand_assets WHERE user_id=? AND id IN ({placeholders})", (user_id, *asset_ids)):
            assets[row["id"]] = dict(row)
    source_key = f"brand-kit:{kit_id}"
    for clip_id in ids:
        state = editor.get_or_create_edit_state(clip_id)
        cap = dict(state.get("caption_config") or {})
        if cfg.get("font_family"): cap["fontFamily"] = cfg["font_family"]
        if cfg.get("primary_color"): cap["primaryColor"] = cfg["primary_color"]
        if cfg.get("secondary_color"): cap["secondaryColor"] = cfg["secondary_color"]
        state["caption_config"] = cap
        overlays = [deepcopy(o) for o in (state.get("overlays") or []) if o.get("source") != source_key]
        y = 80
        for aid in asset_ids:
            asset = assets.get(aid)
            if not asset or not asset.get("file_path"):
                continue
            kind = asset.get("asset_type") if asset.get("asset_type") in {"logo", "watermark", "image"} else "image"
            overlays.append({
                "id": f"kit-{kit_id}-{aid}", "type": kind, "path": asset["file_path"], "x": 40, "y": y,
                "width": 240 if kind == "logo" else 180, "height": 140, "opacity": 0.92 if kind == "logo" else 0.65,
                "zIndex": 75, "source": source_key,
            })
            y += 155
        cta = str(cfg.get("cta_text") or "").strip()
        if cta:
            overlays.append({
                "id": f"kit-{kit_id}-cta", "type": "cta", "text": cta, "x": 70, "y": 1680, "width": 940, "height": 120,
                "background": cfg.get("primary_color") or "#6D28D9", "color": cfg.get("secondary_color") or "#FFFFFF",
                "fontFamily": cfg.get("font_family") or "Montserrat", "fontSize": 48, "zIndex": 78, "source": source_key,
            })
        state["overlays"] = overlays
        editor.save_edit_state(clip_id, state)
    return {"updated": len(ids), "clip_ids": ids, "brand_kit": item}


BRAND_KIT_EXPORT_VERSION = 2

def export_brand_kit(user_id: int, kit_id: str) -> dict[str, Any] | None:
    item=get_brand_kit(user_id,kit_id)
    if not item: return None
    # Assets are referenced by IDs and are intentionally not embedded as executable/blob data.
    return {"viralclip_brand_kit_version":BRAND_KIT_EXPORT_VERSION,"kind":"brand-kit","name":item["name"],"config":deepcopy(item.get("config") or {})}

def import_brand_kit(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    if str(payload.get("kind") or "brand-kit") != "brand-kit": raise ValueError("arquivo não é um Brand Kit")
    version=int(payload.get("viralclip_brand_kit_version") or 1)
    if version<1 or version>BRAND_KIT_EXPORT_VERSION: raise ValueError("versão de Brand Kit não suportada")
    config=deepcopy(payload.get("config") if isinstance(payload.get("config"),dict) else {})
    # Imported foreign asset IDs are removed; user can attach their local logos afterwards.
    config["asset_ids"]=[]
    return create_brand_kit(user_id,str(payload.get("name") or "Brand Kit importado"),config)
