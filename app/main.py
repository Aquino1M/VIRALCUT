from __future__ import annotations

import json
import math
import re
import shutil
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.cors import CORSMiddleware

from .auth import current_user
from .config import APP_NAME, BASE_DIR, MAX_UPLOAD_MB, OUTPUT_DIR, SECRET_KEY, TEMP_DIR, THUMB_DIR, WORKER_ALLOWED_ORIGINS
from .db import execute, fetchall, fetchone, hash_password, init_db, now_iso, verify_password
from .services import captions as caption_engine
from .services import editor as editor_service
from .services import fonts as font_service
from .services import face_tracking
from .services import layouts as layout_service
from .services import projects as project_service
from .services import preview as preview_service
from .services import proxy_media as proxy_media_service
from .services.jobs import submit
from .services import jobs as project_jobs
from .services.render import generate_thumbnail, render_edited_clip, render_clean_clip, resolve_output_geometry
from .services import render_queue
from .services import api_v1 as api_v1_service
from .services import auto_edit as auto_edit_service
from .services import assets as asset_service
from .services import timeline as timeline_service
from .services import hardware as hardware_service
from .services import job_store as job_store_service
from .services import worker_pairing as worker_pairing_service
from .services import quality_check as quality_check_service
from .services import studio_templates as studio_template_service
from .services import brand_kits as brand_kit_service
from .services import publishing as publishing_service
from .services import viral_score as viral_score_service
from .services import performance as performance_service
from .services import waveform as waveform_service
from .services import compute as compute_service
from .services import cloud_client as cloud_client_service
from .services import semantic_search as semantic_search_service
from .services import revisions as revision_service
from .services import prompt_edit as prompt_edit_service
from .services import creator_intelligence as creator_intelligence_service
from .services import media_analysis as media_analysis_service


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    render_queue.recover_interrupted_renders()
    job_store_service.recover_stale_jobs(stale_after_seconds=120)
    for project_id in project_jobs.recover_interrupted_projects():
        submit(project_id)
    yield


app = FastAPI(title=APP_NAME, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax", https_only=False)
if WORKER_ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=WORKER_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")


def render(request: Request, template: str, **ctx):
    context = {"request": request, "app_name": APP_NAME, "user": current_user(request), **ctx}
    return templates.TemplateResponse(request=request, name=template, context=context)


def require_login(request: Request):
    user = current_user(request)
    if not user:
        return None, RedirectResponse("/login", status_code=303)
    return user, None


def _is_admin(user) -> bool:
    return bool(user and user["is_admin"])


def require_admin(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return None, redirect
    if not _is_admin(user):
        return None, HTMLResponse("Acesso exclusivo do administrador", status_code=403)
    return user, None


def _owned_clip(user_id: int, clip_id: str):
    return fetchone(
        "SELECT c.*,p.user_id,p.source_path,p.transcript_path,p.settings_json,p.tracking_path,p.tracking_summary_json,p.title project_title FROM clips c JOIN projects p ON p.id=c.project_id WHERE c.id=? AND p.user_id=?",
        (clip_id, user_id),
    )


def _owned_project(user_id: int, project_id: str):
    return fetchone("SELECT * FROM projects WHERE id=? AND user_id=?", (project_id, user_id))


def _safe_filename(value: str, fallback: str = "clip") -> str:
    value = re.sub(r"[^\w\-. ]+", "", value or "", flags=re.UNICODE).strip().replace(" ", "_")
    return (value[:80] or fallback).strip("._") or fallback


def _settings(row) -> dict[str, Any]:
    try:
        return json.loads(row["settings_json"] or "{}")
    except Exception:
        return {}


def _geometry_labels(settings: dict[str, Any]) -> dict[str, str]:
    ratio = str((settings or {}).get("aspect_ratio") or "9:16")
    w, h = resolve_output_geometry(ratio, preview=False)
    pw, ph = resolve_output_geometry(ratio, preview=True)
    return {
        "output_resolution": f"{w}×{h}",
        "preview_resolution": f"{pw}×{ph}",
        "aspect_css": f"{w}/{h}",
    }


def _clip_editor_revision(clip_id: str) -> int:
    row = fetchone("SELECT revision FROM clip_edits WHERE clip_id=?", (clip_id,))
    return int(row["revision"] if row and row["revision"] is not None else 1)


def _current_clip_render(clip_id: str, revision: int, kinds: tuple[str, ...] = ("final", "project_preview")) -> dict[str, Any] | None:
    rows = fetchall(
        "SELECT * FROM clip_renders WHERE clip_id=? AND status='done' AND editor_revision=? ORDER BY created_at DESC",
        (clip_id, int(revision)),
    )
    for kind in kinds:
        for row in rows:
            path = row["video_path"]
            if row["kind"] == kind and path and Path(path).exists() and Path(path).stat().st_size > 0:
                return dict(row)
    return None


def _decorate_clip_preview(clip: dict[str, Any]) -> dict[str, Any]:
    revision = _clip_editor_revision(clip["id"])
    current = _current_clip_render(clip["id"], revision)
    state = editor_service.get_or_create_edit_state(clip["id"])
    w, h = resolve_output_geometry(str(state.get("aspect_ratio") or "9:16"), preview=False)
    legacy = revision <= 1 and any(
        path and Path(path).exists() and Path(path).stat().st_size > 0
        for path in (clip.get("preview_path"), clip.get("video_path"))
    )
    clip.update({"editor_revision": revision, "aspect_css": f"{w}/{h}", "preview_stale": current is None and not legacy})
    return clip


def _clip_analysis(row) -> dict[str, Any]:
    try:
        current = json.loads(row["analysis_json"] or "{}")
    except Exception:
        current = {}
    if current.get("version") == 2 and isinstance(current.get("breakdown"), dict):
        return current
    payload = {
        "title": row["title"] or "",
        "hook": row["hook"] or "",
        "reason": row["reason"] or "",
        "duration": max(0.0, float(row["end_time"] or 0) - float(row["start_time"] or 0)),
        "score": float(row["score"] or 0),
    }
    current = viral_score_service.score_clip_payload(payload)
    execute("UPDATE clips SET analysis_json=?,updated_at=? WHERE id=?", (json.dumps(current, ensure_ascii=False), now_iso(), row["id"]))
    return current


def _clip_workflow_status(clip_id: str, has_video: bool) -> str:
    render = fetchone("SELECT status FROM clip_renders WHERE clip_id=? ORDER BY created_at DESC LIMIT 1", (clip_id,))
    publish = fetchone("SELECT status FROM publish_queue WHERE clip_id=? ORDER BY created_at DESC LIMIT 1", (clip_id,))
    rstatus = str(render["status"] or "") if render else ""
    pstatus = str(publish["status"] or "") if publish else ""
    if rstatus == "error" or pstatus == "error":
        return "error"
    if pstatus == "published":
        return "published"
    if pstatus == "scheduled":
        return "scheduled"
    if rstatus in {"queued", "rendering"}:
        return "rendering"
    if has_video or rstatus == "done":
        return "rendered"
    return "ready"


def _initial_cues(clip) -> list[dict[str, Any]]:
    cues = editor_service.list_caption_cues(clip["id"])
    if cues:
        return cues
    transcript_path = clip["transcript_path"]
    if transcript_path and Path(transcript_path).exists():
        try:
            transcript = json.loads(Path(transcript_path).read_text(encoding="utf-8"))
            cues = caption_engine.cues_from_transcript(transcript, float(clip["start_time"]), float(clip["end_time"]))
            if cues:
                return editor_service.replace_caption_cues(clip["id"], cues)
        except Exception:
            pass
    return []


@app.get("/sw.js")
def service_worker():
    path = BASE_DIR / "app" / "static" / "sw.js"
    return FileResponse(path, media_type="application/javascript", headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.get("/font-css")
def font_css():
    return Response(font_service.browser_font_css(), media_type="text/css")


@app.get("/font-files/{filename}")
def font_file(filename: str):
    path = font_service.allowed_local_font(filename)
    if not path:
        return HTMLResponse("Fonte não encontrada", status_code=404)
    return FileResponse(path, media_type="font/ttf")


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    if current_user(request):
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, "landing.html")


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return render(request, "auth.html", mode="register", error=None)


@app.post("/register")
def register(request: Request, email: str = Form(...), password: str = Form(...)):
    email = email.strip().lower()
    if len(password) < 6:
        return render(request, "auth.html", mode="register", error="Use uma senha com pelo menos 6 caracteres.")
    if fetchone("SELECT id FROM users WHERE email=?", (email,)):
        return render(request, "auth.html", mode="register", error="Esse e-mail já está cadastrado.")
    execute(
        "INSERT INTO users(email,password_hash,is_admin,created_at) "
        "VALUES(?,?,CASE WHEN EXISTS(SELECT 1 FROM users) THEN 0 ELSE 1 END,?)",
        (email, hash_password(password), now_iso()),
    )
    user = fetchone("SELECT id FROM users WHERE email=?", (email,))
    request.session["user_id"] = user["id"]
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "auth.html", mode="login", error=None)


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    row = fetchone("SELECT * FROM users WHERE email=?", (email.strip().lower(),))
    if not row or not verify_password(password, row["password_hash"]):
        return render(request, "auth.html", mode="login", error="E-mail ou senha inválidos.")
    request.session["user_id"] = row["id"]
    hardware_service.load_or_build_profile()
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request, q: str = Query(""), status: str = Query("all"),
    sort: str = Query("recent"), page: int = Query(1), page_size: int = Query(12),
):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    stats = {
        "projects": fetchone("SELECT COUNT(*) n FROM projects WHERE user_id=?", (user["id"],))["n"],
        "done": fetchone("SELECT COUNT(*) n FROM projects WHERE user_id=? AND status='done'", (user["id"],))["n"],
        "clips": fetchone("SELECT COUNT(*) n FROM clips c JOIN projects p ON p.id=c.project_id WHERE p.user_id=?", (user["id"],))["n"],
    }
    where=["p.user_id=?"]; params: list[Any]=[user["id"]]
    if q.strip():
        where.append("(LOWER(p.title) LIKE ? OR LOWER(COALESCE(p.source_value,'')) LIKE ?)")
        like=f"%{q.strip().lower()}%"; params.extend([like,like])
    allowed_status={"queued","processing","done","error"}
    if status in allowed_status:
        where.append("p.status=?"); params.append(status)
    order={
        "recent":"p.created_at DESC", "oldest":"p.created_at ASC", "title":"LOWER(p.title) ASC",
        "duration":"COALESCE(p.duration,0) DESC", "progress":"p.progress DESC",
    }.get(sort,"p.created_at DESC")
    page_size=max(6,min(48,int(page_size or 12))); page=max(1,int(page or 1))
    where_sql=" AND ".join(where)
    total=fetchone(f"SELECT COUNT(*) n FROM projects p WHERE {where_sql}",params)["n"]
    pages=max(1,math.ceil(total/page_size)); page=min(page,pages)
    rows=fetchall(
        f"""SELECT p.*, (SELECT COUNT(*) FROM clips c WHERE c.project_id=p.id) clip_count
            FROM projects p WHERE {where_sql} ORDER BY {order} LIMIT ? OFFSET ?""",
        (*params,page_size,(page-1)*page_size),
    )
    projects=[]
    for row in rows:
        item=dict(row)
        try: item["compute_summary"]=json.loads(item.get("compute_summary_json") or "{}")
        except Exception: item["compute_summary"]={}
        projects.append(item)
    return render(request, "dashboard.html", projects=projects, stats=stats, q=q, status=status, sort=sort, page=page, page_size=page_size, pages=pages, total=total)


@app.get("/videos", response_class=HTMLResponse)
def videos_page(request: Request, project_id: str = Query("")):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    projects = [dict(row) for row in fetchall(
        "SELECT id,title FROM projects WHERE user_id=? ORDER BY created_at DESC", (user["id"],)
    )]
    selected = project_id if any(p["id"] == project_id for p in projects) else ""
    where = "p.user_id=?" + (" AND p.id=?" if selected else "")
    params = (user["id"], selected) if selected else (user["id"],)
    rows = fetchall(
        f"""SELECT c.*, p.title project_title, p.id project_id
            FROM clips c JOIN projects p ON p.id=c.project_id
            WHERE {where} ORDER BY c.created_at DESC LIMIT 200""",
        params,
    )
    clips = []
    for row in rows:
        item = dict(row)
        item["analysis"] = _clip_analysis(row)
        item["workflow_status"] = _clip_workflow_status(row["id"], bool(row["video_path"]))
        clips.append(item)
    return render(request, "videos.html", clips=clips, projects=projects, selected_project_id=selected)


@app.get("/library", response_class=HTMLResponse)
def library_page(request: Request, q: str = Query(""), kind: str = Query("")):
    user, redirect = require_admin(request)
    if redirect:
        return redirect
    status = asset_service.starter_pack_status()
    if q.strip():
        assets = asset_service.search_assets(q.strip(), kind=kind or None, limit=80)
    else:
        assets = asset_service.scan_assets()[:120]
        if kind:
            assets = [a for a in assets if a.get("kind") == kind]
    return render(request, "library.html", asset_status=status, assets=assets, q=q, kind=kind)


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    user, redirect = require_admin(request)
    if redirect:
        return redirect
    users = [dict(row) for row in fetchall(
        "SELECT id,email,is_admin,compute_mode,created_at FROM users ORDER BY is_admin DESC,created_at"
    )]
    return render(request, "admin.html", users=users)


@app.post("/admin/users/{user_id}/processing-mode")
def admin_processing_mode(request: Request, user_id: int, mode: str = Form("auto")):
    admin, redirect = require_admin(request)
    if redirect:
        return redirect
    if mode not in {"auto", "local", "cloud"}:
        return HTMLResponse("Modo de processamento inválido", status_code=400)
    if not fetchone("SELECT id FROM users WHERE id=?", (user_id,)):
        return HTMLResponse("Usuário não encontrado", status_code=404)
    execute("UPDATE users SET compute_mode=? WHERE id=?", (mode, user_id))
    return RedirectResponse("/admin", status_code=303)


@app.get("/templates", response_class=HTMLResponse)
def templates_page(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    layouts = layout_service.list_layout_presets()
    for item in layouts:
        item["panels"] = layout_service.layout_preview_panels(item["id"])
    return render(
        request,
        "templates.html",
        layout_presets=layouts,
        caption_presets=caption_engine.list_caption_presets(),
        auto_styles=auto_edit_service.STYLE_HINTS,
        auto_intensities=auto_edit_service.INTENSITY,
        saved_templates=studio_template_service.list_templates(user["id"]),
    )


@app.get("/brand-kit", response_class=HTMLResponse)
def brand_kit_page(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    rows = fetchall("SELECT * FROM brand_assets WHERE user_id=? ORDER BY created_at DESC", (user["id"],))
    return render(
        request, "brand_kit.html", brand_assets=[dict(r) for r in rows],
        brand_kits=brand_kit_service.list_brand_kits(user["id"]), fonts=font_service.list_fonts(),
    )


@app.get("/publish", response_class=HTMLResponse)
def publish_page(request: Request, status: str = Query("")):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    items = publishing_service.list_items(user["id"], status=status or None)
    clips = fetchall(
        "SELECT c.id,c.title,c.video_path,p.title project_title FROM clips c JOIN projects p ON p.id=c.project_id WHERE p.user_id=? ORDER BY c.created_at DESC LIMIT 250",
        (user["id"],),
    )
    return render(request, "publish.html", items=items, clips=[dict(x) for x in clips], platforms=sorted(publishing_service.PLATFORMS), status_filter=status)


@app.get("/analytics", response_class=HTMLResponse)
def analytics_page(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    rows = [dict(r) for r in fetchall(
        "SELECT c.*,p.title project_title FROM clips c JOIN projects p ON p.id=c.project_id WHERE p.user_id=? ORDER BY c.score DESC,c.created_at DESC",
        (user["id"],),
    )]
    scores = []
    for row in rows:
        try:
            analysis = json.loads(row.get("analysis_json") or "{}")
        except Exception:
            analysis = {}
        score = float(analysis.get("score") or (float(row.get("score") or 0) * 10))
        scores.append(max(0.0, min(100.0, score)))
        row["viral_score"] = round(score)
    publish_counts = {r["status"]: r["n"] for r in fetchall("SELECT status,COUNT(*) n FROM publish_queue WHERE user_id=? GROUP BY status", (user["id"],))}
    encoders = [dict(r) for r in fetchall(
        "SELECT COALESCE(c.render_encoder,'-') encoder,COUNT(*) n FROM clips c JOIN projects p ON p.id=c.project_id WHERE p.user_id=? AND c.video_path IS NOT NULL GROUP BY c.render_encoder ORDER BY n DESC",
        (user["id"],),
    )]
    stats = {
        "projects": fetchone("SELECT COUNT(*) n FROM projects WHERE user_id=?", (user["id"],))["n"],
        "clips": len(rows),
        "rendered": sum(1 for r in rows if r.get("video_path")),
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "avg_render_seconds": round(sum(float(r.get("render_seconds") or 0) for r in rows if r.get("render_seconds")) / max(1, sum(1 for r in rows if r.get("render_seconds"))), 1),
    }
    creator_profile = creator_intelligence_service.creator_profile(user["id"])
    return render(request, "analytics.html", stats=stats, top_clips=rows[:12], publish_counts=publish_counts, encoders=encoders, creator_profile=creator_profile)


@app.get("/api/v1/templates")
def api_v1_templates(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return {"items": studio_template_service.list_templates(user["id"])}


@app.post("/api/v1/templates")
def api_v1_create_template(request: Request, payload: dict[str, Any] = Body(...)):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return studio_template_service.create_template(user["id"], str(payload.get("name") or "Template"), payload.get("config") if isinstance(payload.get("config"), dict) else {}, favorite=bool(payload.get("favorite")))


@app.post("/api/v1/templates/{template_id}/apply")
def api_v1_apply_template(request: Request, template_id: str, payload: dict[str, Any] = Body(default={})):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    result = studio_template_service.apply_template(user["id"], template_id, [str(x) for x in payload.get("clip_ids") or []])
    if result.get("error"):
        return JSONResponse(result, status_code=404)
    return result


@app.post("/api/v1/templates/{template_id}/duplicate")
def api_v1_duplicate_template(request: Request, template_id: str):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    item = studio_template_service.duplicate_template(user["id"], template_id)
    return item if item else JSONResponse({"error": "not_found"}, status_code=404)


@app.delete("/api/v1/templates/{template_id}")
def api_v1_delete_template(request: Request, template_id: str):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return {"deleted": studio_template_service.delete_template(user["id"], template_id)}


@app.get("/api/v1/brand-kits")
def api_v1_brand_kits(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return {"items": brand_kit_service.list_brand_kits(user["id"])}


@app.post("/api/v1/brand-kits")
def api_v1_create_brand_kit(request: Request, payload: dict[str, Any] = Body(...)):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return brand_kit_service.create_brand_kit(user["id"], str(payload.get("name") or "Brand Kit"), payload.get("config") if isinstance(payload.get("config"), dict) else {})


@app.put("/api/v1/brand-kits/{kit_id}")
def api_v1_update_brand_kit(request: Request, kit_id: str, payload: dict[str, Any] = Body(...)):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    item = brand_kit_service.update_brand_kit(user["id"], kit_id, name=payload.get("name"), config=payload.get("config") if isinstance(payload.get("config"), dict) else None)
    return item if item else JSONResponse({"error": "not_found"}, status_code=404)


@app.post("/api/v1/brand-kits/{kit_id}/apply")
def api_v1_apply_brand_kit(request: Request, kit_id: str, payload: dict[str, Any] = Body(default={})):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    result = brand_kit_service.apply_brand_kit(user["id"], kit_id, [str(x) for x in payload.get("clip_ids") or []], platform=str(payload.get("platform") or "") or None)
    if result.get("error"):
        return JSONResponse(result, status_code=404)
    return result


@app.delete("/api/v1/brand-kits/{kit_id}")
def api_v1_delete_brand_kit(request: Request, kit_id: str):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return {"deleted": brand_kit_service.delete_brand_kit(user["id"], kit_id)}


@app.get("/api/v1/publish")
def api_v1_publish_list(request: Request, status: str = Query("")):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return {"items": publishing_service.list_items(user["id"], status=status or None)}


@app.post("/api/v1/publish")
def api_v1_publish_create(request: Request, payload: dict[str, Any] = Body(...)):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        return publishing_service.enqueue(
            user["id"], str(payload.get("clip_id") or ""), platform=str(payload.get("platform") or ""),
            scheduled_at=str(payload.get("scheduled_at") or "").strip() or None, caption=str(payload.get("caption") or ""),
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/api/v1/publish/{item_id}/status")
def api_v1_publish_status(request: Request, item_id: str, payload: dict[str, Any] = Body(...)):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        item = publishing_service.update_status(user["id"], item_id, str(payload.get("status") or ""), external_url=payload.get("external_url"), error_message=payload.get("error_message"))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return item if item else JSONResponse({"error": "not_found"}, status_code=404)


@app.get("/hardware", response_class=HTMLResponse)
def hardware_page(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    capabilities = hardware_service.load_or_build_profile()
    performance = performance_service.resolve_mode(capabilities, user["performance_mode"] or "auto")
    return render(
        request, "hardware.html", capabilities=capabilities, performance=performance,
        performance_override=user["performance_mode"] or "auto", pair_code=worker_pairing_service.current_pair_code(),
    )


@app.post("/api/v1/performance-mode")
def api_v1_performance_mode(request: Request, payload: dict[str, Any] = Body(...)):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    execute("UPDATE users SET performance_mode='auto' WHERE id=?", (user["id"],))
    policy = performance_service.resolve_mode(hardware_service.load_or_build_profile(), "auto")
    return {"mode": "auto", "resolved_mode": policy["mode"], "policy": policy}


@app.get("/projects/new", response_class=HTMLResponse)
def new_project(request: Request, url: str = Query("")):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    profiles = fetchall("SELECT * FROM creator_profiles WHERE user_id=? ORDER BY created_at DESC", (user["id"],))
    layout_presets = layout_service.list_layout_presets()
    for item in layout_presets:
        item["panels"] = layout_service.layout_preview_panels(item["id"])
    return render(
        request,
        "new_project.html",
        profiles=profiles,
        max_upload_mb=MAX_UPLOAD_MB,
        caption_presets=caption_engine.list_caption_presets(),
        layout_presets=layout_presets,
        fonts=font_service.list_fonts(),
        source_url_prefill=url.strip(),
    )


@app.post("/projects")
async def create_project(
    request: Request,
    title: str = Form("Novo projeto"),
    source_url: str = Form(""),
    upload: UploadFile | None = File(None),
    mode: str = Form("smart"),
    num_clips: int = Form(5),
    min_duration: float = Form(20),
    max_duration: float = Form(90),
    target_duration: float = Form(60),
    manual_ranges: str = Form(""),
    crop_style: str = Form("smart"),
    caption_style: str = Form("green-fresh"),
    caption_preset_id: str = Form("green-fresh"),
    layout_preset_id: str = Form("auto"),
    caption_font: str = Form("Bangers"),
    aspect_ratio: str = Form("9:16"),
    prompt: str = Form(""),
    captions: str | None = Form(None),
    emojis: str | None = Form(None),
    use_llm: str | None = Form(None),
    cta_enabled: str | None = Form(None),
    auto_edit_enabled: str | None = Form(None),
    auto_edit_style: str = Form("podcast-viral"),
    auto_edit_intensity: str = Form("normal"),
    language: str = Form(""),
    custom_keywords: str = Form(""),
    profile_id: str = Form(""),
    youtube_cookies: str = Form(""),
    start_range: float = Form(0),
    end_range: float = Form(0),
):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    project_id = uuid.uuid4().hex[:16]
    source_type: str | None = None
    source_value: str | None = None
    source_path: str | None = None

    if upload and upload.filename:
        if not project_service.validate_upload_filename(upload.filename):
            return HTMLResponse("Formato inválido. Use MP4, MOV, MKV ou AVI.", status_code=400)
        suffix = Path(upload.filename).suffix.lower()
        save_dir = BASE_DIR / "data" / "uploads" / project_id
        save_dir.mkdir(parents=True, exist_ok=True)
        path = save_dir / f"upload{suffix}"
        total = 0
        with path.open("wb") as f:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_MB * 1024 * 1024:
                    path.unlink(missing_ok=True)
                    return HTMLResponse("Arquivo excede o limite configurado.", status_code=413)
                f.write(chunk)
        source_type, source_path = "upload", str(path)
    elif source_url.strip():
        source_value = source_url.strip()
        source_type = project_service.classify_source_url(source_value)
    else:
        return RedirectResponse("/projects/new?error=source", status_code=303)

    if profile_id:
        prof = fetchone("SELECT * FROM creator_profiles WHERE id=? AND user_id=?", (profile_id, user["id"]))
        if prof:
            min_duration = float(prof["preferred_min"])
            max_duration = float(prof["preferred_max"])
            custom_keywords = ",".join(filter(None, [custom_keywords, prof["keywords"]]))

    settings = project_service.normalize_project_settings({
        "prompt": prompt,
        "num_clips": num_clips,
        "min_duration": min_duration,
        "max_duration": max_duration,
        "target_duration": target_duration,
        "manual_ranges": manual_ranges,
        "crop_style": crop_style,
        "captions": captions == "on",
        "caption_style": caption_style,
        "caption_preset_id": caption_preset_id,
        "layout_preset_id": layout_preset_id,
        "caption_font": caption_font,
        "aspect_ratio": aspect_ratio,
        "emojis": emojis == "on",
        "use_llm": use_llm == "on",
        "cta_enabled": cta_enabled == "on",
        "auto_edit_enabled": auto_edit_enabled == "on",
        "auto_edit_style": auto_edit_style,
        "auto_edit_intensity": auto_edit_intensity,
        "language": language,
        "custom_keywords": custom_keywords,
        "youtube_cookies": youtube_cookies,
        "start_range": start_range,
        "end_range": end_range,
    })
    now = now_iso()
    execute(
        "INSERT INTO projects(id,user_id,title,source_type,source_value,source_path,mode,status,progress,message,settings_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (project_id, user["id"], title.strip() or "Novo projeto", source_type, source_value, source_path, mode, "queued", 0, "Na fila", json.dumps(settings, ensure_ascii=False), now, now),
    )
    submit(project_id)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@app.get("/projects/{project_id}", response_class=HTMLResponse)
def project_page(
    request: Request,
    project_id: str,
    sort: str = Query("score"),
    filter: str = Query("all"),
    page_size: int = Query(0),
    page: int = Query(1),
):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    project = _owned_project(user["id"], project_id)
    if not project:
        return HTMLResponse("Projeto não encontrado", status_code=404)
    performance = performance_service.resolve_mode(hardware_service.load_or_build_profile(), user["performance_mode"] or "auto")
    size = project_service.page_size(page_size or int(performance["card_page_size"]))
    page = max(1, int(page))
    where = ["project_id=?"]
    params: list[Any] = [project_id]
    if filter == "rendered":
        where.append("video_path IS NOT NULL")
    elif filter == "not_rendered":
        where.append("video_path IS NULL")
    elif filter == "ready":
        where.append("video_path IS NULL")
        where.append("NOT EXISTS (SELECT 1 FROM clip_renders r WHERE r.clip_id=clips.id AND r.status IN ('queued','rendering','error'))")
        where.append("NOT EXISTS (SELECT 1 FROM publish_queue q WHERE q.clip_id=clips.id AND q.status IN ('scheduled','published','error'))")
    elif filter == "rendering":
        where.append("EXISTS (SELECT 1 FROM clip_renders r WHERE r.clip_id=clips.id AND r.status IN ('queued','rendering'))")
    elif filter == "scheduled":
        where.append("EXISTS (SELECT 1 FROM publish_queue q WHERE q.clip_id=clips.id AND q.status='scheduled')")
    elif filter == "published":
        where.append("EXISTS (SELECT 1 FROM publish_queue q WHERE q.clip_id=clips.id AND q.status='published')")
    elif filter == "error":
        where.append("(EXISTS (SELECT 1 FROM clip_renders r WHERE r.clip_id=clips.id AND r.status='error') OR EXISTS (SELECT 1 FROM publish_queue q WHERE q.clip_id=clips.id AND q.status='error'))")
    where_sql = " AND ".join(where)
    total = fetchone(f"SELECT COUNT(*) n FROM clips WHERE {where_sql}", params)["n"]
    pages = max(1, math.ceil(total / size))
    page = min(page, pages)
    clip_rows = fetchall(
        f"SELECT * FROM clips WHERE {where_sql} ORDER BY {project_service.sort_sql(sort)} LIMIT ? OFFSET ?",
        (*params, size, (page - 1) * size),
    )
    clips = []
    for row in clip_rows:
        item = _decorate_clip_preview(dict(row))
        item["analysis"] = _clip_analysis(row)
        item["workflow_status"] = _clip_workflow_status(row["id"], bool(row["video_path"]))
        duration=max(0.0,float(row["end_time"] or 0)-float(row["start_time"] or 0))
        base_v3=viral_score_service.score_clip_payload_v3({
            "title":row["title"],"hook":row["hook"],"reason":row["reason"],"duration":duration,"score":row["score"],
            "text":item["analysis"].get("text") or "",
        })
        calibration=creator_intelligence_service.calibrate_score(user["id"],base_v3["score"],duration=duration)
        item["viral_v3"]=viral_score_service.score_clip_payload_v3({
            "title":row["title"],"hook":row["hook"],"reason":row["reason"],"duration":duration,"score":row["score"],
            "text":item["analysis"].get("text") or "",
        },creator_calibration=calibration)
        clips.append(item)
    all_ids = [r["id"] for r in fetchall(f"SELECT id FROM clips WHERE {where_sql} ORDER BY {project_service.sort_sql(sort)}", params)]
    try:
        project_compute_summary=json.loads(project["compute_summary_json"] or "{}")
    except Exception:
        project_compute_summary={}
    return render(
        request,
        "project.html",
        project=project,
        project_compute_summary=project_compute_summary,
        worker_job=job_store_service.latest_job("project", project_id),
        clips=clips,
        settings=_settings(project),
        **_geometry_labels(_settings(project)),
        total=total,
        pages=pages,
        page=page,
        page_size=size,
        sort=sort,
        filter=filter,
        all_ids=all_ids,
        caption_presets=caption_engine.list_caption_presets(),
        layout_presets=layout_service.list_layout_presets(),
        fonts=font_service.list_fonts(),
        studio_templates=studio_template_service.list_templates(user["id"]),
        brand_kits=brand_kit_service.list_brand_kits(user["id"]),
        performance=performance,
    )


@app.post("/api/v1/projects/{project_id}/command")
def api_v1_project_command(request: Request, project_id: str, payload: dict[str, Any] = Body(...)):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not _owned_project(user["id"], project_id):
        return JSONResponse({"error": "not_found"}, status_code=404)
    valid = {r["id"] for r in fetchall("SELECT id FROM clips WHERE project_id=?", (project_id,))}
    ids = [str(x) for x in payload.get("clip_ids") or [] if str(x) in valid]
    result = {"selected": len(ids), "template_updated": 0, "brand_kit_updated": 0, "director_updated": 0, "render_queued": 0, "render_ids": []}
    template_id = str(payload.get("template_id") or "").strip()
    if template_id:
        applied = studio_template_service.apply_template(user["id"], template_id, ids)
        if applied.get("error"):
            return JSONResponse({"error": applied["error"]}, status_code=404)
        result["template_updated"] = int(applied.get("updated") or 0)
    kit_id = str(payload.get("brand_kit_id") or "").strip()
    if kit_id:
        applied = brand_kit_service.apply_brand_kit(user["id"], kit_id, ids)
        if applied.get("error"):
            return JSONResponse({"error": applied["error"]}, status_code=404)
        result["brand_kit_updated"] = int(applied.get("updated") or 0)
    if payload.get("auto_director"):
        for clip_id in ids:
            auto_edit_service.build_auto_edit_plan(
                clip_id, style=str(payload.get("style") or "podcast-viral"),
                intensity=str(payload.get("intensity") or "normal"), options={"director": True, "broll": bool(payload.get("broll", True)), "sfx": True, "effects": True, "filters": True, "music": True},
            )
            result["director_updated"] += 1
    if payload.get("render"):
        for clip_id in ids:
            render_id = render_queue.enqueue_clip_render(clip_id, "final")
            result["render_ids"].append(render_id)
        result["render_queued"] = len(result["render_ids"])
    return result


@app.get("/api/projects/{project_id}")
def project_status(request: Request, project_id: str):
    user = current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    p = fetchone("SELECT id,status,progress,message FROM projects WHERE id=? AND user_id=?", (project_id, user["id"]))
    if not p:
        return JSONResponse({"error": "not_found"}, status_code=404)
    clips = fetchone("SELECT COUNT(*) n FROM clips WHERE project_id=?", (project_id,))["n"]
    worker = job_store_service.latest_job("project", project_id)
    return {"id": p["id"], "status": p["status"], "progress": p["progress"], "message": p["message"], "clips": clips, "worker": worker}


@app.post("/projects/{project_id}/retry")
def retry_project(request: Request, project_id: str):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    project = _owned_project(user["id"], project_id)
    if not project:
        return HTMLResponse("Projeto não encontrado", status_code=404)
    if project["status"] in {"queued", "processing"}:
        return RedirectResponse(f"/projects/{project_id}", status_code=303)

    # Remove only generated/retryable state. The original upload (when present)
    # lives under data/uploads and remains untouched. Remote sources are fetched
    # again from source_value.
    execute("DELETE FROM clips WHERE project_id=?", (project_id,))
    shutil.rmtree(OUTPUT_DIR / project_id, ignore_errors=True)
    shutil.rmtree(TEMP_DIR / project_id, ignore_errors=True)
    now = now_iso()
    execute(
        "UPDATE projects SET status='queued',progress=0,message='Na fila para reprocessar',"
        "transcript_path=NULL,tracking_path=NULL,tracking_summary_json='{}',updated_at=? WHERE id=?",
        (now, project_id),
    )
    submit(project_id)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@app.post("/projects/{project_id}/defaults")
def update_project_defaults(request: Request, project_id: str, payload: dict[str, Any] = Body(...)):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    project = _owned_project(user["id"], project_id)
    if not project:
        return JSONResponse({"error": "not_found"}, status_code=404)
    current = _settings(project)
    allowed = {
        "prompt", "goal", "num_clips", "min_duration", "max_duration", "target_duration",
        "clip_duration_policy", "start_range", "end_range", "language", "target_languages",
        "aspect_ratio", "layout_preset_id", "layout_config", "caption_preset_id",
        "caption_font", "caption_config", "captions", "emojis", "use_llm",
        "cta_enabled", "overlays", "custom_keywords", "youtube_cookies", "crop_style",
    }
    merged = {**current, **{k: v for k, v in payload.items() if k in allowed}}
    normalized = project_service.normalize_project_settings(merged)
    template_id = str(payload.get("template_id") or "").strip() or None
    brand_kit_id = str(payload.get("brand_kit_id") or "").strip() or None
    if template_id and not studio_template_service.get_template(user["id"], template_id):
        return JSONResponse({"error": "template_not_found"}, status_code=404)
    if brand_kit_id and not brand_kit_service.get_brand_kit(user["id"], brand_kit_id):
        return JSONResponse({"error": "brand_kit_not_found"}, status_code=404)
    execute(
        "UPDATE projects SET settings_json=?,template_id=?,brand_kit_id=?,updated_at=? WHERE id=?",
        (json.dumps(normalized, ensure_ascii=False), template_id, brand_kit_id, now_iso(), project_id),
    )
    return {**normalized, "template_id": template_id, "brand_kit_id": brand_kit_id}


@app.get("/api/projects/{project_id}/tracking")
def project_tracking_status(request: Request, project_id: str):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    project = _owned_project(user["id"], project_id)
    if not project:
        return JSONResponse({"error": "not_found"}, status_code=404)
    try:
        summary = json.loads(project["tracking_summary_json"] or "{}")
    except Exception:
        summary = {}
    if not summary:
        summary = {"backend": "none", "track_count": 0, "coverage_percent": 0.0, "dominant_tracks": [], "fallback_reason": "Tracking ainda não disponível", "model_available": False, "analyzed_frames": 0}
    return summary


@app.get("/projects/{project_id}/thumb")
def project_thumb(request: Request, project_id: str):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    project = _owned_project(user["id"], project_id)
    if not project or not project["thumbnail_path"] or not Path(project["thumbnail_path"]).exists():
        return HTMLResponse("Imagem não encontrada", status_code=404)
    return FileResponse(project["thumbnail_path"], media_type="image/jpeg")


@app.get("/projects/{project_id}/download-all")
def project_download_all(request: Request, project_id: str):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    project = _owned_project(user["id"], project_id)
    if not project:
        return HTMLResponse("Projeto não encontrado", status_code=404)
    clips = fetchall("SELECT * FROM clips WHERE project_id=? AND video_path IS NOT NULL ORDER BY start_time", (project_id,))
    if not clips:
        return HTMLResponse("Nenhum corte renderizado para baixar.", status_code=404)
    zip_path = TEMP_DIR / f"{project_id}_cortes.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        used = set()
        for idx, c in enumerate(clips, 1):
            p = Path(c["video_path"])
            if not p.exists():
                continue
            name = f"{idx:02d}_{_safe_filename(c['title'])}.mp4"
            while name in used:
                name = f"{idx:02d}_{uuid.uuid4().hex[:4]}_{_safe_filename(c['title'])}.mp4"
            used.add(name)
            zf.write(p, arcname=name)
    return FileResponse(zip_path, media_type="application/zip", filename=f"{_safe_filename(project['title'], 'viralclip')}_cortes.zip")


@app.get("/clips/{clip_id}/video")
def clip_video(request: Request, clip_id: str):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    c = _owned_clip(user["id"], clip_id)
    if not c or not c["video_path"] or not Path(c["video_path"]).exists():
        return HTMLResponse("Arquivo não encontrado", status_code=404)
    return FileResponse(c["video_path"], media_type="video/mp4")


@app.get("/clips/{clip_id}/clean-video")
def clip_clean_video(request: Request, clip_id: str):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    c = _owned_clip(user["id"], clip_id)
    if not c:
        return HTMLResponse("Arquivo não encontrado", status_code=404)
    source_path = c["source_path"]
    if not source_path or not Path(source_path).exists():
        return HTMLResponse("Fonte do projeto indisponível", status_code=404)
    state = editor_service.get_or_create_edit_state(clip_id)
    aspect_ratio = _settings(c).get("aspect_ratio") or "9:16"
    state.setdefault("aspect_ratio", aspect_ratio)
    tracking_data = face_tracking.load_tracks(c["tracking_path"]) if c["tracking_path"] else face_tracking.empty_tracking("Tracking não disponível")
    clip_tracking = face_tracking.slice_tracks(tracking_data, float(c["start_time"]), float(c["end_time"]))
    settings = _settings(c)
    default_layout = settings.get("layout_preset_id") or settings.get("video_layout") or "auto"
    default_layout_config = settings.get("layout_config") or {}
    matches_project_default = (state.get("layout_preset_id") or "auto") == default_layout and (state.get("layout_config") or {}) == default_layout_config
    legacy_clean = c["clean_path"] if "clean_path" in c.keys() else None
    if matches_project_default and legacy_clean and Path(legacy_clean).exists() and Path(legacy_clean).stat().st_size > 0:
        return FileResponse(legacy_clean, media_type="video/mp4", headers={"Cache-Control": "no-store"})
    out = preview_service.clean_layout_path(clip_id, state, clip_tracking, aspect_ratio)
    if not out.exists() or out.stat().st_size <= 0:
        clean_state = dict(state)
        clean_state["overlays"] = []
        clean_state["tracks"] = {**(state.get("tracks") or {})}
        for key in ("captions", "overlays", "text", "cta"):
            clean_state["tracks"][key] = {**clean_state["tracks"].get(key, {}), "visible": False}
        render_edited_clip(
            Path(source_path), out, float(c["start_time"]), float(c["end_time"]), clean_state,
            caption_cues=[], tracking=clip_tracking,
        )
        if matches_project_default:
            execute("UPDATE clips SET clean_path=?,updated_at=? WHERE id=?", (str(out), now_iso(), clip_id))
    if matches_project_default:
        execute("UPDATE clips SET clean_path=?,updated_at=? WHERE id=?", (str(out), now_iso(), clip_id))
    return FileResponse(out, media_type="video/mp4", headers={"Cache-Control": "no-store"})


@app.get("/clips/{clip_id}/editor-proxy")
def clip_editor_proxy(request: Request, clip_id: str, retry: int = Query(0)):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    c = _owned_clip(user["id"], clip_id)
    if not c or not c["source_path"] or not Path(c["source_path"]).exists():
        return HTMLResponse("Fonte do projeto indisponível", status_code=404)
    state = editor_service.get_or_create_edit_state(clip_id)
    try:
        profile = hardware_service.load_or_build_profile()
        performance = performance_service.resolve_mode(profile, user["performance_mode"] or "auto")
        path = proxy_media_service.ensure_editor_proxy(
            clip_id, Path(c["source_path"]), float(c["start_time"]), float(c["end_time"]), state.get("aspect_ratio") or "9:16",
            target_height=int(performance["proxy_height"]),
            force_rebuild=bool(retry),
            prefer_cloud=(user["compute_mode"] or "auto") not in {"local", "cpu-local", "gpu-local"},
        )
    except Exception as exc:
        return HTMLResponse(f"Falha ao preparar proxy: {exc}", status_code=500)
    return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "no-store"})


@app.get("/clips/{clip_id}/waveform")
def clip_waveform(request: Request, clip_id: str):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    clip = _owned_clip(user["id"], clip_id)
    if not clip or not clip["source_path"] or not Path(clip["source_path"]).exists():
        return JSONResponse({"error": "source_not_found"}, status_code=404)
    try:
        path = waveform_service.ensure_waveform(
            clip_id, Path(clip["source_path"]), float(clip["start_time"]), float(clip["end_time"]), samples=360,
        )
        execute("UPDATE clips SET waveform_path=?,updated_at=? WHERE id=?", (str(path), now_iso(), clip_id))
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")), headers={"Cache-Control": "private, max-age=3600"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/clips/{clip_id}/preview-video")
def clip_preview_video(request: Request, clip_id: str):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    c = _owned_clip(user["id"], clip_id)
    if not c:
        return HTMLResponse("Arquivo não encontrado", status_code=404)
    revision = _clip_editor_revision(clip_id)
    current = _current_clip_render(clip_id, revision)
    if current:
        return FileResponse(current["video_path"], media_type="video/mp4", headers={"Cache-Control": "no-store"})
    if revision <= 1:
        for path in (c["preview_path"], c["video_path"]):
            if path and Path(path).exists() and Path(path).stat().st_size > 0:
                return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "no-store"})
    return HTMLResponse("Preview da edição atual ainda está sendo atualizado.", status_code=409, headers={"Cache-Control": "no-store"})


@app.get("/clips/{clip_id}/thumb")
def clip_thumb(request: Request, clip_id: str):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    c = _owned_clip(user["id"], clip_id)
    if not c:
        return HTMLResponse("Imagem não encontrada", status_code=404)
    revision = _clip_editor_revision(clip_id)
    current = _current_clip_render(clip_id, revision)
    if current:
        thumb = Path(current["video_path"]).with_suffix(".jpg")
        if not thumb.exists() or thumb.stat().st_size <= 0:
            try:
                generate_thumbnail(Path(current["video_path"]), thumb, "")
            except Exception:
                pass
        if thumb.exists() and thumb.stat().st_size > 0:
            return FileResponse(thumb, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
    if revision <= 1 and c["thumbnail_path"] and Path(c["thumbnail_path"]).exists():
        return FileResponse(c["thumbnail_path"], media_type="image/jpeg", headers={"Cache-Control": "no-store"})
    return HTMLResponse("Imagem da edição atual ainda está sendo atualizada.", status_code=409, headers={"Cache-Control": "no-store"})


@app.get("/clips/{clip_id}/download")
def clip_download(request: Request, clip_id: str):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    c = _owned_clip(user["id"], clip_id)
    if not c or not c["video_path"] or not Path(c["video_path"]).exists():
        return HTMLResponse("Arquivo não encontrado", status_code=404)
    current_revision = int(editor_service.get_or_create_edit_state(clip_id).get("revision") or 1)
    latest = fetchone("SELECT editor_revision FROM clip_renders WHERE clip_id=? AND kind='final' AND status='done' ORDER BY created_at DESC LIMIT 1", (clip_id,))
    if latest and latest["editor_revision"] is not None and int(latest["editor_revision"]) != current_revision:
        return HTMLResponse("Há alterações não renderizadas. Renderize a versão final atual antes de baixar.", status_code=409)
    return FileResponse(c["video_path"], media_type="video/mp4", filename=f"{_safe_filename(c['title'])}.mp4")


@app.get("/api/caption-presets")
def api_caption_presets(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return caption_engine.list_caption_presets()


@app.get("/api/layout-presets")
def api_layout_presets(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    items = layout_service.list_layout_presets()
    for item in items:
        item["panels"] = layout_service.layout_preview_panels(item["id"])
    return items


@app.get("/api/fonts")
def api_fonts(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return font_service.list_fonts()


@app.get("/api/presets")
def api_user_presets(request: Request, preset_type: str | None = None):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return editor_service.list_user_presets(user["id"], preset_type)


@app.post("/presets")
def save_preset(request: Request, payload: dict[str, Any] = Body(...)):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        return editor_service.save_user_preset(
            user["id"],
            str(payload.get("preset_type") or "combined"),
            str(payload.get("name") or "Meu preset"),
            payload.get("config") or {},
            favorite=bool(payload.get("favorite")),
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/presets/{preset_id}/favorite")
def favorite_preset(request: Request, preset_id: str, payload: dict[str, Any] = Body(...)):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    preset = editor_service.get_user_preset(user["id"], preset_id)
    if not preset:
        return JSONResponse({"error": "not_found"}, status_code=404)
    execute("UPDATE user_presets SET favorite=?,updated_at=? WHERE id=? AND user_id=?", (int(bool(payload.get("favorite"))), now_iso(), preset_id, user["id"]))
    return editor_service.get_user_preset(user["id"], preset_id)


@app.post("/presets/{preset_id}/duplicate")
def duplicate_preset(request: Request, preset_id: str):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    preset = editor_service.get_user_preset(user["id"], preset_id)
    if not preset:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return editor_service.save_user_preset(
        user["id"], preset["preset_type"], f"{preset['name']} (cópia)", preset["config"], favorite=False
    )


@app.get("/clips/{clip_id}/editor-state")
def get_editor_state(request: Request, clip_id: str):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not _owned_clip(user["id"], clip_id):
        return JSONResponse({"error": "not_found"}, status_code=404)
    return editor_service.get_or_create_edit_state(clip_id)


@app.put("/clips/{clip_id}/editor-state")
def put_editor_state(request: Request, clip_id: str, payload: dict[str, Any] = Body(...)):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    clip = _owned_clip(user["id"], clip_id)
    if not clip:
        return JSONResponse({"error": "not_found"}, status_code=404)
    payload = layout_service.ensure_layout_overlays(payload, clip["title"] or "")
    return editor_service.save_edit_state(clip_id, payload)


@app.get("/clips/{clip_id}/captions")
def get_captions(request: Request, clip_id: str):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    clip = _owned_clip(user["id"], clip_id)
    if not clip:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return _initial_cues(clip)


@app.put("/clips/{clip_id}/captions")
def put_captions(request: Request, clip_id: str, payload: list[dict[str, Any]] = Body(...)):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not _owned_clip(user["id"], clip_id):
        return JSONResponse({"error": "not_found"}, status_code=404)
    return editor_service.replace_caption_cues(clip_id, payload)


@app.put("/clips/{clip_id}/snapshot")
def put_editor_snapshot(request: Request, clip_id: str, payload: dict[str, Any] = Body(...)):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    clip = _owned_clip(user["id"], clip_id)
    if not clip:
        return JSONResponse({"error": "not_found"}, status_code=404)
    state = layout_service.ensure_layout_overlays(payload.get("state") or {}, clip["title"] or "")
    cues = payload.get("cues") or []
    timeline_data = payload.get("timeline") or timeline_service.get_or_create_timeline(clip_id)
    return editor_service.save_editor_snapshot(clip_id, state, cues, timeline_data)


@app.get("/clips/{clip_id}/edit", response_class=HTMLResponse)
def edit_clip_page(request: Request, clip_id: str):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    clip = _owned_clip(user["id"], clip_id)
    if not clip:
        return HTMLResponse("Corte não encontrado", status_code=404)
    state = editor_service.get_or_create_edit_state(clip_id)
    cues = _initial_cues(clip)
    settings = _settings(clip)
    state["aspect_ratio"] = settings.get("aspect_ratio") or state.get("aspect_ratio") or "9:16"
    performance = performance_service.resolve_mode(hardware_service.load_or_build_profile(), user["performance_mode"] or "auto")
    return render(
        request,
        "editor.html",
        clip=clip,
        settings=settings,
        **_geometry_labels(settings),
        state=state,
        cues=cues,
        caption_presets=caption_engine.list_caption_presets(),
        layout_presets=layout_service.list_layout_presets(),
        fonts=font_service.list_fonts(),
        user_presets=editor_service.list_user_presets(user["id"]),
        studio_templates=studio_template_service.list_templates(user["id"]),
        brand_kits=brand_kit_service.list_brand_kits(user["id"]),
        performance=performance,
    )


@app.post("/clips/{clip_id}/edit")
def legacy_edit_clip(
    request: Request,
    clip_id: str,
    overlay_text: str = Form(""),
    crop_style: str = Form("blur"),
    caption_style: str = Form("bold"),
    captions: str | None = Form(None),
):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    clip = _owned_clip(user["id"], clip_id)
    if not clip or not clip["source_path"]:
        return HTMLResponse("Dados do projeto indisponíveis para re-render.", status_code=400)
    state = editor_service.get_or_create_edit_state(clip_id)
    state["layout_preset_id"] = "center" if crop_style == "blur" else "single"
    state["caption_preset_id"] = {"bold": "green-fresh", "large": "mrbeast", "minimal": "minimal-clean"}.get(caption_style, caption_style)
    state["tracks"]["captions"]["visible"] = captions == "on"
    if overlay_text:
        state["overlays"] = [{"type": "text", "text": overlay_text, "x": 70, "y": 100, "width": 940, "height": 160, "fontSize": 58}]
    editor_service.save_edit_state(clip_id, state)
    return RedirectResponse(f"/clips/{clip_id}/edit", status_code=303)


@app.post("/projects/{project_id}/bulk-edit")
def bulk_edit(request: Request, project_id: str, payload: dict[str, Any] = Body(...)):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    project = _owned_project(user["id"], project_id)
    if not project:
        return JSONResponse({"error": "not_found"}, status_code=404)
    requested = [str(x) for x in payload.get("clip_ids") or []]
    valid = {r["id"] for r in fetchall("SELECT id FROM clips WHERE project_id=?", (project_id,))}
    ids = [x for x in requested if x in valid]
    for clip_id in ids:
        state = editor_service.get_or_create_edit_state(clip_id)
        for key in ("caption_preset_id", "layout_preset_id", "overlays", "tracks"):
            if key in payload:
                state[key] = payload[key]
        if "caption_config" in payload:
            state["caption_config"] = {**(state.get("caption_config") or {}), **(payload.get("caption_config") or {})}
        if "layout_config" in payload:
            state["layout_config"] = {**(state.get("layout_config") or {}), **(payload.get("layout_config") or {})}
        editor_service.save_edit_state(clip_id, state)
    return {"updated": len(ids), "clip_ids": ids}


@app.get("/projects/{project_id}/bulk-editor", response_class=HTMLResponse)
def bulk_editor_page(request: Request, project_id: str, ids: str = ""):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    project = _owned_project(user["id"], project_id)
    if not project:
        return HTMLResponse("Projeto não encontrado", status_code=404)
    selected = [x for x in ids.split(",") if x]
    if selected:
        placeholders = ",".join("?" for _ in selected)
        clips = fetchall(f"SELECT * FROM clips WHERE project_id=? AND id IN ({placeholders}) ORDER BY start_time", (project_id, *selected))
    else:
        clips = fetchall("SELECT * FROM clips WHERE project_id=? ORDER BY start_time", (project_id,))
    return render(
        request,
        "bulk_editor.html",
        project=project,
        clips=clips,
        selected_ids=[c["id"] for c in clips],
        caption_presets=caption_engine.list_caption_presets(),
        layout_presets=layout_service.list_layout_presets(),
        fonts=font_service.list_fonts(),
        user_presets=editor_service.list_user_presets(user["id"]),
    )


@app.get("/projects/{project_id}/new-clip", response_class=HTMLResponse)
def new_manual_clip_page(request: Request, project_id: str, asset_id: str = Query("")):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    project = _owned_project(user["id"], project_id)
    if not project:
        return HTMLResponse("Projeto não encontrado", status_code=404)
    assets = [dict(a) for a in fetchall("SELECT * FROM project_assets WHERE project_id=? AND kind='source' ORDER BY created_at", (project_id,))]
    selected_asset = next((a for a in assets if a["id"] == asset_id), None) if asset_id else None
    return render(request, "manual_clip.html", project=project, assets=assets, selected_asset=selected_asset, selected_asset_id=asset_id)


@app.post("/projects/{project_id}/new-clip")
def create_manual_clip(request: Request, project_id: str, title: str = Form("Novo clipe"), start_time: float = Form(...), end_time: float = Form(...), asset_id: str = Form("")):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    project = _owned_project(user["id"], project_id)
    if not project:
        return HTMLResponse("Projeto não encontrado", status_code=404)
    source_path = project["source_path"]
    transcript_path = project["transcript_path"]
    if asset_id:
        asset = fetchone("SELECT * FROM project_assets WHERE id=? AND project_id=? AND kind='source'", (asset_id, project_id))
        if not asset:
            return HTMLResponse("Fonte importada não encontrada.", status_code=404)
        source_path = asset["local_path"]
        transcript_path = None
    if not source_path or not Path(source_path).exists():
        return HTMLResponse("Fonte local indisponível.", status_code=400)
    if end_time <= start_time:
        return HTMLResponse("O fim precisa ser maior que o início.", status_code=400)
    clip_id = uuid.uuid4().hex
    out_dir = OUTPUT_DIR / project_id; out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"manual_{clip_id[:8]}.mp4"
    state = {
        "caption_preset_id": _settings(project).get("caption_preset_id", "green-fresh"),
        "layout_preset_id": _settings(project).get("layout_preset_id", "auto"),
        "caption_config": _settings(project).get("caption_config", {}),
        "overlays": _settings(project).get("overlays", []),
    }
    transcript = None
    if transcript_path and Path(transcript_path).exists():
        transcript = json.loads(Path(transcript_path).read_text(encoding="utf-8"))
    result = render_edited_clip(Path(source_path), out, start_time, end_time, state, transcript=transcript)
    thumb = THUMB_DIR / f"{clip_id}.jpg"
    try:
        generate_thumbnail(out, thumb, title)
        thumb_path = str(thumb)
    except Exception:
        thumb_path = None
    now = now_iso()
    analysis = viral_score_service.score_clip_payload({
        "title": title.strip() or "Novo clipe", "reason": "Criado manualmente",
        "duration": max(0.0, end_time - start_time), "score": 0,
    })
    execute(
        "INSERT INTO clips(id,project_id,title,start_time,end_time,score,reason,video_path,thumbnail_path,created_at,updated_at,render_status,render_encoder,file_size,analysis_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (clip_id, project_id, title.strip() or "Novo clipe", start_time, end_time, 0, "Criado manualmente", str(out), thumb_path, now, now, "rendered", result.get("encoder"), out.stat().st_size if out.exists() else None, json.dumps(analysis, ensure_ascii=False)),
    )
    editor_service.save_edit_state(clip_id, state)
    if project["template_id"]:
        studio_template_service.apply_template(user["id"], str(project["template_id"]), [clip_id])
    if project["brand_kit_id"]:
        brand_kit_service.apply_brand_kit(user["id"], str(project["brand_kit_id"]), [clip_id])
    return RedirectResponse(f"/clips/{clip_id}/edit", status_code=303)


@app.post("/projects/{project_id}/import")
async def import_project_video(request: Request, project_id: str, upload: UploadFile = File(...)):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    project = _owned_project(user["id"], project_id)
    if not project:
        return HTMLResponse("Projeto não encontrado", status_code=404)
    if not project_service.validate_upload_filename(upload.filename):
        return HTMLResponse("Formato inválido. Use MP4, MOV, MKV ou AVI.", status_code=400)
    asset_id = uuid.uuid4().hex[:16]
    folder = BASE_DIR / "data" / "uploads" / project_id / "assets"; folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{asset_id}{Path(upload.filename).suffix.lower()}"
    total = 0
    with path.open("wb") as f:
        while chunk := await upload.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_UPLOAD_MB * 1024 * 1024:
                path.unlink(missing_ok=True)
                return HTMLResponse("Arquivo excede o limite configurado.", status_code=413)
            f.write(chunk)
    execute(
        "INSERT INTO project_assets(id,project_id,kind,provider,source_value,local_path,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (asset_id, project_id, "source", "upload", upload.filename, str(path), json.dumps({"size": total}), now_iso()),
    )
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@app.get("/projects/{project_id}/source-video")
def project_source_video(request: Request, project_id: str, asset_id: str = Query("")):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    project = _owned_project(user["id"], project_id)
    if not project:
        return HTMLResponse("Projeto não encontrado", status_code=404)
    path = project["source_path"]
    if asset_id:
        asset = fetchone("SELECT local_path FROM project_assets WHERE id=? AND project_id=? AND kind='source'", (asset_id, project_id))
        path = asset["local_path"] if asset else None
    if not path or not Path(path).exists():
        return HTMLResponse("Fonte local indisponível", status_code=404)
    return FileResponse(path, media_type="video/mp4")


@app.post("/clips/{clip_id}/preview-render")
def queue_preview_render(request: Request, clip_id: str, payload: dict[str, Any] = Body(default={})):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not _owned_clip(user["id"], clip_id):
        return JSONResponse({"error": "not_found"}, status_code=404)
    try:
        playhead = max(0.0, float(payload.get("playhead") or 0))
    except Exception:
        playhead = 0.0
    revision = payload.get("revision")
    try:
        render_id = render_queue.enqueue_clip_render(clip_id, "preview", preview_offset=max(0.0, playhead - 2.0), editor_revision=int(revision) if revision is not None else None)
    except ValueError as exc:
        if str(exc) == "editor_revision_stale":
            return JSONResponse({"error": "snapshot_stale"}, status_code=409)
        raise
    return {"render_id": render_id, "status": "queued"}


@app.post("/clips/{clip_id}/project-preview-render")
def queue_project_preview_render(request: Request, clip_id: str, payload: dict[str, Any] = Body(default={})):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not _owned_clip(user["id"], clip_id):
        return JSONResponse({"error": "not_found"}, status_code=404)
    revision = payload.get("revision")
    try:
        render_id = render_queue.enqueue_clip_render(
            clip_id,
            "project_preview",
            editor_revision=int(revision) if revision is not None else None,
        )
    except ValueError as exc:
        if str(exc) == "editor_revision_stale":
            return JSONResponse({"error": "snapshot_stale"}, status_code=409)
        raise
    return {"render_id": render_id, "status": "queued"}


@app.post("/clips/{clip_id}/final-render")
def queue_final_render(request: Request, clip_id: str, payload: dict[str, Any] = Body(default={})):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not _owned_clip(user["id"], clip_id):
        return JSONResponse({"error": "not_found"}, status_code=404)
    revision = payload.get("revision")
    clip = _owned_clip(user["id"], clip_id)
    state = editor_service.get_or_create_edit_state(clip_id)
    timeline_data = timeline_service.get_or_create_timeline(clip_id)
    check = quality_check_service.inspect(Path(clip["source_path"]) if clip and clip["source_path"] else None, state, timeline_data)
    if check["errors"]:
        return JSONResponse({"error": "quality_check_failed", "details": check}, status_code=422)
    try:
        render_id = render_queue.enqueue_clip_render(clip_id, "final", editor_revision=int(revision) if revision is not None else None)
    except ValueError as exc:
        if str(exc) == "editor_revision_stale":
            return JSONResponse({"error": "snapshot_stale"}, status_code=409)
        raise
    return {"render_id": render_id, "status": "queued"}


@app.get("/renders/{render_id}")
def render_status_api(request: Request, render_id: str):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    row = fetchone(
        "SELECT r.* FROM clip_renders r JOIN clips c ON c.id=r.clip_id JOIN projects p ON p.id=c.project_id WHERE r.id=? AND p.user_id=?",
        (render_id, user["id"]),
    )
    if not row:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return dict(row)


@app.get("/renders/{render_id}/video")
def render_video(request: Request, render_id: str, download: int = 0):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    row = fetchone(
        "SELECT r.*,c.title FROM clip_renders r JOIN clips c ON c.id=r.clip_id JOIN projects p ON p.id=c.project_id WHERE r.id=? AND p.user_id=?",
        (render_id, user["id"]),
    )
    if not row or not row["video_path"] or not Path(row["video_path"]).exists():
        return HTMLResponse("Render não encontrado", status_code=404)
    return FileResponse(row["video_path"], media_type="video/mp4", filename=f"{_safe_filename(row['title'])}.mp4") if download else FileResponse(row["video_path"], media_type="video/mp4")


@app.get("/clips/{clip_id}/renders/{render_id}")
def clip_render_status(request: Request, clip_id: str, render_id: str):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    row = fetchone(
        "SELECT r.* FROM clip_renders r JOIN clips c ON c.id=r.clip_id JOIN projects p ON p.id=c.project_id WHERE r.id=? AND c.id=? AND p.user_id=?",
        (render_id, clip_id, user["id"]),
    )
    return dict(row) if row else JSONResponse({"error": "not_found"}, status_code=404)


@app.post("/projects/{project_id}/bulk-render")
def bulk_render(request: Request, project_id: str, payload: dict[str, Any] = Body(...)):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    project = _owned_project(user["id"], project_id)
    if not project:
        return JSONResponse({"error": "not_found"}, status_code=404)
    valid = {r["id"] for r in fetchall("SELECT id FROM clips WHERE project_id=?", (project_id,))}
    ids = [str(x) for x in payload.get("clip_ids") or [] if str(x) in valid]
    kind = "preview" if payload.get("kind") == "preview" else "final"
    render_ids = [render_queue.enqueue_clip_render(cid, kind) for cid in ids]
    return {"queued": len(render_ids), "render_ids": render_ids}


@app.get("/api/brand-assets")
def list_brand_assets(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    rows = fetchall("SELECT * FROM brand_assets WHERE user_id=? ORDER BY created_at DESC", (user["id"],))
    out = []
    for row in rows:
        d = dict(row)
        try:
            d["config"] = json.loads(d.pop("config_json") or "{}")
        except Exception:
            d["config"] = {}
        out.append(d)
    return out


@app.post("/brand-assets")
async def upload_brand_asset(
    request: Request,
    file: UploadFile = File(...),
    name: str = Form("Asset"),
    asset_type: str = Form("logo"),
    return_to: str = Form(""),
):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        return JSONResponse({"error": "Use PNG, JPG ou WEBP."}, status_code=400)
    if asset_type not in {"logo", "watermark", "image"}:
        asset_type = "image"
    asset_id = uuid.uuid4().hex[:16]
    folder = BASE_DIR / "data" / "brand" / str(user["id"])
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{asset_id}{ext}"
    total = 0
    with path.open("wb") as f:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > 20 * 1024 * 1024:
                path.unlink(missing_ok=True)
                return JSONResponse({"error": "Asset maior que 20 MB."}, status_code=413)
            f.write(chunk)
    now = now_iso()
    execute(
        "INSERT INTO brand_assets(id,user_id,name,asset_type,file_path,config_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (asset_id, user["id"], name.strip() or "Asset", asset_type, str(path), json.dumps({"size": total}), now, now),
    )
    if return_to.startswith("/"):
        return RedirectResponse(return_to, status_code=303)
    return {"id": asset_id, "name": name.strip() or "Asset", "asset_type": asset_type, "file_path": str(path)}


@app.get("/brand-assets/{asset_id}/file")
def brand_asset_file(request: Request, asset_id: str):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    row = fetchone("SELECT * FROM brand_assets WHERE id=? AND user_id=?", (asset_id, user["id"]))
    if not row or not row["file_path"] or not Path(row["file_path"]).exists():
        return HTMLResponse("Asset não encontrado", status_code=404)
    suffix = Path(row["file_path"]).suffix.lower()
    media = "image/png" if suffix == ".png" else "image/webp" if suffix == ".webp" else "image/jpeg"
    return FileResponse(row["file_path"], media_type=media)


def _worker_api_identity(request: Request):
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer ") and worker_pairing_service.validate_token(auth.split(" ", 1)[1].strip()):
        return {"kind": "pairing", "user": None}
    user = current_user(request)
    if user:
        return {"kind": "session", "user": user}
    return None


def _worker_job_allowed(request: Request, snapshot: dict | None) -> bool:
    ident = _worker_api_identity(request)
    if not ident or not snapshot:
        return False
    if ident["kind"] == "pairing":
        return True
    if snapshot.get("kind") == "project" and snapshot.get("target_id"):
        return bool(_owned_project(ident["user"]["id"], str(snapshot["target_id"])))
    return True


@app.get("/api/v1/health")
def api_v1_health():
    return api_v1_service.health_payload()


@app.get("/api/v1/capabilities")
def api_v1_capabilities(request: Request):
    if not _worker_api_identity(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return api_v1_service.capabilities_payload()


@app.post("/api/v1/hardware/revalidate")
def api_v1_hardware_revalidate(request: Request):
    if not _worker_api_identity(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return hardware_service.load_or_build_profile(force=True)


@app.post("/api/v1/pair")
def api_v1_pair(payload: dict[str, Any] = Body(...)):
    try:
        return worker_pairing_service.issue_token(str(payload.get("code") or ""), str(payload.get("device_name") or "Browser"))
    except ValueError:
        return JSONResponse({"error": "pairing_code_invalid"}, status_code=401)


@app.post("/api/v1/jobs")
def api_v1_create_job(request: Request, payload: dict[str, Any] = Body(...)):
    ident = _worker_api_identity(request)
    if not ident:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    kind = str(payload.get("kind") or "project")
    target_id = str(payload.get("target_id") or "")
    if kind != "project" or not target_id:
        return JSONResponse({"error": "unsupported_job"}, status_code=400)
    if ident["kind"] == "session" and not _owned_project(ident["user"]["id"], target_id):
        return JSONResponse({"error": "project_not_found"}, status_code=404)
    jid = project_jobs.submit(target_id)
    return job_store_service.job_snapshot(jid)


@app.get("/api/v1/jobs/{job_id}")
def api_v1_get_job(request: Request, job_id: str):
    snap = job_store_service.job_snapshot(job_id)
    if not _worker_job_allowed(request, snap):
        return JSONResponse({"error": "job_not_found"}, status_code=404)
    return snap


@app.get("/api/v1/jobs/{job_id}/events")
def api_v1_job_events(request: Request, job_id: str):
    snap = job_store_service.job_snapshot(job_id)
    if not _worker_job_allowed(request, snap):
        return JSONResponse({"error": "job_not_found"}, status_code=404)
    return {"id": job_id, "status": snap.get("status"), "stage": snap.get("stage"), "stages": snap.get("stages") or [], "heartbeat_at": snap.get("heartbeat_at")}


def _job_control_response(request: Request, job_id: str, state: str):
    snap = job_store_service.job_snapshot(job_id)
    if not _worker_job_allowed(request, snap):
        return JSONResponse({"error": "job_not_found"}, status_code=404)
    job_store_service.set_control(job_id, state)
    return job_store_service.job_snapshot(job_id)


@app.post("/api/v1/jobs/{job_id}/pause")
def api_v1_pause_job(request: Request, job_id: str):
    return _job_control_response(request, job_id, "paused")


@app.post("/api/v1/jobs/{job_id}/resume")
def api_v1_resume_job(request: Request, job_id: str):
    return _job_control_response(request, job_id, "running")


@app.post("/api/v1/jobs/{job_id}/cancel")
def api_v1_cancel_job(request: Request, job_id: str):
    return _job_control_response(request, job_id, "cancelled")


@app.post("/api/v1/jobs/{job_id}/retry")
def api_v1_retry_job(request: Request, job_id: str):
    snap = job_store_service.job_snapshot(job_id)
    if not _worker_job_allowed(request, snap):
        return JSONResponse({"error": "job_not_found"}, status_code=404)
    if snap.get("kind") != "project" or not snap.get("target_id"):
        return JSONResponse({"error": "not_retryable"}, status_code=400)
    execute("UPDATE projects SET status='queued',progress=0,message='Na fila',updated_at=? WHERE id=?", (now_iso(), snap["target_id"]))
    jid = project_jobs.submit(str(snap["target_id"]))
    return job_store_service.job_snapshot(jid)


@app.get("/api/v1/assets")
def api_v1_assets(request: Request, q: str = "", kind: str | None = None, limit: int = 20, orientation: str | None = None):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not _is_admin(user):
        return JSONResponse({"error": "admin_required"}, status_code=403)
    if q.strip():
        return {"items": asset_service.search_assets(q, kind=kind, limit=limit, orientation=orientation), "status": asset_service.starter_pack_status()}
    items = asset_service.scan_assets()
    if kind:
        items = [a for a in items if a.get("kind") == kind]
    return {"items": items[: max(1, min(100, int(limit)))], "status": asset_service.starter_pack_status()}


@app.get("/api/v1/assets/status")
def api_v1_asset_status(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not _is_admin(user):
        return JSONResponse({"error": "admin_required"}, status_code=403)
    return asset_service.starter_pack_status()


@app.post("/api/v1/assets/import")
async def api_v1_import_asset(
    request: Request, file: UploadFile = File(...), kind: str = Form("broll"), tags: str = Form("")
):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not _is_admin(user):
        return JSONResponse({"error": "admin_required"}, status_code=403)
    kind = kind if kind in {"broll", "sfx", "music", "overlay", "background", "user"} else "user"
    filename = _safe_filename(file.filename or "asset", "asset")
    suffix = Path(filename).suffix.lower()
    allowed = asset_service.VIDEO_EXTS | asset_service.AUDIO_EXTS | asset_service.IMAGE_EXTS
    if suffix not in allowed:
        return JSONResponse({"error": "formato de asset não suportado"}, status_code=400)
    target_dir = asset_service.ASSET_DIR / "user"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid.uuid4().hex[:10]}_{filename}"
    total = 0
    max_bytes = MAX_UPLOAD_MB * 1024 * 1024
    try:
        with target.open("wb") as fh:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("asset excede o limite de upload")
                fh.write(chunk)
    except Exception as exc:
        target.unlink(missing_ok=True)
        return JSONResponse({"error": str(exc)}, status_code=413 if "limite" in str(exc) else 400)
    tag_list = [x.strip() for x in re.split(r"[,;]", tags or "") if x.strip()]
    return asset_service.register_asset(
        kind, target, name=Path(filename).stem, tags=tag_list, provider="user",
        license_name="user-provided", attribution="Arquivo do usuário",
    )


@app.get("/api/v1/assets/{asset_id}/file")
def api_v1_asset_file(request: Request, asset_id: str):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not _is_admin(user):
        return JSONResponse({"error": "admin_required"}, status_code=403)
    item = asset_service.get_asset(asset_id)
    if not item:
        return JSONResponse({"error": "asset_not_found"}, status_code=404)
    path = Path(str(item.get("local_path") or ""))
    if not path.exists() or not path.is_file():
        return JSONResponse({"error": "asset_file_missing"}, status_code=404)
    return FileResponse(path, filename=path.name)


@app.get("/api/v1/clips/{clip_id}/timeline")
def api_v1_get_timeline(request: Request, clip_id: str):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not _owned_clip(user["id"], clip_id):
        return JSONResponse({"error": "clip_not_found"}, status_code=404)
    return timeline_service.get_or_create_timeline(clip_id)


@app.put("/api/v1/clips/{clip_id}/timeline")
def api_v1_put_timeline(request: Request, clip_id: str, payload: dict[str, Any] = Body(...)):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not _owned_clip(user["id"], clip_id):
        return JSONResponse({"error": "clip_not_found"}, status_code=404)
    try:
        return timeline_service.save_timeline(clip_id, payload)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/api/v1/clips/{clip_id}/auto-edit")
def api_v1_auto_edit(request: Request, clip_id: str, payload: dict[str, Any] = Body(default={})):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not _owned_clip(user["id"], clip_id):
        return JSONResponse({"error": "clip_not_found"}, status_code=404)
    try:
        return auto_edit_service.build_auto_edit_plan(
            clip_id,
            style=str(payload.get("style") or "podcast-viral"),
            intensity=str(payload.get("intensity") or "normal"),
            options=payload.get("options") if isinstance(payload.get("options"), dict) else {},
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.get("/profiles", response_class=HTMLResponse)
def profiles_page(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    profiles = fetchall("SELECT * FROM creator_profiles WHERE user_id=? ORDER BY created_at DESC", (user["id"],))
    return render(request, "profiles.html", profiles=profiles)


@app.post("/profiles")
def create_profile(
    request: Request,
    name: str = Form(...),
    preferred_min: float = Form(25),
    preferred_max: float = Form(75),
    avg_duration: float = Form(45),
    aggression: float = Form(0.6),
    keywords: str = Form(""),
):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    execute(
        "INSERT INTO creator_profiles(user_id,name,avg_duration,preferred_min,preferred_max,aggression,keywords,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (user["id"], name.strip(), avg_duration, preferred_min, preferred_max, aggression, keywords.strip(), now_iso()),
    )
    return RedirectResponse("/profiles", status_code=303)


@app.post("/projects/{project_id}/delete")
def delete_project(request: Request, project_id: str):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    p = _owned_project(user["id"], project_id)
    if p:
        execute("DELETE FROM projects WHERE id=?", (project_id,))
        for base in (BASE_DIR / "data" / "outputs" / project_id, BASE_DIR / "data" / "uploads" / project_id, BASE_DIR / "data" / "temp" / project_id):
            shutil.rmtree(base, ignore_errors=True)
    return RedirectResponse("/dashboard", status_code=303)

# ---------------------------------------------------------------------------
# V4.2 Adaptive Compute Fabric + Creator Intelligence
# ---------------------------------------------------------------------------

@app.get("/compute", response_class=HTMLResponse)
def compute_page(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return redirect
    profile = hardware_service.load_or_build_profile()
    local_nodes = [n.payload() for n in compute_service.local_nodes(profile)]
    cloud = cloud_client_service.health(timeout=2.5)
    tasks = compute_service.recent_tasks(40)
    decisions = [dict(r) for r in fetchall("SELECT * FROM scheduler_decisions ORDER BY created_at DESC LIMIT 30")]
    samples = [dict(r) for r in fetchall(
        "SELECT node_kind,task_type,COUNT(*) samples,AVG(speed) avg_speed,AVG(seconds) avg_seconds FROM performance_samples WHERE ok=1 GROUP BY node_kind,task_type ORDER BY node_kind,task_type"
    )]
    return render(
        request,
        "compute.html",
        local_nodes=local_nodes,
        cloud=cloud,
        tasks=tasks,
        decisions=decisions,
        samples=samples,
        compute_mode=user["compute_mode"] or "auto",
    )


@app.get("/api/v1/compute")
def api_v1_compute(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    profile = hardware_service.load_or_build_profile()
    nodes = [n.payload() for n in compute_service.local_nodes(profile)]
    if cloud_client_service.configured():
        nodes.append(cloud_client_service.cloud_node().payload())
    return {
        "mode": user["compute_mode"] or "auto",
        "free_cpu_only": True,
        "nodes": nodes,
        "recent_tasks": compute_service.recent_tasks(25),
    }


@app.post("/api/v1/compute-mode")
def api_v1_compute_mode(request: Request, payload: dict[str, Any] = Body(...)):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    mode = str(payload.get("mode") or "auto").lower()
    if mode not in {"auto", "hybrid", "cloud", "local", "cpu-local", "gpu-local"}:
        return JSONResponse({"error": "invalid_mode"}, status_code=400)
    execute("UPDATE users SET compute_mode=? WHERE id=?", (mode, user["id"]))
    return {"mode": mode, "free_cpu_only": True}


@app.get("/api/v1/lightning/health")
def api_v1_lightning_health(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return cloud_client_service.health(timeout=3.0)


@app.get("/api/v1/projects/{project_id}/compute")
def api_v1_project_compute(request: Request, project_id: str):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    project = _owned_project(user["id"], project_id)
    if not project:
        return JSONResponse({"error": "not_found"}, status_code=404)
    tasks = [dict(r) for r in fetchall("SELECT * FROM processing_tasks WHERE project_id=? ORDER BY created_at", (project_id,))]
    try:
        summary = json.loads(project["compute_summary_json"] or "{}")
    except Exception:
        summary = {}
    return {"project_id": project_id, "summary": summary, "tasks": tasks}


@app.get("/api/v1/projects/{project_id}/search")
def api_v1_project_semantic_search(request: Request, project_id: str, q: str = Query(...), limit: int = Query(12)):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    project = _owned_project(user["id"], project_id)
    if not project:
        return JSONResponse({"error": "not_found"}, status_code=404)
    path = Path(project["transcript_path"]) if project["transcript_path"] else None
    if not path or not path.exists():
        return JSONResponse({"error": "transcript_unavailable"}, status_code=409)
    try:
        transcript = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return JSONResponse({"error": "transcript_invalid"}, status_code=500)
    return {"query": q, "results": semantic_search_service.search_transcript(transcript, q, limit=limit)}


@app.post("/api/v1/clips/{clip_id}/prompt-edit")
def api_v1_prompt_edit(request: Request, clip_id: str, payload: dict[str, Any] = Body(...)):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not _owned_clip(user["id"], clip_id):
        return JSONResponse({"error": "clip_not_found"}, status_code=404)
    try:
        return prompt_edit_service.apply_prompt(clip_id, str(payload.get("prompt") or ""))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.get("/api/v1/clips/{clip_id}/revisions")
def api_v1_clip_revisions(request: Request, clip_id: str):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not _owned_clip(user["id"], clip_id):
        return JSONResponse({"error": "clip_not_found"}, status_code=404)
    return {"revisions": revision_service.list_revisions(clip_id)}


@app.post("/api/v1/clips/{clip_id}/revisions")
def api_v1_create_revision(request: Request, clip_id: str, payload: dict[str, Any] = Body(default={})):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not _owned_clip(user["id"], clip_id):
        return JSONResponse({"error": "clip_not_found"}, status_code=404)
    return revision_service.create_revision(clip_id, str(payload.get("label") or "Checkpoint"))


@app.post("/api/v1/clips/{clip_id}/revisions/{revision}/restore")
def api_v1_restore_revision(request: Request, clip_id: str, revision: int):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not _owned_clip(user["id"], clip_id):
        return JSONResponse({"error": "clip_not_found"}, status_code=404)
    try:
        return revision_service.restore_revision(clip_id, revision)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)


@app.get("/api/v1/clips/{clip_id}/viral-score-v3")
def api_v1_viral_score_v3(request: Request, clip_id: str, platform: str = Query("")):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    clip = _owned_clip(user["id"], clip_id)
    if not clip:
        return JSONResponse({"error": "clip_not_found"}, status_code=404)
    try:
        analysis = json.loads(clip["analysis_json"] or "{}")
    except Exception:
        analysis = {}
    duration = max(0.0, float(clip["end_time"] or 0) - float(clip["start_time"] or 0))
    base = viral_score_service.score_clip_payload_v3({
        "title": clip["title"], "hook": clip["hook"], "reason": clip["reason"], "duration": duration,
        "score": clip["score"], "text": analysis.get("text") or "",
    })
    calibration = creator_intelligence_service.calibrate_score(user["id"], base["score"], duration=duration, platform=platform or None)
    return viral_score_service.score_clip_payload_v3({
        "title": clip["title"], "hook": clip["hook"], "reason": clip["reason"], "duration": duration,
        "score": clip["score"], "text": analysis.get("text") or "",
    }, creator_calibration=calibration)


@app.post("/api/v1/creator-performance")
def api_v1_creator_performance(request: Request, payload: dict[str, Any] = Body(...)):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    clip_id = str(payload.get("clip_id") or "") or None
    if clip_id and not _owned_clip(user["id"], clip_id):
        return JSONResponse({"error": "clip_not_found"}, status_code=404)
    try:
        return creator_intelligence_service.record_performance(
            user["id"], clip_id=clip_id, platform=str(payload.get("platform") or "manual"),
            views=int(payload.get("views") or 0), likes=int(payload.get("likes") or 0), comments=int(payload.get("comments") or 0),
            shares=int(payload.get("shares") or 0), watch_seconds=float(payload["watch_seconds"]) if payload.get("watch_seconds") is not None else None,
            completion_rate=float(payload["completion_rate"]) if payload.get("completion_rate") is not None else None,
            hook_hold_rate=float(payload["hook_hold_rate"]) if payload.get("hook_hold_rate") is not None else None,
            published_at=payload.get("published_at"), metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        )
    except (TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.get("/api/v1/creator-intelligence")
def api_v1_creator_intelligence(request: Request):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return creator_intelligence_service.creator_profile(user["id"])


@app.get("/api/v1/clips/{clip_id}/quality")
def api_v1_clip_quality(request: Request, clip_id: str, platform: str = Query("")):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    clip = _owned_clip(user["id"], clip_id)
    if not clip:
        return JSONResponse({"error": "clip_not_found"}, status_code=404)
    state = editor_service.get_or_create_edit_state(clip_id)
    data = timeline_service.get_or_create_timeline(clip_id)
    source = Path(clip["source_path"]) if clip["source_path"] else None
    output = Path(clip["video_path"]) if clip["video_path"] else None
    return quality_check_service.inspect(source, state, data, output_path=output, platform=platform or None)


@app.get("/api/v1/projects/{project_id}/media-analysis")
def api_v1_project_media_analysis(request: Request, project_id: str):
    user, redirect = require_login(request)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    project = _owned_project(user["id"], project_id)
    if not project:
        return JSONResponse({"error": "not_found"}, status_code=404)
    source = Path(project["source_path"]) if project["source_path"] else None
    if not source or not source.exists():
        return JSONResponse({"error": "source_unavailable"}, status_code=409)
    try:
        return media_analysis_service.inspect_media(source)
    except Exception as exc:
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)


@app.get("/api/v1/templates/{template_id}/export")
def api_v1_export_template(request: Request, template_id: str):
    user, redirect = require_login(request)
    if redirect: return JSONResponse({"error":"unauthorized"},status_code=401)
    data=studio_template_service.export_template(user["id"],template_id)
    if not data: return JSONResponse({"error":"not_found"},status_code=404)
    return JSONResponse(data,headers={"Content-Disposition":f'attachment; filename="{template_id}.viralclip-template.json"'})

@app.post("/api/v1/templates/import")
def api_v1_import_template(request: Request, payload: dict[str, Any] = Body(...)):
    user, redirect = require_login(request)
    if redirect: return JSONResponse({"error":"unauthorized"},status_code=401)
    try: return studio_template_service.import_template(user["id"],payload)
    except ValueError as exc: return JSONResponse({"error":str(exc)},status_code=400)

@app.get("/api/v1/brand-kits/{kit_id}/export")
def api_v1_export_brand_kit(request: Request, kit_id: str):
    user, redirect = require_login(request)
    if redirect: return JSONResponse({"error":"unauthorized"},status_code=401)
    data=brand_kit_service.export_brand_kit(user["id"],kit_id)
    if not data: return JSONResponse({"error":"not_found"},status_code=404)
    return JSONResponse(data,headers={"Content-Disposition":f'attachment; filename="{kit_id}.viralclip-brand.json"'})

@app.post("/api/v1/brand-kits/import")
def api_v1_import_brand_kit(request: Request, payload: dict[str, Any] = Body(...)):
    user, redirect = require_login(request)
    if redirect: return JSONResponse({"error":"unauthorized"},status_code=401)
    try: return brand_kit_service.import_brand_kit(user["id"],payload)
    except ValueError as exc: return JSONResponse({"error":str(exc)},status_code=400)


@app.get("/api/v1/projects/{project_id}/ask")
def api_v1_project_ask(request: Request, project_id: str, q: str = Query(...)):
    user, redirect = require_login(request)
    if redirect: return JSONResponse({"error":"unauthorized"},status_code=401)
    project=_owned_project(user["id"],project_id)
    if not project: return JSONResponse({"error":"not_found"},status_code=404)
    path=Path(project["transcript_path"]) if project["transcript_path"] else None
    if not path or not path.exists(): return JSONResponse({"error":"transcript_unavailable"},status_code=409)
    try: transcript=json.loads(path.read_text(encoding="utf-8"))
    except Exception: return JSONResponse({"error":"transcript_invalid"},status_code=500)
    return semantic_search_service.answer_from_transcript(transcript,q)
