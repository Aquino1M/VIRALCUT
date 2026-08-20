# ViralClip AI Editor V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Upgrade the current FastAPI/Jinja ViralClip MVP into a local-first production-style short-form editor with playable clip cards, visual captions/layouts, individual and bulk editing, presets, overlays, proxy previews, render queue, and export tools.

**Architecture:** Keep FastAPI + Jinja + SQLite and the current background processing pipeline. Add focused editor services for captions, layouts, fonts, overlays, preview/cache, and editor state; expose JSON endpoints for live editor operations while preserving existing HTML routes. Final rendering remains FFmpeg-first with `h264_amf` preferred and libx264 fallback.

**Tech Stack:** Python 3.10+, FastAPI, Jinja2, SQLite, FFmpeg/libass, Pillow, vanilla JavaScript/CSS, pytest.

## Global Constraints

- Preserve existing projects/clips and existing creation flow.
- Keep Windows local-first operation and RX 580 `h264_amf` preference.
- Final output remains 1080x1920 for vertical projects; preview may be lower resolution.
- Default heavy final render concurrency is 1.
- Do not redistribute proprietary font binaries; open fonts are optional installer downloads.
- Preserve graceful CPU fallbacks and human-readable errors.
- Do not require React, cloud render, or social publishing APIs.

---

### Task 1: Database migration and editor domain model
**Files:** `app/db.py`, `app/services/editor.py`, `tests/test_editor_state.py`
**Produces:** clip edit state, caption cues, presets, renders, project source assets, overlay assets, safe migrations.
- [x] Write failing migration/editor-state tests.
- [x] Verify RED.
- [x] Implement idempotent schema extensions and editor-state helpers.
- [x] Verify GREEN and full suite.

### Task 2: Caption preset registry and ASS renderer
**Files:** `app/services/captions.py`, `tests/test_captions.py`
**Produces:** built-in preset registry, validated config merging, cue grouping, ASS generation with Portuguese accents and per-word highlighting.
- [x] Write failing caption tests.
- [x] Verify RED.
- [x] Implement caption registry/config/ASS helpers.
- [x] Verify GREEN and full suite.

### Task 3: Layout preset registry and filtergraphs
**Files:** `app/services/layouts.py`, `tests/test_layouts.py`
**Produces:** Auto, Single, Center, Split, Split Vertical, Tri-Split, Tri-Split Top, Quad, Six-Split, React, Brainrot, Talking Head+B-roll, Top/Bottom Podcast layouts.
- [x] Write failing layout tests.
- [x] Verify RED.
- [x] Implement deterministic render-safe filtergraphs with fallback geometry.
- [x] Verify GREEN and full suite.

### Task 4: Font manager and installer
**Files:** `app/services/fonts.py`, `tools/install_fonts.py`, `install_fonts.bat`, `tests/test_fonts.py`
**Produces:** system/open font registry, local data/fonts metadata, non-fatal installer.
- [x] Write failing resolution/registry tests.
- [x] Verify RED.
- [x] Implement font detection and metadata.
- [x] Verify GREEN and full suite.

### Task 5: Render pipeline, preview cache, overlay composition
**Files:** `app/services/render.py`, `app/services/preview.py`, `app/services/overlays.py`, `tests/test_editor_render_pipeline.py`
**Produces:** settings-hashed previews, ASS captions, layout filters, CTA/logo/text overlays, AMF fallback, concise errors/logs.
- [x] Write failing render-command/cache tests.
- [x] Verify RED.
- [x] Implement modular render composition.
- [x] Verify GREEN and full suite.

### Task 6: Project creation defaults and ingestion UX
**Files:** `app/main.py`, `app/templates/new_project.html`, `app/services/ingest.py`, `tests/test_project_defaults.py`
**Produces:** provider classification for YouTube/Twitch/Kick/Drive/local, accepted extensions, project defaults, validation.
- [x] Write failing API/default tests.
- [x] Verify RED.
- [x] Implement normalized defaults and provider classification.
- [x] Verify GREEN and full suite.

### Task 7: Project workspace and clip library
**Files:** `app/main.py`, `app/templates/project.html`, `app/static/style.css`, `tests/test_project_workspace.py`
**Produces:** playable video cards with audio, score/duration/time/reason/download, sorting/filtering/pagination, real-format toggle, selection, Download All ZIP, project metadata/actions.
- [x] Write failing route/template tests.
- [x] Verify RED.
- [x] Implement routes and responsive workspace.
- [x] Verify GREEN and full suite.

### Task 8: Individual editor and live preview
**Files:** `app/templates/editor.html`, `app/static/editor.js`, `app/static/style.css`, `app/main.py`, `tests/test_editor_api.py`
**Produces:** 3-column editor, caption/layout/text/brand/export tabs, instant caption preview, presets, controls, safe zones, transport, autosave/undo/redo.
- [x] Write failing API/template tests.
- [x] Verify RED.
- [x] Implement editor APIs and UI.
- [x] Verify GREEN and full suite.

### Task 9: Caption timeline, Brand Kit, presets, bulk editor
**Files:** `app/main.py`, `app/templates/editor.html`, `app/templates/bulk_editor.html`, `app/static/editor.js`, `app/static/bulk.js`, `tests/test_bulk_and_presets.py`
**Produces:** editable cues, split/merge/shift, overlay assets/config, user presets, bulk apply/render.
- [x] Write failing persistence/bulk tests.
- [x] Verify RED.
- [x] Implement endpoints/UI.
- [x] Verify GREEN and full suite.

### Task 10: Render queue, technical info, regression and packaging
**Files:** `app/services/render_queue.py`, `app/main.py`, `README.md`, `ARQUITETURA.md`, `run.bat`, `install.bat`, tests.
**Produces:** queued preview/final renders with progress, technical metadata, robust packaging and Windows instructions.
- [x] Write failing queue/status tests.
- [x] Verify RED.
- [x] Implement queue/status/metadata and docs.
- [x] Run all tests, compileall, template smoke tests, package ZIP.


## Implementation Verification

- [x] Full pytest suite passes: 65 tests, 0 failures.
- [x] `python -m compileall -q app tools` succeeds.
- [x] Real FFmpeg smoke render validates video+audio, editor layout, ASS captions, overlay composition, progress callbacks, and 1080x1920 final output.
- [x] Packaging excludes runtime databases, credentials, caches, Git metadata, virtual environments, and font binaries.
