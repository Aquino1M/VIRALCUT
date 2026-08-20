from app.services import jobs


def test_two_pass_helper_transcribes_segments_then_refines_only_selected_windows(monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, "transcribe_segments", lambda *a, **k: calls.append(("segments", None)) or {
        "language": "pt", "duration": 120.0,
        "segments": [{"id": 0, "start": 0.0, "end": 120.0, "text": "fala", "words": []}],
    })
    monkeypatch.setattr(jobs, "_pick_highlights_for_two_pass", lambda *_a, **_k: [
        {"start": 10.0, "end": 20.0, "score": 9.0},
        {"start": 70.0, "end": 82.0, "score": 8.0},
    ])
    monkeypatch.setattr(jobs, "transcribe_words", lambda _src, start, end, **k: calls.append(("words", (start, end))) or {
        "segments": [{"start": start, "end": end, "text": "fala", "words": [{"start": start, "end": end, "word": "fala"}]}],
    })
    result = jobs.run_two_pass_asr_for_candidates("video.mp4", {"mode": "smart", "num_clips": 2, "min_duration": 1, "max_duration": 30}, progress_callback=None)
    assert calls == [("segments", None), ("words", (10.0, 20.0)), ("words", (70.0, 82.0))]
    assert result["candidates"][0]["transcript"]["segments"][0]["words"]
