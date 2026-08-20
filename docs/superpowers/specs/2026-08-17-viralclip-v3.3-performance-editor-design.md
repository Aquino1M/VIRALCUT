# ViralClip Studio V3.3 — Performance Editor Design

Date: 2026-08-17
Status: Design approved in conversation; written-spec review pending
Base: ViralClip Studio V3.2 Hybrid Worker Edition

## 1. Goal

Turn the current editor into a responsive, reliable, professional timeline editor while preserving or improving final output quality. Editing and preview must become lightweight and GPU-assisted where available; heavy processing stays in the Local Worker. The original media remains the source of truth for final export.

Primary outcomes:
- no multi-minute wait to switch layouts;
- edits shown in the editor must match the rendered/downloaded video;
- real Save/Autosave with revisioned snapshots;
- working Preview Render and Final Render jobs;
- CTA/overlay manipulation must be fluid and removable;
- timeline must become an actual editing surface, not just a visual representation;
- 480p proxy for editor playback by default, with adaptive lower/higher proxy only for performance needs;
- final render uses native/original source quality (1080p when project target is 1080p, higher when configured and source allows it);
- browser/WebGPU/WebGL handles interactive preview; Local Worker/FFmpeg handles high-quality and final renders.

## 2. Product quality rule

The editor may reduce **preview resolution or preview-only effect fidelity** to maintain responsiveness, but it must never silently reduce final export quality.

Required UI copy:

> Visualização em baixa qualidade • O clipe final será em resolução nativa.

The original source file is immutable from the editor's perspective. Proxy generation creates derived media and never replaces the original.

## 3. Architecture

### 3.1 Browser Editor Runtime

Responsibilities:
- timeline interaction;
- canvas composition;
- 480p proxy playback;
- caption/text/CTA/image/overlay transforms;
- layout composition without invoking FFmpeg;
- WebGPU effects when available;
- WebGL fallback;
- Canvas/DOM fallback where needed;
- selection, snapping, drag, resize, trim, split, keyboard shortcuts;
- local in-memory editor state;
- lightweight preview quality adaptation.

### 3.2 Local Worker

Responsibilities:
- proxy generation;
- source ingest/download;
- transcription;
- scene detection;
- face tracking and tracking cache;
- B-roll/asset preparation;
- waveform generation;
- high-quality preview renders;
- final renders using original media;
- persistent render/job queue;
- hardware detection and encoder selection;
- quality checks before final render.

### 3.3 No FFmpeg for normal editor interaction

The following operations must not invoke FFmpeg synchronously:
- changing layout;
- dragging or resizing CTA/text/image/overlay;
- changing caption style;
- changing project aspect ratio;
- moving playhead;
- selecting timeline items;
- trimming visual item bounds in the UI;
- toggling visibility/mute/lock;
- changing crop/scale/position in the editor.

FFmpeg is reserved for proxy creation, requested high-quality preview, and final render.

## 4. Proxy system

### 4.1 Default proxy

Default editor proxy: 480p-equivalent preserving project aspect ratio and frame timing.

Examples:
- 9:16 -> approximately 270x480 or 480x854 depending encoder policy;
- 16:9 -> approximately 854x480;
- 1:1 -> approximately 480x480.

The exact dimensions must preserve aspect ratio and use encoder-friendly even dimensions.

### 4.2 Adaptive preview

The system may temporarily drop interactive preview below 480p if measured frame time is too high, and may use 720p on sufficiently capable systems. This adaptation affects only preview.

### 4.3 Proxy cache

Proxy key includes:
- source content hash;
- source trim/range if applicable;
- rotation/orientation normalization version;
- proxy profile version.

A valid cached proxy is reused across sessions and projects using the same source where safe.

### 4.4 Background preparation

After ingest, the Worker prepares in background:
- proxy;
- waveform summary;
- thumbnails/keyframes;
- scene metadata;
- asset metadata needed by the editor.

The editor should open as soon as the minimum usable proxy data is available; secondary caches continue in background.

## 5. EditorSnapshot — single source of truth

All editor-visible state is persisted as one versioned snapshot model.

```text
EditorSnapshot
  revision
  projectId
  composition
  tracks[]
    items[]
  assets[]
  layoutState
  faceTrackRefs
  captionStyleRefs
  updatedAt
```

Each item has a stable ID. Item types include:
- video;
- broll;
- caption;
- text;
- image;
- CTA/overlay;
- SFX;
- music;
- filter/effect;
- transition.

### 5.1 Revision semantics

Every successful save increments `revision`.

A render job stores the exact snapshot revision it renders. A completed render is valid for the current editor only if its revision equals the current saved revision.

If edits exist after the latest render, UI must show:

> Há alterações não renderizadas.

The old render remains available as an older version but is never presented as the current export.

## 6. Save and autosave

### 6.1 Explicit Save

Add a visible **Salvar** button in the editor top bar.

Shortcuts:
- Windows/Linux: Ctrl+S;
- optional future macOS mapping: Cmd+S.

### 6.2 Autosave

Editor actions update local state immediately. Persistence happens in the background using a debounce/coalescing queue.

Autosave must never block dragging, playback, or timeline interaction.

### 6.3 Render barrier

Before Preview Render or Final Render starts:
1. flush pending editor mutations;
2. await a successful snapshot save;
3. obtain saved revision;
4. create the render job against that revision.

This prevents a render from using stale captions/layout/CTA state.

## 7. Preview Render and Final Render

### 7.1 Preview Render

Purpose: fast validation, intentionally lower quality.

Uses:
- proxy media where possible;
- lower bitrate/resolution;
- current saved revision;
- Local Worker job queue.

UI states:
- Salvando;
- Na fila;
- Renderizando;
- Finalizado;
- Falhou;
- Cancelado.

Starting a new preview for the same project may cancel an obsolete queued/running preview when safe.

### 7.2 Final Render

Final Render always uses original/native source media rather than editor proxy.

Target resolution follows project export configuration. For the normal vertical preset it is 1080x1920. Higher native targets may be supported without changing this architecture.

Hardware encoder selection continues to use Worker Hardware Auto and verified fallback:
- NVIDIA -> NVENC when validated;
- AMD -> AMF when validated;
- Intel -> QSV when validated;
- CPU -> libx264 fallback.

### 7.3 Download

`Baixar MP4` downloads only a completed render tied to the intended revision. If no current-revision final render exists, the UI must not imply the old file is current.

## 8. Instant layouts

Changing layouts must become a browser-side composition operation.

The editor reuses:
- current proxy video;
- scene metadata;
- face tracking data;
- crop/identity information.

Layouts include existing ViralClip layouts such as Single, Center, Split, Split Vertical, Tri-Split, React, Podcast, Choquei-style, Header/News and Story/Documentary.

The UI may preload layout definitions and reusable tracking metadata.

Acceptance target: layout visual state should update in the next frame or within a few hundred milliseconds under normal conditions, not minutes.

## 9. Aspect ratio / “Formato real” correction

The current `Formato real` behavior is replaced or repurposed as an explicit **Proporção do projeto** control.

Supported initial options:
- 9:16;
- 1:1;
- 4:5;
- 16:9;
- Original.

Changing ratio updates the browser canvas immediately without waiting for FFmpeg.

Safe zones, captions and overlays must recompute against the selected composition.

## 10. Canvas interaction

Selectable canvas items show:
- selection outline;
- resize handles where applicable;
- remove `×` control for CTA/overlays when selected;
- position guides/safe-zone guides;
- inspector synchronization.

CTA/text/image drag uses compositor-friendly transforms (`translate3d` or equivalent) during interaction. The editor must not rebuild every overlay on every pointer movement.

Use `requestAnimationFrame` for interaction batching and `requestVideoFrameCallback` where available for video-frame synchronized preview.

Persist the final transform after drop/debounce, not on every raw pointer event.

Delete/Backspace removes a selected removable timeline/canvas item after focus-safety checks.

## 11. Timeline Pro editing

The timeline becomes an editor surface similar in interaction quality to professional NLEs, while keeping ViralClip's own UI/design.

### 11.1 Selection

Clicking a timeline block:
- selects it visually;
- sets `selectedItemId`;
- seeks playhead when appropriate;
- highlights the same object on canvas;
- opens its properties in inspector.

Clicking blank timeline clears selection unless a modifier is used.

### 11.2 Track controls

Each track supports, where applicable:
- visibility;
- mute;
- lock;
- height/collapse state.

### 11.3 Editing actions

Initial V3.3 actions:
- drag item in time;
- trim start/end handles;
- split at playhead / razor action;
- delete;
- duplicate;
- copy/paste;
- multi-select;
- snapping;
- ripple behavior for supported source edits;
- markers;
- playhead dragging;
- horizontal timeline zoom;
- timeline scroll;
- undo/redo.

### 11.4 Shortcuts

Initial shortcuts:
- Space: play/pause;
- Ctrl+S: save;
- Ctrl+Z: undo;
- Ctrl+Shift+Z: redo;
- Delete/Backspace: delete selected item;
- Ctrl+C / Ctrl+V: copy/paste supported items;
- S or dedicated razor action: split selected clip at playhead (exact shortcut may avoid collisions with existing shortcuts);
- J/K/L: reverse/pause/forward playback behavior where feasible;
- Ctrl + mouse wheel: horizontal timeline zoom;
- Shift + mouse wheel: horizontal scroll.

Shortcut conflicts must be resolved centrally in one shortcut registry.

## 12. Inspector synchronization

The right inspector follows selection.

Examples:
- caption -> text, timing, font, size, alignment, highlight;
- CTA/text -> content, transform, style, duration;
- B-roll/video -> crop, opacity, speed, volume, source timing;
- music -> volume, fade, ducking;
- SFX -> volume, timing;
- effect/filter -> intensity/configuration.

Inspector edits update local preview immediately and autosave in background.

## 13. Timeline performance

### 13.1 Incremental DOM updates

Do not rebuild the entire timeline for every mutation. Update affected items/tracks.

### 13.2 Virtualization

Only timeline items in or near the visible time range are mounted when projects become large.

### 13.3 Waveform cache

Waveform data is computed once by Worker, stored as a compact summary, and rendered by the browser without re-decoding audio.

## 14. Browser GPU / decoding

Preferred interactive path:
- hardware-accelerated `<video>`/browser decode;
- WebGPU compositor/effects when available;
- WebGL fallback;
- Canvas fallback.

Optional use of WebCodecs may be introduced behind a capability abstraction where it improves frame access without reducing compatibility.

The UI reports actual runtime mode, not aspirational capability:
- Preview: WebGPU / WebGL / Canvas;
- Decode: hardware/standard browser path when detectable;
- Worker encoder: NVENC / AMF / QSV / libx264;
- Proxy resolution;
- final target resolution.

## 15. Adaptive performance mode

The editor measures interactive frame time/FPS.

If responsiveness degrades, it may temporarily:
- lower proxy playback resolution/profile;
- lower preview-only blur quality;
- defer expensive visual filters during drag;
- reduce nonessential redraw frequency.

On interaction end, full preview fidelity returns according to available resources.

This never modifies final render settings.

## 16. Incremental cache / dirty graph

Derived artifacts are keyed by source hash + relevant configuration/version.

Changing only captions must not invalidate:
- transcription;
- face tracking;
- proxy;
- waveform;
- scene detection.

Changing layout must not invalidate tracking if the same source/tracking windows remain valid.

Changing source trim may invalidate only affected derived ranges.

## 17. Face tracking cache

Tracking is stored by source hash and useful time windows/scenes. Layout changes reuse tracking data instead of rerunning analysis.

Browser preview interpolates tracking data locally. Worker performs new tracking only when required source windows are missing/stale.

## 18. Auto Edit remains non-destructive

Auto Edit creates/editable timeline items and decisions. It does not permanently bake B-roll, zoom, SFX, text or captions into the editor source.

Each AI decision can be changed or removed independently.

For B-roll, the inspector may expose reason/confidence, e.g. semantic match tags, so the user can understand why an asset was selected.

Low-confidence B-roll may be skipped in favor of the original camera rather than inserting a poor match.

## 19. Asset prefetch

Once transcription is available, Asset Brain may pre-resolve likely B-roll/SFX candidates for upcoming semantic segments. Prefetch is bounded by disk/cache policy and must not block editor interaction.

## 20. Audio improvements

Keep or improve final quality with:
- speech-aware music ducking;
- fades;
- loudness/limiter checks;
- cached waveform;
- independent SFX/music items on timeline.

Preview may use simplified audio processing when necessary, but final render applies full configured audio chain.

## 21. Quality Check before final export

Before starting or finalizing Final Render, validate:
- required source assets exist;
- no invalid/blank source ranges;
- captions/CTA are not outside required safe zones unless explicitly allowed;
- font/style fallback is known;
- audio chain is valid;
- timeline has no broken asset references;
- sufficient disk space exists;
- target encoder has fallback available.

Nonfatal warnings can be acknowledged. Fatal issues block final render with actionable messages.

## 22. Short high-quality test render

Allow rendering a short range around the playhead (target around 3–5 seconds) at final-quality settings to validate a complex visual effect without rendering the whole clip.

## 23. A/B Auto Edit variants

Architecture supports multiple edit revisions/variants sharing the same heavy cached artifacts. Variants can differ in layout rhythm, B-roll choices, caption style or effect intensity without retranscribing/retracking the source.

This feature must reuse the same snapshot/revision infrastructure and not duplicate original media.

## 24. Before/after comparison

Editor can temporarily bypass Auto Edit visual layers for comparison without mutating the project. This is a preview-only mode.

## 25. Crash recovery

Maintain a lightweight editor journal/recovery record.

On restart after an unclean close, offer recovery of the most recent valid editor state. Recovery must never overwrite a newer explicit save without user confirmation.

## 26. Offline behavior

Already-downloaded/local projects and cached assets remain editable without internet. Features requiring online B-roll/providers or remote model APIs degrade gracefully and clearly.

## 27. Performance telemetry — local diagnostics

Measure locally:
- editor boot time;
- proxy generation time;
- time to first usable frame;
- layout switch latency;
- drag FPS/frame time;
- timeline render/update time;
- transcription time;
- tracking time;
- Auto Edit time;
- preview render time;
- final render time.

Telemetry is diagnostic and local by default. It is used to compare ViralClip versions and prevent regressions.

## 28. Regression benchmark targets

Create repeatable benchmarks/tests for representative projects.

Target behaviors:
- no synchronous FFmpeg call on layout click;
- no full overlay-tree rebuild per pointermove;
- selected timeline item persists visually and logically;
- save barrier always precedes render job creation;
- final render revision equals the saved editor revision used to create the job;
- editor proxy path differs from original final-render source path;
- final target remains 1080p/native according to project settings;
- proxy defaults to 480p class;
- timeline remains interactive with large caption counts through virtualization/incremental updates.

Performance numerical thresholds should be recorded by benchmark environment rather than hard-coded globally, except that UI actions must not block for multi-second FFmpeg renders.

## 29. Render/job priority

Interactive work has higher priority than background work.

Suggested priority order:
1. editor save/metadata operations;
2. short test preview;
3. requested preview render;
4. final render;
5. background proxy/cache prefetch;
6. optional asset enrichment.

Obsolete previews may be cancelled/coalesced.

## 30. Error handling

User-visible errors must identify:
- operation;
- failed backend/component;
- retry/fallback status;
- actionable next step.

The editor must not silently fail a Save, Preview Render, Final Render or Download action.

If WebGPU fails, fall back to WebGL/Canvas. If hardware encode fails, fall back through the verified Worker encoder chain. If a proxy is missing, regenerate it without modifying the original.

## 31. Compatibility and migration

V3.2 projects must open in V3.3.

Migration converts legacy editor state/overlays into the unified snapshot/timeline representation while preserving IDs when possible.

Old rendered files stay available as historical renders; they are not considered current if their revision does not match the migrated current snapshot.

## 32. UI/UX acceptance criteria

The following current problems are considered fixed only when:
- edited captions match the final downloaded render;
- explicit Save persists and survives page reload;
- Preview Render button creates a visible job and completes/fails visibly;
- Final Render button creates a visible job tied to current revision;
- Download retrieves the correct current revision;
- CTA has visible remove control when selected and Delete/Backspace support;
- dragging CTA/text/image is fluid and does not rebuild all overlays per pointer move;
- clicking a timeline card visibly selects it and opens the correct inspector;
- timeline items can be moved/trimmed/split/deleted as supported;
- project ratio selector actually changes composition preview;
- layout changes do not synchronously invoke FFmpeg;
- proxy editor displays low-quality notice;
- final export uses original media and configured native/1080p target;
- editor reports preview/backend mode;
- large timelines remain usable without mounting all items simultaneously.

## 33. Out of scope for this V3.3 implementation

To keep V3.3 focused, these are not required for completion:
- replacing the entire Python/FastAPI stack with another backend;
- cloud GPU rendering as the primary path;
- removing the Local Worker architecture;
- copying proprietary UI/source code from other editors;
- requiring WebGPU with no fallback;
- changing final quality downward for performance.

## 34. Testing strategy

Implementation follows test-first changes for bug fixes/features where practical.

Required test groups:
- EditorSnapshot revision/save tests;
- render save-barrier tests;
- render-current-revision/download tests;
- proxy/original separation tests;
- layout-no-FFmpeg regression tests;
- aspect ratio behavior tests;
- timeline selection/edit action tests;
- CTA remove/drag state tests;
- cache invalidation tests;
- migration tests;
- worker job priority/cancellation tests;
- quality check tests;
- browser JS syntax/unit tests available in project tooling;
- FFmpeg smoke tests using proxy and original paths;
- extracted-ZIP verification before delivery.

## 35. Delivery criteria

V3.3 is deliverable only after:
- full existing + new automated suite passes;
- Python compile checks pass;
- frontend JS checks pass;
- real proxy generation smoke test passes;
- real preview render smoke test passes;
- real final 1080x1920 render using original source passes;
- snapshot revision/render consistency is verified;
- ZIP is created from the verified tree;
- extracted ZIP repeats the critical test suite/smokes;
- package inspection confirms no user media, database, secrets, cache, `.env`, font binaries or private credentials are shipped.
