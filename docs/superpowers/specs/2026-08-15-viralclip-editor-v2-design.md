# ViralClip AI — Editor V2 Design

Date: 2026-08-15
Status: Approved by user and implemented in the V2 sandbox branch

## 1. Goal

Transform the current functional ViralClip MVP into a production-style short-form video editor focused on three workflows:

1. Generate and review AI-selected clips.
2. Edit one clip with live visual preview.
3. Apply the same visual treatment to many clips with a bulk editor.

The upgrade must preserve the current local-first Python/FastAPI pipeline and AMD RX 580 acceleration path while substantially improving caption styling, layout presets, previews, downloads, and editing ergonomics.

## 2. Success criteria

A user should be able to:

- open a completed project and immediately play each cut with audio;
- see start time, end time, duration, AI score, title and reason on each card;
- download a rendered MP4 directly from the card;
- open an individual editor with a 9:16 player and adjust captions/layout without guessing;
- preview caption and layout changes before a full final render;
- choose from visual caption preset cards instead of a plain select box;
- change caption font, colors, casing, position, line height, spacing, stroke, timing and animation;
- edit transcript words/phrases and timing on a caption timeline;
- choose video layouts such as Single, Center, Split, Split Vertical, Tri-Split, Tri-Split Top, Quad, Six-Split, React, Brainrot and Auto;
- save custom presets;
- apply settings to selected clips or all clips in a project;
- render final files using AMD AMF when available;
- keep the app usable on the target i5-4590 / RX 580 / 16 GB RAM machine without saturating the CPU unnecessarily;
- create a project from YouTube, Twitch, Kick, Google Drive or a local video file;
- keep fast low-quality/proxy previews separate from native-resolution final renders;
- manage large projects with filtering, sorting, pagination and bulk selection;
- create a new clip manually or import additional media into an existing project;
- save project-level defaults for prompt, language, aspect ratio, layout, caption preset and overlay/brand treatment;
- add logos, watermarks, CTA bars and other reusable overlays through project templates.

## 3. Existing project constraints

The current application is FastAPI + Jinja + SQLite. Video work is performed with FFmpeg, transcription is local, and jobs run in a thread pool. The existing `clips` table stores one rendered video path and thumbnail per clip, while project-wide rendering choices are currently stored in `projects.settings_json`.

The V2 design should extend these patterns rather than replace the stack with a heavy SPA framework.

## 3.1 Source ingestion and project creation

The project-creation flow should support the source types shown in the supplementary reference:

- YouTube URL;
- Twitch URL;
- Kick URL;
- Google Drive URL;
- local upload by click or drag-and-drop.

Initial accepted local formats:

- MP4;
- MOV;
- MKV;
- AVI.

The UI should enforce configurable safety limits, initially targeting up to 10 hours or 10 GB per source, and show a clear source-validation state before the expensive transcription pipeline starts.

The ingestion layer must normalize every source into a local canonical media asset plus metadata so the rest of the pipeline does not care where the source came from.

For remote sources, download adapters should be isolated by provider. A provider failure must not break local-file projects.

### Project-creation defaults

The creation flow should store project-level defaults that are later inherited by generated clips:

- AI prompt / clipping intent;
- goal (`shorts`, manual/sequential where applicable);
- preferred clip-duration policy;
- start/end source range;
- language;
- target language(s), when translation is enabled later;
- aspect ratio;
- default video layout;
- default caption preset;
- default caption font;
- emoji preference;
- CTA/overlay preference.

These defaults remain editable after project creation.

## 4. Architecture

### 4.1 Backend modules

Keep FastAPI as the HTTP layer, but split editing responsibilities into focused services:

- `app/services/captions.py`
  - caption word/page model;
  - ASS generation;
  - style-to-ASS conversion;
  - per-word highlight events;
  - safe-area/position calculations.

- `app/services/layouts.py`
  - layout preset registry;
  - speaker panel definitions;
  - crop/panel geometry;
  - FFmpeg filtergraph generation.

- `app/services/fonts.py`
  - local font registry;
  - open-license font installer/downloader metadata;
  - system-font detection;
  - font path resolution for FFmpeg and browser preview.

- `app/services/editor.py`
  - load/save clip edit state;
  - merge preset + clip overrides;
  - create preview render requests;
  - bulk apply operations.

- `app/services/render.py`
  - remain the final render entry point;
  - delegate layout and caption filter generation to the new focused modules;
  - keep AMD AMF selection/fallback.

- `app/services/preview.py`
  - generate short low-cost preview assets;
  - cache preview by settings hash;
  - invalidate when visual settings change.

### 4.2 UI approach

Continue Jinja templates with lightweight vanilla JavaScript. Add stateful editor behavior through JSON API endpoints rather than rebuilding the entire product in React.

The editor page becomes a 3-column desktop workspace:

- left: presets/assets/layouts;
- center: 9:16 video preview;
- right: controls for the active tab;
- bottom: caption timeline and transport controls.

On smaller screens, collapse the left/right panels into tabbed drawers.

## 5. Data model

### 5.1 `clip_edits`

One row per clip containing the current editable state.

Fields:

- `clip_id` primary key / FK;
- `caption_preset_id`;
- `layout_preset_id`;
- `caption_config_json`;
- `layout_config_json`;
- `overlay_config_json`;
- `updated_at`.

### 5.2 `caption_cues`

Store editable caption segments/words independently of the source transcript.

Fields:

- `id`;
- `clip_id`;
- `start_time`;
- `end_time`;
- `text`;
- `word_index`;
- `speaker_id` optional;
- `confidence` optional;
- `created_at` / `updated_at`.

This allows the user to correct text/timing without modifying the project's original Whisper transcript.

### 5.3 `user_presets`

Fields:

- `id`;
- `user_id`;
- `preset_type` (`caption`, `layout`, `combined`);
- `name`;
- `config_json`;
- `created_at`;
- `updated_at`.

### 5.4 `clip_renders`

Do not overwrite the only existing render while experimenting.

Fields:

- `id`;
- `clip_id`;
- `kind` (`preview`, `final`);
- `status`;
- `progress`;
- `settings_hash`;
- `video_path`;
- `created_at`.

The `clips.video_path` column remains the canonical current final render for compatibility.

## 6. Caption system

### 6.1 Preset gallery

Initial built-in presets:

- Green Fresh;
- Rainbow Fun;
- Cariani-inspired;
- MrBeast-inspired;
- Podcast Bold;
- Minimal Clean;
- Karaoke;
- Word Pop;
- Classic Subtitle;
- Neon;
- Breaking/News;
- Clean Box.

Each preset card shows a small animated browser preview using the same config schema used by rendering.

### 6.2 Caption configuration schema

Editable fields:

- `fontFamily`;
- `fontSize`;
- `fontWeight`;
- `textCase`: original / upper / lower;
- `align`: left / center / right;
- `positionX`;
- `positionY`;
- `maxWidth`;
- `maxLines`;
- `wordsPerPage`;
- `lineHeight`;
- `letterSpacing`;
- `primaryColor`;
- `secondaryColor` / active-word color;
- `strokeColor`;
- `strokeWidth`;
- `shadowColor`;
- `shadowDepth`;
- optional background box color/opacity/radius;
- `pageDurationMs`;
- `minWordDurationMs`;
- `animationType`;
- `animationDuration`;
- `scaleAmount`;
- `popScalePeak`;
- `popFontSizeBoost`;
- `popDurationMs`;
- `fadeInMs`;
- `fadeOutMs`;
- `enableEmojis`.

### 6.3 Source-inspired defaults

The initial Green Fresh preset should mirror the supplied reference values where applicable:

- Bangers;
- 75 px target font size;
- uppercase;
- white primary text;
- green `#76FF03` active color;
- black stroke;
- stroke width 10;
- centered;
- one line by default;
- 3 words per page;
- 900 ms page duration;
- scaling/word-pop behavior;
- scale amount 0.4;
- pop peak 1.1;
- pop size boost 0.24;
- pop duration 1000 ms.

These become editable defaults, not hardcoded behavior.

### 6.4 Rendering technology

Use ASS/libass instead of plain SRT for advanced captions.

Why:

- per-word timing;
- font selection;
- outline/shadow;
- precise screen position;
- color changes;
- karaoke-like highlighting;
- multiple lines;
- animation tags where practical.

For effects unsupported or unreliable in ASS, generate layered drawtext/overlay events only when needed.

### 6.5 Live preview

Two tiers:

1. **Instant browser preview** — CSS/JS overlays above the HTML `<video>` element update immediately when the user changes font/position/color/timing controls.
2. **Rendered preview** — a button generates a 4–8 second FFmpeg sample around the current playhead using the exact final pipeline.

This keeps the UI responsive while still offering an authoritative render check.

## 7. Font manager

### 7.1 Font policy

Do not redistribute proprietary font binaries in the project ZIP.

The installer/runtime may:

- detect system fonts already installed on Windows;
- download approved open-license fonts from their official or trusted upstream source;
- store downloaded fonts under `data/fonts/`;
- register those paths with FFmpeg/libass;
- store metadata in `data/fonts/fonts.json`.

### 7.2 Initial open-license font set

Target open equivalents/useful creator fonts such as:

- Bangers;
- Anton;
- Montserrat;
- Bebas Neue;
- Oswald;
- Roboto Condensed;
- Archivo Black;
- League Spartan;
- Permanent Marker where appropriate.

For fonts such as Arial, Arial Black, Impact or Comic Sans, use the Windows-installed font when present rather than distributing it.

### 7.3 Installer behavior

Add `install_fonts.bat` and a Python helper. It should be idempotent, verify files, and never fail the main app installation solely because one optional font cannot be downloaded.

## 8. Video layouts

### 8.1 Preset registry

Built-ins:

- Auto;
- Single;
- Center;
- Split;
- Split Vertical;
- Tri-Split;
- Tri-Split Top;
- Quad;
- Six-Split;
- React;
- Brainrot;
- Talking Head + secondary B-roll panel;
- Top/Bottom Podcast.

### 8.2 Layout schema

Each layout contains one or more panels:

- normalized or pixel position;
- width/height;
- crop rectangle;
- border radius;
- border/color;
- background blur;
- assigned speaker/source;
- face tracking enabled;
- z-index.

### 8.3 Speaker-aware layouts

For split/react layouts:

- use detected face/speaker metadata where available;
- otherwise use face tracking from sampled frames;
- otherwise fall back to deterministic center crops.

The first version should not depend on perfect diarization to render successfully.

## 9. Project workspace, clip cards and playback

### 9.1 Project header

A completed project should expose:

- source thumbnail;
- project title;
- source/channel label when known;
- source duration;
- number of generated clips;
- project creation date;
- `Open original` action;
- share action;
- `New clip` action;
- `Import videos` action;
- bulk `Select` mode.

`New clip` opens a manual cutter against the project's source media. `Import videos` adds extra source assets to the same project without creating an unrelated project.

### 9.2 Proxy preview versus final output

The project page should explicitly distinguish:

- fast/low-quality preview assets used for browsing and editing;
- native-resolution final renders used for download/export.

A `Real format` viewing mode should preserve the actual target aspect ratio in clip cards.

This proxy/final split is important for large projects and lower-end hardware.

### 9.3 Clip management controls

Large projects should support:

- page-size choices (initially 12 / 24 / 36 / 48 / 60 / 72 / 84 / 96);
- pagination;
- filter by all / rendered / not rendered;
- distribution/status filters reserved for future publishing integration;
- sort by AI score;
- sort by source time;
- sort by duration;
- sort by title;
- total clip count;
- responsive card grid;
- bulk selection across the current filter result.

Publishing-oriented statuses such as scheduled/published may exist in the data model but should not require social publishing APIs in V2.

### 9.4 Clip card

Each completed clip card should include:

- playable HTML5 video with audio;
- poster thumbnail;
- duration badge;
- score badge;
- title;
- hook/reason;
- source time range;
- render status;
- buttons: Play, Edit, Download;
- optional checkbox for bulk selection.

When available, keep waveform metadata and render variants attached to the clip model so the UI can later expose richer timeline/audio controls without reprocessing the entire source.

The player must use the existing authenticated video endpoint so no extra copy is needed.

## 10. Individual editor

### 10.1 Tabs

Left/right editing controls should expose:

- Captions;
- Layout;
- Text/CTA;
- Brand Kit;
- Export.

### 10.2 Transport

- Play/pause;
- current time / total duration;
- ±5s / ±10s seek shortcuts;
- volume;
- timeline scrubber;
- loop preview segment.

### 10.3 Caption timeline

Bottom timeline shows caption cues as blocks.

Capabilities:

- click a cue to edit text;
- drag start/end handles;
- split cue;
- merge adjacent cues;
- shift cue timing;
- jump video playhead to cue;
- optional word-level view when word timestamps are available.

For V2, editing can be implemented using numeric/timeline handles without a full nonlinear editing engine.

## 10.4 Layered overlays and Brand Kit

V2 should support reusable visual overlays without becoming a full freeform compositor.

Supported overlay types:

- logo;
- watermark;
- CTA bar;
- headline/title bar;
- static image;
- simple text;
- optional background shape.

Each overlay stores:

- source asset;
- start/end or full-clip duration;
- x/y position;
- width/height;
- opacity;
- z-index;
- optional crop;
- optional border radius.

Project templates can combine:

- caption preset;
- layout preset;
- logos/watermarks;
- CTA/title bars;
- safe-zone positions.

This lets the user create reusable styles for pages, podcasts or campaigns and apply them to many clips.

### 10.5 Lightweight layered timeline model

The underlying edit state should be track-aware even though V2 is not a full nonlinear editor.

Track types:

- video/layout;
- captions;
- text;
- overlay/image;
- CTA/title.

Track state supports:

- visible/hidden;
- locked/unlocked;
- muted where audio-bearing;
- ordered z-index/layer priority.

This makes later editor growth possible without rewriting saved project files.

## 11. Bulk editor

Access from the project page.

Actions:

- select all / none;
- choose target clips;
- apply caption preset;
- apply caption config overrides;
- apply layout preset;
- change crop/layout mode;
- enable/disable captions;
- apply overlay/title style;
- save as preset;
- queue preview or final renders.

Bulk operations update edit-state rows first. Rendering is a separate explicit action so changing a style does not immediately consume CPU/GPU for every clip.

## 12. Render queue and performance

### 12.1 Queue

Replace direct ad-hoc rerender with a render job abstraction that supports:

- queued;
- rendering;
- done;
- error;
- percent progress.

### 12.2 RX 580

Continue to prefer `h264_amf` when available.

Preview renders should use a speed-focused AMF preset and reduced bitrate/resolution when practical. Final renders remain 1080x1920.

### 12.3 CPU limits

- avoid running multiple heavy FFmpeg final renders concurrently on this PC;
- default final-render concurrency to 1;
- allow lightweight thumbnail/metadata work in parallel;
- preserve limited CPU-thread configuration for CPU fallback transcription.

### 12.4 Cache

Hash the effective edit configuration. Reuse an existing preview if source clip + edit state has not changed.

## 13. API endpoints

Proposed routes:

- `GET /clips/{clip_id}/editor-state`
- `PUT /clips/{clip_id}/editor-state`
- `GET /clips/{clip_id}/captions`
- `PUT /clips/{clip_id}/captions`
- `POST /clips/{clip_id}/preview-render`
- `POST /clips/{clip_id}/final-render`
- `GET /clips/{clip_id}/renders/{render_id}`
- `GET /clips/{clip_id}/download`
- `GET /api/caption-presets`
- `GET /api/layout-presets`
- `GET /api/fonts`
- `POST /presets`
- `POST /projects/{project_id}/bulk-edit`
- `POST /projects/{project_id}/bulk-render`

Existing routes remain compatible where possible.

## 14. Error handling

- Return human-readable rendering errors without dumping the entire FFmpeg banner into the UI.
- Save full FFmpeg stderr to a local log file for diagnosis.
- If a requested font is unavailable, fall back to an installed default and show a warning.
- If AMF render fails, retry once with libx264 and show that CPU fallback was used.
- If a complex layout cannot resolve a speaker/face, fall back to center crop instead of failing the job.
- If preview render fails, preserve editor state so the user does not lose changes.

## 15. Testing strategy

### Unit tests

- caption config validation;
- ASS escaping;
- color conversion;
- caption cue grouping;
- layout filter generation;
- FFmpeg filter escaping;
- font resolution;
- settings hashing;
- database migrations.

### Integration tests

- create project -> render clip -> play/download;
- edit caption -> preview render -> final render;
- bulk apply -> state persisted across clips;
- AMF command generation;
- libx264 fallback;
- layout presets on landscape source;
- captions with accented Portuguese characters.

### UI smoke tests

- project card contains `<video controls>`;
- duration and download action displayed;
- editor loads presets;
- instant preview changes when style controls change;
- save editor state endpoint persists values.

## 16. Additional improvements included

Beyond the requested scope, V2 should include:

- project-level “default style” so newly generated clips inherit the preferred caption/layout preset;
- favorite presets;
- duplicate preset;
- before/after reset per section;
- keyboard shortcuts in the editor;
- undo/redo for editor-state changes in the browser session;
- safe-zone guides for TikTok/Reels UI;
- autosave indicator;
- export filename sanitization based on clip title;
- “download all rendered clips” ZIP action;
- batch render progress on project page;
- technical info drawer showing encoder used, resolution, file size and render time;
- optional waveform data generation for a more useful caption timeline later;
- source-provider adapters for YouTube/Twitch/Kick/Google Drive;
- project source metadata panel with original-link access;
- low-resolution proxy generation and native-final render separation;
- manual `New clip` workflow from an existing source;
- import-additional-video workflow within an existing project;
- reusable combined project templates (caption + layout + overlays);
- optional logo/watermark/CTA asset library;
- large-project filters, sorting, page-size selection and pagination.

## 17. Non-goals for this iteration

To avoid turning V2 into a full Premiere/CapCut clone, this iteration will not include:

- arbitrary multi-track media import;
- freeform frame-by-frame keyframing;
- music library/licensing;
- full motion graphics compositor;
- social network publishing APIs (status fields may be reserved, but V2 does not need to publish);
- cloud render farm/orchestration.

These can be separate future phases.

## 18. Implementation order

1. Database migration + editor/project-default state model.
2. Source-ingestion adapters and project creation flow.
3. Proxy/final asset model and preview pipeline.
4. Font manager and caption preset registry.
5. ASS caption generator and tests.
6. Layout preset registry and FFmpeg builders.
7. Overlay/Brand Kit model and combined project templates.
8. Project workspace: metadata, New Clip, Import Videos, filters, sort, pagination, player/download.
9. Individual editor shell + instant preview.
10. Layered caption/overlay timeline editing.
11. Preview/final render queue.
12. Bulk editor.
13. Additional UX improvements and regression tests.

## 19. Acceptance checklist

The V2 is complete when:

- existing project creation still works;
- old clips still open and download;
- every clip card can play audio/video;
- duration is shown correctly;
- the caption preset gallery has visual previews;
- Green Fresh matches the supplied reference configuration closely;
- font selection works with downloaded/open fonts and Windows system fonts;
- position/size/colors/timing can be changed and previewed;
- individual editor saves state;
- at least 10 layout presets render without filter errors;
- bulk apply changes multiple selected clips;
- preview render is cached by settings hash;
- final render uses AMF on compatible RX 580 setup and falls back safely;
- all new automated tests pass;
- project creation accepts local files plus supported remote-link source adapters;
- local upload validates accepted formats and configured size/duration limits;
- proxy preview and native final render are clearly separated;
- project page supports New Clip, Import Videos and bulk Select modes;
- project workspace filters, sorts and paginates large clip collections;
- project defaults propagate to newly generated clips;
- reusable combined templates can include captions, layout and logo/watermark/CTA overlays;
- existing projects remain readable after the migration.
