# ViralClip Studio V3 Asset Brain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Windows-local ViralClip V3 that auto-detects NVIDIA/AMD/Intel/CPU, starts from one BAT, exposes a versioned local API, maintains a reusable ~2 GB asset library, and uses transcript-aware Auto Edit to place B-roll/SFX/music/effects on a non-destructive timeline.

**Architecture:** Preserve the proven FastAPI/FFmpeg V2.2 pipeline and add focused V3 services rather than replacing the entire application at once. The editable source of truth becomes a schema-v3 timeline stored per clip; Auto Edit generates timeline items using a local asset catalog, and the renderer compiles supported timeline items into the final FFmpeg render. Online stock providers are optional and require user-owned API keys; procedural effects/SFX and user-imported assets work offline.

**Tech Stack:** Python 3.10–3.12, FastAPI, SQLite, FFmpeg/ffprobe, OpenCV, Jinja/vanilla JS editor, httpx, yt-dlp, faster-whisper/DirectML, optional Pexels/Pixabay APIs.

## Global Constraints

- Preserve all V2.2 routes and workflows.
- No proprietary Real Oficial code/assets are copied.
- No font binaries are bundled in the ZIP.
- Initial asset library target is `2 GB` and enforced as a hard downloader budget.
- NVIDIA uses NVENC/CUDA when available; AMD uses AMF/DirectML/Vulkan-capable paths when available; Intel uses QSV/OpenVINO-capable paths when available; CPU always remains a fallback.
- `VIRALCLIP.bat` is the single normal entry point for install/repair/diagnose/start.
- Stock APIs are optional and only activated with user-provided keys.
- Auto Edit always produces an editable plan before final render.

---

### Task 1: Universal hardware manager and encoder router
**Files:** Create `app/services/hardware.py`; modify `app/services/render.py`, `app/config.py`; test `tests/test_v3_hardware.py`.
**Interfaces:** Produces `detect_capabilities() -> dict`, `recommended_profile(capabilities) -> dict`, and universal `video_encoder_args` support.
- [ ] Add failing tests for NVIDIA/AMD/Intel/CPU detection using mocked command output.
- [ ] Implement detection and recommendation logic.
- [ ] Add NVENC/QSV/AMF encoder argument branches and auto selection.
- [ ] Run tests and commit.

### Task 2: Single Windows launcher
**Files:** Create `VIRALCLIP.bat`, `tools/bootstrap.py`; modify README; test `tests/test_v3_launcher.py`.
**Interfaces:** `python tools/bootstrap.py [start|repair|diagnose|update|safe]`.
- [ ] Add failing launcher contract tests.
- [ ] Implement Python bootstrap and thin BAT wrapper.
- [ ] Make first-run install idempotent and hardware-aware.
- [ ] Run tests and commit.

### Task 3: Schema-v3 timeline persistence
**Files:** Create `app/services/timeline.py`; modify `app/db.py`, `app/services/editor.py`; test `tests/test_v3_timeline.py`.
**Interfaces:** `get_or_create_timeline(clip_id)`, `save_timeline(clip_id, timeline)`, `timeline_from_edit_state(...)`.
- [ ] Write failing schema/migration tests.
- [ ] Add `clip_timelines` table and schema validation.
- [ ] Seed tracks for video/captions/broll/sfx/music/effects/text/overlays.
- [ ] Run tests and commit.

### Task 4: Asset library and 2 GB starter pack manager
**Files:** Create `app/services/assets.py`, `tools/install_asset_pack.py`, `data/assets/.gitkeep`; modify config; test `tests/test_v3_assets.py`.
**Interfaces:** `scan_assets()`, `search_assets(query, kind, limit)`, `register_asset(...)`, `starter_pack_status()`, `install_starter_pack(...)`.
- [ ] Add failing indexing/search/budget tests.
- [ ] Implement manifest/catalog, synonym-aware ranking and license metadata.
- [ ] Add procedural local SFX/effects/background generation and optional Pexels/Pixabay download adapters.
- [ ] Enforce 2 GB maximum downloaded library size.
- [ ] Run tests and commit.

### Task 5: Transcript-aware Auto Edit planner
**Files:** Create `app/services/auto_edit.py`; modify timeline service; test `tests/test_v3_auto_edit.py`.
**Interfaces:** `build_auto_edit_plan(clip_id, style, intensity, options) -> dict`.
- [ ] Add failing tests for phrase segmentation and B-roll/SFX/effect placement.
- [ ] Implement semantic keyword/concept extraction with optional LLM refinement.
- [ ] Add pacing/safety rules preventing over-editing.
- [ ] Persist generated plan as timeline items/markers.
- [ ] Run tests and commit.

### Task 6: Timeline-aware render compiler
**Files:** Create `app/services/timeline_render.py`; modify `render_queue.py`; test `tests/test_v3_timeline_render.py`.
**Interfaces:** `compile_timeline_render(...)` maps B-roll/effects/audio tracks into FFmpeg-compatible state.
- [ ] Add failing render-plan tests.
- [ ] Implement B-roll overlay/full-frame cuts, zoom/effect expressions and SFX/music audio mixing for local assets.
- [ ] Preserve captions/layout/Brand Kit layers.
- [ ] Run tests and commit.

### Task 7: API v1 and worker-ready capabilities
**Files:** Modify `app/main.py`; create `app/services/api_v1.py`; test `tests/test_v3_api.py`.
**Interfaces:** `/api/v1/health`, `/api/v1/capabilities`, `/api/v1/assets`, `/api/v1/clips/{id}/timeline`, `/api/v1/clips/{id}/auto-edit`.
- [ ] Add failing endpoint tests.
- [ ] Implement authenticated local API endpoints.
- [ ] Return stable schema/version fields for future Vercel worker bridge.
- [ ] Run tests and commit.

### Task 8: Editor Pro controls for Auto Edit and media library
**Files:** Modify `app/templates/editor.html`, `app/static/editor.js`, `app/static/style.css`; test `tests/test_v3_editor_ui.py`.
**Interfaces:** UI invokes API v1, shows Auto Edit plan, multi-track lanes and asset search.
- [ ] Add failing HTML/JS contract tests.
- [ ] Add Auto Edit style/intensity controls and Asset Library panel.
- [ ] Add multi-track plan preview and apply/undo actions.
- [ ] Run tests and commit.

### Task 9: Project-level automatic Auto Edit
**Files:** Modify `app/templates/new_project.html`, `app/services/projects.py`, `app/services/jobs.py`; test `tests/test_v3_project_auto_edit.py`.
**Interfaces:** New project settings `auto_edit_enabled/style/intensity` trigger plan+render after clip creation.
- [ ] Add failing settings/pipeline tests.
- [ ] Add creation controls and normalized defaults.
- [ ] Generate Auto Edit timeline after captions exist and rerender using timeline compiler.
- [ ] Run tests and commit.

### Task 10: Release verification and ZIP
**Files:** Modify VERSION, README, release notes; add `docs/V3_RELEASE_NOTES.md`.
- [ ] Run complete pytest suite.
- [ ] Run compileall.
- [ ] Run real FFmpeg smoke render when ffmpeg is available.
- [ ] Inspect package for `.env`, database, cache, git metadata, and font binaries.
- [ ] Create ZIP from tracked release files, extract to fresh directory and repeat tests.
