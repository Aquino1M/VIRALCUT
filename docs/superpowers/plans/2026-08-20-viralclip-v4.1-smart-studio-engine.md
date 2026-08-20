# ViralClip V4.1 Smart Studio Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver ViralClip V4.1 with a repaired Windows launcher, Smart Director scene decisions, ViralScore 2.0, final render cache, reusable templates/brand kits, publishing workflow, analytics and performance modes while preserving V3.4 compatibility.

**Architecture:** Extend the existing local-first FastAPI/SQLite/FFmpeg system instead of replacing it. New subsystems are small services with owned-resource APIs; the current timeline remains the editor source of truth and the existing render queue remains the only final-render executor.

**Tech Stack:** Python 3.10–3.12, FastAPI, Jinja2, SQLite, vanilla JavaScript/CSS, FFmpeg/FFprobe.

**Spec:** `docs/superpowers/specs/2026-08-20-viralclip-v4.1-smart-studio-engine-design.md`

## Global Constraints

- Windows-first and local-first.
- One heavy render at a time.
- Existing V3.4 DBs/routes remain compatible.
- Proxy/performance settings never lower final output quality.
- Publishing is a truthful local queue; no fake external posting.

---

### Task 1: Windows launcher + release contract

**Files:** Modify `VIRALCLIP.bat`, `tools/bootstrap.py`, `VERSION`; create `docs/V4.1_RELEASE_NOTES.md`; test `tests/test_v41_release_contract.py`, `tests/test_v41_windows_bootstrap.py`.

**Interfaces:** `VIRALCLIP.bat` invokes `tools/bootstrap.py`; bootstrap keeps modes `start|repair|diagnose|update|safe`.

- [ ] Write failing release/launcher tests.
- [ ] Run focused tests and confirm failure.
- [ ] Replace the batch wrapper with a minimal ASCII launcher and update version strings/release notes.
- [ ] Run focused tests to green.

### Task 2: Database migrations + domain services

**Files:** Modify `app/db.py`; create `app/services/viral_score.py`, `app/services/studio_templates.py`, `app/services/brand_kits.py`, `app/services/publishing.py`, `app/services/performance.py`; test `tests/test_v41_domain_services.py`.

**Interfaces:**
- `viral_score.score_clip_payload(payload) -> dict`
- `studio_templates.create/list/get/apply/delete`
- `brand_kits.create/list/get/apply/delete`
- `publishing.enqueue/list/update_status`
- `performance.resolve_mode(profile, override='auto') -> dict`

- [ ] Write failing migration/service tests.
- [ ] Verify RED.
- [ ] Add idempotent tables/columns and minimal services.
- [ ] Verify GREEN.

### Task 3: Smart Director + render cache

**Files:** Modify `app/services/auto_edit.py`, `app/services/timeline_render.py`, `app/services/render_queue.py`; test `tests/test_v41_smart_director.py`, `tests/test_v41_render_cache.py`.

**Interfaces:** Auto Edit produces `effects` items with `type='director-layout'`; render queue reuses completed finals with same revision/hash and existing file.

- [ ] Write failing Smart Director and cache tests.
- [ ] Verify RED.
- [ ] Add director-layout decisions and final-cache lookup.
- [ ] Add renderer support for scene-layout base rendering without changing downstream B-roll/effects APIs.
- [ ] Verify GREEN and existing render tests.

### Task 4: API/UI for templates, brand kits, publishing and analytics

**Files:** Modify `app/main.py`, `app/templates/base.html`, `app/templates/templates.html`, `app/templates/brand_kit.html`, `app/templates/project.html`, `app/templates/editor.html`, `app/static/editor.js`, `app/static/style.css`; create `app/templates/publish.html`, `app/templates/analytics.html`; test `tests/test_v41_studio_routes.py`.

**Interfaces:** Owned-resource endpoints under `/api/v1/templates`, `/api/v1/brand-kits`, `/api/v1/publish`; pages `/publish`, `/analytics`.

- [ ] Write failing route/UI tests.
- [ ] Verify RED.
- [ ] Add routes and truthful local workflow pages.
- [ ] Add apply actions in project/editor and sidebar/mobile nav.
- [ ] Verify GREEN.

### Task 5: ViralScore backfill + project command center

**Files:** Modify `app/main.py`, `app/services/jobs.py`, `app/templates/project.html`, `app/templates/videos.html`; test `tests/test_v41_command_center.py`.

**Interfaces:** Clips expose parsed `analysis` and workflow status; project filters support `ready|rendering|rendered|scheduled|published|error` while old filters remain accepted.

- [ ] Write failing score/filter tests.
- [ ] Verify RED.
- [ ] Score newly created clips and lazily backfill old clips.
- [ ] Add workflow filters/status summary.
- [ ] Verify GREEN.

### Task 6: Full regression + package

**Files:** Modify `README.md`, `ARQUITETURA.md`, `SOURCES.md` as needed.

- [ ] Run `python -m pytest -q`.
- [ ] Run Python compile checks.
- [ ] Inspect ZIP for excluded runtime/cache/user media.
- [ ] Create `ViralClip_Studio_V4.1_Smart_Studio_Engine_Windows.zip`.
- [ ] Re-extract package into a clean verification directory and run full tests again.
