# ViralClip AI V2.1 — Face Tracking & Functional Layouts Design

Date: 2026-08-15
Status: Approved by user

## Goal

Fix the duplicated captions in the editor and replace the current geometry-only layout system with a reusable face-aware reframing pipeline. The chosen layout must be selectable before project processing so generated clips are rendered in the requested visual format from the start, while still remaining changeable later in the editor.

## Root causes being fixed

1. The editor currently plays the already-rendered `clips.video_path`, which already has captions burned in, and then draws editable captions over the player. This produces duplicate captions.
2. Current split/grid layouts duplicate the same source input and center-crop every panel. They do not use people/tracks, so different panels often show the same region and cannot follow speakers.
3. Face tracking is optional UI state even though the product behavior requires it as the default safety mechanism for people-focused layouts.

## Pipeline architecture

### Clean clip proxy

Every generated clip receives a clean, uncaptioned, unbranded proxy asset derived from the source range. The editor always previews this clean asset plus HTML overlays. Final/preview render jobs burn captions and overlays exactly once.

`clips.clean_path` stores the clean 1080x1920/base-layout clip used by the editor. `clips.video_path` remains the latest final downloadable render. Existing V2 projects without `clean_path` lazily generate one from the project source when the editor is opened.

### Face analysis

A new `app/services/face_tracking.py` module analyzes the canonical project source once and writes `data/tracks/<project_id>.json`.

Detector priority:

1. OpenCV YuNet (`FaceDetectorYN`) when the downloaded ONNX model is available.
2. OpenCV Haar cascade fallback, bundled through the installed OpenCV package.

MediaPipe is not a hard dependency because the Windows target may use Python versions for which MediaPipe wheels are unavailable. The tracking interface stays detector-agnostic so MediaPipe can be added later without changing layout code.

The analyzer samples frames at a configurable interval (default 4 fps for analysis), detects faces, assigns stable track IDs with IoU + center-distance matching, and smooths boxes with exponential smoothing. Tracks include time, normalized box, center, size, confidence and a lightweight activity score based on mouth/lower-face motion when available.

Face analysis must not block successful processing: if the model is missing or no faces are found, the pipeline records an empty track file and all layouts fall back to deterministic center crops.

### Track reuse

Tracking is project-level and runs once after ingestion, before transcription/rendering. Every generated clip uses the same track file sliced to its source time range. Changing layout later in the editor reuses the saved tracks; it does not re-analyze the video.

## Layout engine

`app/services/layouts.py` becomes a declarative preset registry plus a renderer that can generate FFmpeg crop expressions from face tracks.

Every preset must produce a real, distinct composition:

- `auto`: chooses `single` for one dominant face, `podcast-dynamic` for two persistent faces, otherwise `center`.
- `single`: one full-height crop following the dominant/active face.
- `center`: contained source over blurred background.
- `split`: two horizontal panels with different tracked people/crops.
- `split-vertical`: two vertical panels with separate tracked people.
- `tri-split`: three horizontal tracked panels.
- `tri-split-top`: two tracked top panels + one large tracked bottom panel.
- `quad`: four tracked/alternate crops.
- `six-split`: six tracked/alternate crops.
- `react`: 30/70 composition with different subjects/crops.
- `brainrot`: two different crops; if only one person exists, lower panel uses a wider/context crop rather than duplicating the exact crop.
- `talking-broll`: 70/30 talking head + context crop.
- `podcast-top-bottom`: two-person 50/50 tracked podcast.
- `podcast-dynamic`: two-person layout with active-speaker emphasis; when activity confidence is weak it behaves as stable 50/50.
- `choquei-movimento`: wide/context top or upper panel, red editable title bar in the middle, tracked close-up lower panel, matching the supplied reference video structure.
- `header-news`: persistent header area for image/title plus tracked speaker video below.
- `story-documentary`: main media/context region plus narrator/presenter picture-in-picture area.

When there are fewer tracked people than panels, the engine cycles through semantically different crops: dominant face, secondary face, wider context, left context, right context and source-contain. It must never create multiple panels with identical center crops unless no other valid crop is possible.

## Temporal reframing

For layouts with a single dominant person, the renderer creates time-segmented crop states from the saved tracks and smooths transitions. The crop center is clamped to frame bounds and limited in movement per analysis step to avoid jitter.

The first implementation can use piecewise FFmpeg crop expressions generated from sampled/smoothed centers. It does not require GPU inference.

## Project creation UI

The `Layout padrão` select becomes visual layout cards before project submission. The selected `layout_preset_id` is stored in project settings and used by initial clip rendering.

Face tracking is always enabled for people-aware layouts and is no longer exposed as an Off setting. The editor displays a read-only status (`Face tracking ativo`, track count/fallback state).

## Editor behavior

The editor player source is the clean clip endpoint, never the already-burned final render. HTML caption overlays are therefore shown exactly once.

Switching layouts updates the instant geometry preview and render state. The Face Tracking control becomes a status card showing detector, track count and fallback mode.

## Diagnostics

Add an authenticated project tracking endpoint and a Windows diagnostic check that reports:

- detector backend;
- model availability;
- number of tracks;
- number of analyzed frames;
- coverage percentage;
- fallback reason.

## Installation

`tools/install_tracking_models.py` downloads the small OpenCV YuNet ONNX model from the official OpenCV Zoo GitHub repository. Installation failure is non-fatal because Haar fallback remains available.

No model binary is bundled in the user ZIP.

## Testing

Required regression/feature coverage:

- editor media endpoint returns a clean clip rather than final burned render;
- legacy projects lazily create a clean clip;
- face tracking JSON schema and deterministic association/smoothing tests;
- layout preset registry includes all new presets;
- every layout generates a valid, unique filter graph;
- two face tracks generate different crop centers for split layouts;
- no-face fallback renders successfully;
- project creation persists the selected layout;
- face tracking cannot be disabled through editor state/UI;
- real FFmpeg smoke renders for single, split, podcast-dynamic, choquei-movimento and header-news;
- full existing test suite remains green.

## Performance constraints

Target hardware remains i5-4590, RX 580 8 GB and 16 GB RAM. Face analysis defaults to low sampling frequency and project-level caching. Rendering continues to prefer AMD AMF when available and falls back to libx264. Heavy project jobs remain serialized.
