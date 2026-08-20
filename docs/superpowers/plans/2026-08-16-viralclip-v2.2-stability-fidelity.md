# ViralClip AI V2.2 Stability & Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make layout changes visibly and reliably affect previews/final renders, make captions render with the same controls shown in the editor, speed up face tracking, support real aspect ratios, and recover interrupted jobs safely on Windows.

**Architecture:** Keep the existing FastAPI/SQLite/FFmpeg application and replace the weak boundaries rather than rewrite the app. Introduce explicit output geometry, cache fingerprints, time-window face activity, resilient queue state, and an ASS caption compiler whose output is covered by behavior tests. The editor uses clean source media plus overlays; FFmpeg previews/finals consume the same saved edit state.

**Tech Stack:** Python 3.10–3.12, FastAPI, SQLite, OpenCV/YuNet/Haar, FFmpeg/ASS, vanilla JS/Jinja, pytest.

## Global Constraints

- Preserve Windows `.bat` workflow and local-only processing.
- Face tracking remains always enabled with safe fallback.
- AMD RX 580 render acceleration continues through `h264_amf`, with `libx264` fallback.
- Do not package font binaries, secrets, `.env`, databases, caches, or virtual environments.
- Existing V2.1 behavior stays compatible unless replaced by the approved V2.2 behavior.
- Use TDD for every production behavior change.

---

### Task 1: Output geometry and real aspect ratios

**Files:**
- Modify: `app/services/render.py`
- Modify: `app/services/layouts.py`
- Modify: `app/services/projects.py`
- Modify: `app/templates/editor.html`
- Modify: `app/templates/project.html`
- Test: `tests/test_v22_aspect_ratio.py`

**Interfaces:**
- Produces `resolve_output_geometry(aspect_ratio, preview=False) -> tuple[int, int]`.
- `build_layout_filter(..., output_size=(w,h))` renders every layout into requested geometry.

- [ ] Write tests for 9:16, 4:5, 1:1, 16:9 final/preview geometry and layout filters ending at requested size.
- [ ] Run tests and verify RED.
- [ ] Implement geometry resolver and thread it through render plans/layout filters.
- [ ] Update editor/project technical labels to display real geometry.
- [ ] Run focused tests and full suite.
- [ ] Commit.

### Task 2: Layout cache invalidation and faithful editor preview

**Files:**
- Modify: `app/main.py`
- Modify: `app/services/render.py`
- Modify: `app/static/editor.js`
- Test: `tests/test_v22_clean_cache.py`
- Test: `tests/test_v22_editor_layout_preview.py`

**Interfaces:**
- Produces `edit_state_fingerprint(state, tracking, aspect_ratio) -> str`.
- Clean layout previews use fingerprinted cache files and cannot reuse a stale layout.

- [ ] Write tests proving two layout states produce different cache targets and clean-video responses invalidate when layout changes.
- [ ] Run tests and verify RED.
- [ ] Implement fingerprinted cache and a lightweight layout-preview endpoint.
- [ ] Update editor layout cards to request/render a real 3–4 second FFmpeg preview after layout changes while retaining instant geometry ghost.
- [ ] Run focused tests and full suite.
- [ ] Commit.

### Task 3: Faster sequential face tracking and activity windows

**Files:**
- Modify: `app/services/face_tracking.py`
- Test: `tests/test_v22_face_tracking.py`

**Interfaces:**
- Produces `iter_sampled_frames(cap, native_fps, sample_fps)` without repeated random seeks.
- Produces `track_activity_at(track, t, window=1.0) -> float` and `rank_tracks_at(tracking, t) -> list[track]`.

- [ ] Write tests for sequential sample indices, stable timestamps, and time-window activity ranking.
- [ ] Run tests and verify RED.
- [ ] Replace per-timestamp `cap.set` loop with sequential frame decoding/skipping.
- [ ] Add per-window activity helpers and diagnostics.
- [ ] Run focused tests, timing smoke test, and full suite.
- [ ] Commit.

### Task 4: Layout Engine 2.0 fallbacks and dynamic podcast

**Files:**
- Modify: `app/services/layouts.py`
- Test: `tests/test_v22_layout_engine.py`

**Interfaces:**
- `build_layout_filter(..., tracking=..., output_size=..., clip_duration=...)` returns valid FFmpeg graph.
- Podcast dynamic can change active track by time using tracking activity.

- [ ] Write tests that one-face Quad/Six-Split use distinct context roles, two-face Podcast Dynamic contains time-dependent switching, and branded layouts produce dedicated geometry.
- [ ] Run tests and verify RED.
- [ ] Implement role recipes per layout and time-dependent dynamic composition.
- [ ] Ensure all 17 layouts produce valid graphs for zero, one, two, and three tracks.
- [ ] Run focused tests, FFmpeg smoke renders, and full suite.
- [ ] Commit.

### Task 5: Caption Engine 2.0 fidelity

**Files:**
- Modify: `app/services/captions.py`
- Modify: `app/static/editor.js`
- Test: `tests/test_v22_caption_engine.py`

**Interfaces:**
- ASS compiler honors `maxLines`, `wordsPerPage`, `pageDurationInMilliseconds`, `lineHeight`, `animationType`, pop/scale timing, fade, background, karaoke, rainbow, case, alignment, and position.

- [ ] Write snapshot-style semantic tests for generated ASS tags/events for static, word-pop, scaling, karaoke, rainbow, line wrapping, background and timing.
- [ ] Run tests and verify RED.
- [ ] Implement shared page/timing logic and ASS effects.
- [ ] Align browser preview timing/style with compiler semantics.
- [ ] Run focused tests and full suite.
- [ ] Commit.

### Task 6: Project polling and durable job recovery

**Files:**
- Modify: `app/templates/project.html`
- Modify: `app/services/jobs.py`
- Modify: `app/services/render_queue.py`
- Modify: `app/main.py`
- Test: `tests/test_v22_job_recovery.py`
- Test: `tests/test_v22_project_polling.py`

**Interfaces:**
- Startup recovery marks stale `processing` jobs as recoverable/error and never leaves indefinite in-memory state.
- Project page reloads once on terminal transition, not every poll after first clip.

- [ ] Write tests reproducing repeated reload condition and stale project/render state.
- [ ] Run tests and verify RED.
- [ ] Change polling to incremental status display and one-time terminal reload.
- [ ] Implement startup recovery and safe requeue/retry metadata.
- [ ] Run focused tests and full suite.
- [ ] Commit.

### Task 7: Windows installer and diagnostics hardening

**Files:**
- Modify: `install.bat`
- Modify: `setup_amd_gpu.bat`
- Modify: `diagnostico.bat`
- Modify: `tools/check_acceleration.py`
- Test: `tests/test_v22_windows_setup.py`

**Interfaces:**
- Installer selects compatible Python before creating `.venv`.
- Diagnostics report Python, FFmpeg, AMF, DirectML, tracking backend/model, yt-dlp, and font status.

- [ ] Write textual contract tests for required script branches/messages.
- [ ] Run tests and verify RED.
- [ ] Harden scripts and diagnostics.
- [ ] Run focused tests and full suite.
- [ ] Commit.

### Task 8: End-to-end verification and release package

**Files:**
- Modify: `README.md`
- Modify: `VERSION`
- Create: `docs/V2.2_RELEASE_NOTES.md`
- Test: `tests/test_v22_release_contract.py`

**Interfaces:**
- Release ZIP is self-contained source/config/scripts, excludes runtime/private artifacts.

- [ ] Add release contract test and run RED.
- [ ] Update docs/version/release notes.
- [ ] Run full pytest suite and `python -m compileall app tools`.
- [ ] Render representative layouts/captions/aspect ratios using FFmpeg and supplied sample videos.
- [ ] Build ZIP from tracked files only, extract it, rerun tests/compile checks from extracted package.
- [ ] Inspect ZIP for forbidden artifacts.
- [ ] Commit release metadata.
