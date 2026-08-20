# ViralClip AI V2.1 Tracking & Layouts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate duplicated captions and make every video layout render as a real face-aware composition, with layout selection before project processing.

**Architecture:** Add a cached project-level face-analysis service, store clean clip media separately from final burned renders, and feed sliced face tracks into a declarative FFmpeg layout engine. The UI chooses the default layout during project creation and treats face tracking as always enabled with graceful center-crop fallback.

**Tech Stack:** Python 3.10+, FastAPI, SQLite, OpenCV, FFmpeg/FFprobe, Jinja2, vanilla JavaScript, pytest.

## Global Constraints

- Target hardware: i5-4590, RX 580 8 GB, 16 GB RAM.
- Heavy project/render jobs remain serialized.
- Face analysis is cached once per project and must have a no-face/model-missing fallback.
- No model/font binaries are bundled in the ZIP.
- Final render continues to prefer `h264_amf` and fall back to `libx264`.
- Face tracking is not user-disableable in V2.1.

---

### Task 1: Clean editor media path

**Files:**
- Modify: `app/db.py`
- Modify: `app/services/render.py`
- Modify: `app/services/jobs.py`
- Modify: `app/main.py`
- Modify: `app/templates/editor.html`
- Test: `tests/test_clean_editor_media.py`

**Interfaces:**
- Produces: `clips.clean_path`, `render_clean_clip(...)`, `/clips/{clip_id}/clean-video`.

- [ ] Write failing tests proving editor media resolves to a clean clip and legacy clips lazily generate one from source.
- [ ] Run tests and verify RED.
- [ ] Add idempotent `clean_path` column and clean render helper that applies layout only, no captions/overlays.
- [ ] Generate/store clean clip during project processing before final render.
- [ ] Add clean-video endpoint with lazy generation for legacy projects and point editor player at it.
- [ ] Run focused tests and full existing tests.
- [ ] Commit.

### Task 2: Project-level face tracking service

**Files:**
- Create: `app/services/face_tracking.py`
- Create: `tools/install_tracking_models.py`
- Modify: `app/config.py`
- Modify: `install.bat`
- Modify: `diagnostico.bat`
- Test: `tests/test_face_tracking.py`

**Interfaces:**
- Produces: `analyze_video(video_path, out_path, fps=4.0) -> dict`, `load_tracks(path)`, `slice_tracks(data,start,end)`, `tracking_summary(data)`.

- [ ] Write failing unit tests for box normalization, association, smoothing, track slicing and empty fallback schema.
- [ ] Run RED.
- [ ] Implement detector abstraction with YuNet first and Haar fallback.
- [ ] Implement low-FPS sampling, deterministic track association, exponential smoothing and lightweight activity score.
- [ ] Add model installer that fetches YuNet from official OpenCV Zoo at install time; failure stays non-fatal.
- [ ] Run focused tests.
- [ ] Commit.

### Task 3: Cache tracking during project processing

**Files:**
- Modify: `app/db.py`
- Modify: `app/services/jobs.py`
- Modify: `app/main.py`
- Test: `tests/test_project_tracking_pipeline.py`

**Interfaces:**
- Produces: `projects.tracking_path`, `projects.tracking_summary_json`, authenticated `/api/projects/{id}/tracking`.

- [ ] Write failing tests that project settings/status expose cached tracking and processing calls analysis once per project.
- [ ] Run RED.
- [ ] Add DB columns and run face analysis after ingest/thumbnail before transcription.
- [ ] Persist tracking path/summary and add status endpoint.
- [ ] Ensure face-analysis exceptions degrade to empty tracking data instead of failing project.
- [ ] Run focused/full tests.
- [ ] Commit.

### Task 4: Face-aware layout engine

**Files:**
- Replace/modify: `app/services/layouts.py`
- Modify: `app/services/render.py`
- Test: `tests/test_face_aware_layouts.py`
- Test: `tests/test_layouts.py`

**Interfaces:**
- Consumes: sliced tracking dictionary.
- Produces: `build_layout_filter(layout_id, tracking=..., start=..., duration=..., config=...)`.

- [ ] Write failing tests for all preset IDs, unique panel crops, auto resolution, and two-face split behavior.
- [ ] Run RED.
- [ ] Expand preset registry with `podcast-dynamic`, `choquei-movimento`, `header-news`, `story-documentary`.
- [ ] Implement deterministic crop descriptors from tracks plus alternate context crops when tracks are fewer than panels.
- [ ] Generate valid FFmpeg graphs for every layout and keep center/no-face fallback.
- [ ] Feed tracking data from project into clean/preview/final renders.
- [ ] Run filter-graph unit tests and FFmpeg smoke tests.
- [ ] Commit.

### Task 5: Creation-time visual layout picker and always-on tracking UI

**Files:**
- Modify: `app/templates/new_project.html`
- Modify: `app/templates/editor.html`
- Modify: `app/static/editor.js`
- Modify: `app/static/style.css`
- Test: `tests/test_v21_layout_ui.py`

**Interfaces:**
- Produces: visual radio-card input named `layout_preset_id`; read-only face tracking status in editor.

- [ ] Write failing template/UI tests for card picker, new presets, clean-video player URL and absence of tracking Off control.
- [ ] Run RED.
- [ ] Build layout-card picker with miniature panel diagrams and hidden radio state.
- [ ] Replace face tracking select with status card that fetches project tracking summary.
- [ ] Update instant layout preview for new preset geometries.
- [ ] Run tests.
- [ ] Commit.

### Task 6: Real-video regression smoke tests and Windows packaging

**Files:**
- Create: `tests/test_v21_smoke_render.py`
- Modify: `README.md`
- Modify: `VERSION`

**Interfaces:**
- Validates real FFmpeg output for representative layouts and clean editor media.

- [ ] Add smoke test using generated synthetic two-person-like/color-region source so CI is self-contained.
- [ ] Run real FFmpeg renders for `single`, `split`, `podcast-dynamic`, `choquei-movimento`, `header-news`.
- [ ] Run fresh full `pytest -q` and `python -m compileall app tools`.
- [ ] Test selected layouts against at least one supplied reference video as source media where practical.
- [ ] Update docs/version/install notes.
- [ ] Package only tracked project files into `ViralClip_AI_V2.1_Windows.zip` and smoke-test the extracted ZIP.
- [ ] Commit final packaging/docs changes.
