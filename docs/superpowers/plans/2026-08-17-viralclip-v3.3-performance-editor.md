# ViralClip V3.3 Performance Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the ViralClip editor responsive and revision-safe by using a cached 480p proxy for interactive playback, browser-side layouts, a real editable timeline, and render jobs tied to a saved editor snapshot while preserving native quality for final export.

**Architecture:** Browser owns interactive preview state and never invokes FFmpeg for normal editing. Local Worker generates/reuses a 480p proxy and performs requested preview/final renders. Editor state, captions, overlays and timeline are saved as one revisioned snapshot; render jobs record the revision they consume.

**Tech Stack:** FastAPI, SQLite, Python, FFmpeg, vanilla JS/CSS, HTML5 video, WebGPU/WebGL capability detection.

## Global Constraints
- Default editor proxy is 480p-equivalent and never replaces the original source.
- Final render always uses original/native media and existing hardware encoder selection/fallback.
- Required UI copy: “Visualização em baixa qualidade • O clipe final será em resolução nativa.”
- Layout/aspect/drag/timeline interaction must not synchronously invoke FFmpeg.
- Existing V3.2 projects remain readable.

---

### Task 1: Revisioned EditorSnapshot and Render Barrier
**Files:** `app/db.py`, `app/services/editor.py`, `app/services/render_queue.py`, `app/main.py`, `tests/test_v33_editor_snapshot.py`
**Produces:** `save_editor_snapshot(clip_id, state, cues, timeline) -> dict`, monotonically increasing revision, render records tied to revision.
- [ ] Add failing tests for revision increments, atomic cues/timeline save, and render revision persistence.
- [ ] Add idempotent database columns for `clip_edits.revision` and `clip_renders.editor_revision`.
- [ ] Implement snapshot save/read and render queue revision binding.
- [ ] Add API endpoint for atomic editor snapshot save.
- [ ] Run targeted tests and commit.

### Task 2: 480p Proxy Service and Interactive Source
**Files:** `app/services/proxy_media.py`, `app/main.py`, `app/templates/editor.html`, `tests/test_v33_proxy.py`
**Produces:** cached proxy path keyed by source/range, `/clips/{id}/editor-proxy` endpoint.
- [ ] Add failing proxy geometry/cache tests.
- [ ] Implement even-dimension 480p proxy generation using fast encoder settings and original trim range.
- [ ] Stream cached proxy to editor while leaving final source unchanged.
- [ ] Add required low-quality/native-quality UI notice.
- [ ] Run targeted tests and commit.

### Task 3: Browser-Side Layout, Aspect Ratio, Overlay Performance
**Files:** `app/static/editor.js`, `app/static/style.css`, `app/templates/editor.html`, `tests/test_v33_editor_runtime.py`
**Produces:** instant layout switching, actual project ratio control, selected overlay with X/delete, transform-only drag.
- [ ] Add failing source-contract tests ensuring layout click no longer reloads `/clean-video` and ratio options exist.
- [ ] Replace layout reload with browser composition state update.
- [ ] Add 9:16, 1:1, 4:5, 16:9, Original ratio control.
- [ ] Add selected overlay state, delete X and keyboard delete.
- [ ] Make drag update only selected element with requestAnimationFrame/translate3d; persist on pointerup.
- [ ] Run targeted tests and commit.

### Task 4: Timeline Pro Interaction
**Files:** `app/static/editor.js`, `app/static/style.css`, `app/templates/editor.html`, `tests/test_v33_timeline_ui.py`
**Produces:** persistent selected timeline item, inspector, playhead, drag, trim handles, delete, split, zoom, Ctrl+wheel and Shift+wheel behavior.
- [ ] Add failing UI contract tests.
- [ ] Add selection and inspector synchronization.
- [ ] Implement timeline drag and trim with local state updates, snap and save-on-release.
- [ ] Implement split/delete/duplicate and keyboard shortcuts.
- [ ] Add timeline zoom/scroll controls and visual playhead.
- [ ] Run targeted tests and commit.

### Task 5: Save/Render/Download Reliability and Preview Quality
**Files:** `app/static/editor.js`, `app/templates/editor.html`, `app/services/render.py`, `app/services/timeline_render.py`, `tests/test_v33_render_revision.py`
**Produces:** visible Save button, render waits for save, preview lower resolution/bitrate, final current-revision download only.
- [ ] Add failing tests for preview geometry and current revision behavior.
- [ ] Add explicit Save button and async `flushEditorSnapshot()`.
- [ ] Make preview/final buttons await snapshot flush and pass expected revision.
- [ ] Make preview use proxy-quality output; final remains native target.
- [ ] Mark stale render and disable/label download until current revision final exists.
- [ ] Run targeted tests and commit.

### Task 6: Performance Guardrails, Quality Check, Recovery and Release
**Files:** `app/static/editor.js`, `app/static/style.css`, `app/services/quality_check.py`, `app/main.py`, `VERSION`, `docs/V3.3_RELEASE_NOTES.md`, `tests/test_v33_release_contract.py`
**Produces:** WebGPU/WebGL status, adaptive preview hint, lightweight quality check, crash-recovery journal metadata, V3.3 release package.
- [ ] Add failing release/performance contract tests.
- [ ] Add browser capability/performance indicator and reduced-effects-during-drag behavior.
- [ ] Add final-render preflight quality checks for missing media/invalid durations/out-of-bounds captions/overlays.
- [ ] Add lightweight local recovery journal in browser storage keyed by clip/revision.
- [ ] Update version/docs and run full test suite, compileall and JS syntax validation.
- [ ] Package tracked source without user data, extract ZIP, rerun tests and smoke checks.
