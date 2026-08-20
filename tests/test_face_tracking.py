from __future__ import annotations

import json
from pathlib import Path

from app.services import face_tracking


def test_box_helpers_normalize_associate_and_smooth():
    box = face_tracking.normalize_box((100, 50, 200, 100), 1000, 500)
    assert box == [0.1, 0.1, 0.2, 0.2]
    assert face_tracking.box_center(box) == [0.2, 0.2]
    assert face_tracking.iou([0.1, 0.1, 0.2, 0.2], [0.12, 0.1, 0.2, 0.2]) > 0.8
    smoothed = face_tracking.smooth_box([0.1, 0.1, 0.2, 0.2], [0.3, 0.1, 0.2, 0.2], alpha=0.25)
    assert smoothed == [0.15, 0.1, 0.2, 0.2]


def test_associate_detections_keeps_identity_for_nearby_faces():
    previous = {
        "face_1": {"box": [0.1, 0.1, 0.2, 0.2]},
        "face_2": {"box": [0.7, 0.1, 0.2, 0.2]},
    }
    detections = [
        {"box": [0.12, 0.1, 0.2, 0.2], "confidence": 0.9},
        {"box": [0.68, 0.1, 0.2, 0.2], "confidence": 0.8},
    ]
    assignments, next_id = face_tracking.associate_detections(previous, detections, next_id=3)
    assert assignments[0][0] == "face_1"
    assert assignments[1][0] == "face_2"
    assert next_id == 3


def test_slice_tracks_rebases_time_and_keeps_overlapping_samples():
    data = {
        "version": 1,
        "backend": "test",
        "tracks": [
            {"id": "face_1", "samples": [
                {"t": 4.0, "box": [0.1,0.1,0.2,0.2], "center": [0.2,0.2], "confidence": .9, "activity": .1},
                {"t": 6.0, "box": [0.2,0.1,0.2,0.2], "center": [0.3,0.2], "confidence": .9, "activity": .7},
                {"t": 8.0, "box": [0.3,0.1,0.2,0.2], "center": [0.4,0.2], "confidence": .9, "activity": .2},
            ]}
        ],
        "analyzed_frames": 3,
    }
    sliced = face_tracking.slice_tracks(data, 5.0, 8.0)
    assert [s["t"] for s in sliced["tracks"][0]["samples"]] == [1.0, 3.0]
    assert sliced["source_start"] == 5.0
    assert sliced["duration"] == 3.0


def test_tracking_summary_reports_coverage_and_dominant_tracks():
    data = {
        "backend": "haar",
        "analyzed_frames": 10,
        "total_samples": 10,
        "frames_with_faces": 7,
        "tracks": [
            {"id": "face_1", "samples": [{"t": i} for i in range(7)]},
            {"id": "face_2", "samples": [{"t": i} for i in range(3)]},
        ],
        "fallback_reason": None,
    }
    summary = face_tracking.tracking_summary(data)
    assert summary["backend"] == "haar"
    assert summary["track_count"] == 2
    assert summary["coverage_percent"] == 70.0
    assert summary["dominant_tracks"] == ["face_1", "face_2"]


def test_analyze_video_returns_nonfatal_empty_schema_for_missing_source(tmp_path: Path):
    out = tmp_path / "tracks.json"
    data = face_tracking.analyze_video(tmp_path / "missing.mp4", out)
    assert data["tracks"] == []
    assert data["backend"] == "none"
    assert data["fallback_reason"]
    assert json.loads(out.read_text(encoding="utf-8"))["version"] == 2


def test_merge_tracklets_combines_nonoverlapping_fragments_in_same_region():
    tracks = [
        {"id":"face_1","samples":[{"t":0,"center":[.30,.70],"box":[.2,.5,.2,.3]},{"t":1,"center":[.31,.70],"box":[.21,.5,.2,.3]}]},
        {"id":"face_2","samples":[{"t":3,"center":[.32,.71],"box":[.22,.51,.2,.3]},{"t":4,"center":[.33,.71],"box":[.23,.51,.2,.3]}]},
        {"id":"face_3","samples":[{"t":0,"center":[.70,.20],"box":[.6,.05,.2,.3]}]},
    ]
    merged = face_tracking.merge_tracklets(tracks, max_center_distance=.12)
    assert len(merged) == 2
    longest = max(merged, key=lambda t: len(t["samples"]))
    assert len(longest["samples"]) == 4
    assert [s["t"] for s in longest["samples"]] == [0,1,3,4]
