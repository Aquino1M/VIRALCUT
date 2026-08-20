# ViralClip V4.1 — Smart Studio Engine Design

## Goal

Turn the existing V3.4 local-first editor into a cohesive end-to-end Smart Studio without replacing the proven FastAPI/SQLite/FFmpeg architecture. V4.1 must keep the Local Worker as the only heavy-media executor, make editing decisions visible and editable, reuse final renders when the editor snapshot did not change, and add project-level templates, brand kits, publishing queue, and analytics.

## Constraints

- Windows-first, local-first.
- Python 3.10–3.12.
- Existing FastAPI + Jinja + SQLite stack stays in place.
- Existing FFmpeg render pipeline remains the source of final video pixels.
- One heavy render at a time on baseline/basic PCs.
- Final output quality is never reduced by proxy/editor performance mode.
- Existing V3.4 project databases must migrate idempotently.
- No external social API is required for V4.1; publishing is a local queue/workflow that can later receive platform adapters.
- Existing V3.4 routes and project data remain compatible.

## Architecture

### 1. Windows bootstrap repair

`VIRALCLIP.bat` becomes a minimal ASCII wrapper. All complex setup logic remains in `tools/bootstrap.py`, preventing CMD parsing/encoding issues. Bootstrap exposes clear stages, supports start/repair/diagnose/update/safe, and avoids reinstalling dependencies when the dependency fingerprint is unchanged.

### 2. ViralScore 2.0

A deterministic local scorer computes 0–100 plus sub-scores for Hook, Curiosity, Emotion, Controversy, Clarity, Shareability, Comment potential and estimated Retention. It uses the existing clip score as a prior, then adjusts from title/hook/reason/caption text and duration. Results are stored as JSON on the clip and shown in project cards/analytics.

### 3. Smart Director / scene decisions

Auto Edit keeps its existing B-roll/SFX/music/filter/zoom decisions and additionally creates `director-layout` decisions on the effects track. Decisions are based on speaker changes from caption cues, strong phrases, duration and available tracking. They remain editable timeline items. The renderer understands these items as scene-level layout directives; when present, it renders the affected layout segments and concatenates them into a base before applying captions, overlays, B-roll, SFX/music and effects.

### 4. Caption Engine 3.0 metadata

Caption cues gain optional `highlight` and `emoji` persistence. Existing word-level start/end/speaker/confidence remains compatible. Built-in caption presets gain modern viral variants while continuing to resolve through the same caption engine.

### 5. Final render cache / Render Manager

The existing immutable editor snapshot hash is extended to final renders. If the current editor revision and settings hash already have a completed final render whose file still exists, the render queue returns it immediately instead of starting FFmpeg again. The same status API/download flow remains unchanged.

### 6. Templates

A new `studio_templates` table stores reusable combined editing templates for each user. A template may include caption preset/config, layout preset/config, overlays, tracks and auto-edit defaults. Templates can be created, duplicated, deleted and applied to a clip or multiple clips. The `/templates` page becomes a real manager rather than only a gallery of built-ins.

### 7. Brand Kits

A new `brand_kits` table stores named kits with colors/fonts/default CTA and references to existing `brand_assets`. Users can create/edit/delete kits. A project can have `brand_kit_id` and `template_id` defaults; applying a kit updates editor overlays/default caption font without baking pixels until render.

### 8. Project Command Center

Project cards retain pagination/content-visibility behavior and gain filter states for ready/rendering/rendered/scheduled/published/error. Cards display ViralScore breakdown summary and workflow status. Bulk selection can apply a Studio Template, Brand Kit, Auto Edit and enqueue final renders.

### 9. Publishing queue

A `publish_queue` table stores clip, target platform, scheduled time, caption text and status (`draft`, `scheduled`, `ready`, `published`, `error`). V4.1 does not fake platform publishing: it provides the workflow, export-ready file checks and status tracking. A future adapter can consume the queue.

### 10. Viralytics

`/analytics` aggregates local project/clip/render/publish data: projects, clips, rendered clips, average ViralScore, render time, encoder distribution, publish status and top clips. It does not claim external social views unless those are explicitly imported later.

### 11. Performance modes

A local performance policy maps hardware profile to `basic`, `balanced`, or `performance`. It controls proxy resolution, browser preload/card density, and optional model warm-up only. It never changes final output geometry/bitrate policy. Users can override the mode in Hardware.

## Data migrations

Add columns:
- `clips.analysis_json TEXT NOT NULL DEFAULT '{}'`
- `projects.brand_kit_id TEXT`
- `projects.template_id TEXT`
- `users.performance_mode TEXT NOT NULL DEFAULT 'auto'`
- `caption_cues.highlight INTEGER NOT NULL DEFAULT 0`
- `caption_cues.emoji TEXT`

Add tables:
- `studio_templates`
- `brand_kits`
- `publish_queue`

All migrations are idempotent through `init_db()`.

## Error handling

- Missing template/brand kit: 404 for owned resources.
- Render cache entry with missing file: treated as cache miss.
- Stale editor revision: existing 409 contract remains.
- Smart Director with no cues/tracking: falls back to current Auto Edit behavior and a single layout decision.
- Publishing queue never marks an item published automatically without an explicit action.
- Bootstrap optional acceleration/assets failures warn and continue; Python/venv/core dependency failures remain fatal.

## Verification

- Existing 260 tests remain green.
- New tests cover bootstrap wrapper contract, migrations, ViralScore, Smart Director layout decisions, final render reuse, templates/brand kits ownership/apply, publishing queue and analytics routes.
- Release contract checks VERSION 4.1.0, V4.1 notes, new sidebar routes, and absence of manual render buttons in editor.
