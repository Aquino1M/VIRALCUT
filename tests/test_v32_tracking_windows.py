from pathlib import Path

import numpy as np

from app.services import face_tracking


class FakeCap:
    def __init__(self, path):
        self.pos = 0
        self.set_calls = []
        self.opened = True
        self.frame_count = 300
        self.fps = 30.0
    def isOpened(self): return self.opened
    def get(self, key):
        import cv2
        return {
            cv2.CAP_PROP_FRAME_WIDTH: 1280,
            cv2.CAP_PROP_FRAME_HEIGHT: 720,
            cv2.CAP_PROP_FPS: self.fps,
            cv2.CAP_PROP_FRAME_COUNT: self.frame_count,
        }.get(key, 0)
    def set(self, key, value):
        import cv2
        self.set_calls.append((key, value))
        if key == cv2.CAP_PROP_POS_FRAMES: self.pos = int(value)
        return True
    def read(self):
        if self.pos >= self.frame_count: return False, None
        frame = np.zeros((72,128,3), dtype=np.uint8)
        self.pos += 1
        return True, frame
    def release(self): pass


class FakeDetector:
    backend='fake'
    def __init__(self): self.calls=0
    def detect(self, frame):
        self.calls += 1
        return [{'box':[0.25,0.2,0.2,0.3], 'confidence':0.9}]


def test_analyze_window_seeks_and_reports_absolute_timestamps(monkeypatch, tmp_path):
    source = tmp_path/'source.mp4'; source.write_bytes(b'x')
    holder = {}
    def make_cap(path):
        holder['cap']=FakeCap(path); return holder['cap']
    detector = FakeDetector()
    monkeypatch.setattr(face_tracking.cv2, 'VideoCapture', make_cap)
    monkeypatch.setattr(face_tracking, '_build_detector', lambda: detector)
    progress=[]
    out = face_tracking.analyze_window(source, 4.0, 6.0, fps=2.0, analysis_width=480, progress_callback=lambda f,b: progress.append((f,b)))
    import cv2
    assert holder['cap'].set_calls[0][0] == cv2.CAP_PROP_POS_FRAMES
    assert int(holder['cap'].set_calls[0][1]) == 120
    samples = out['tracks'][0]['samples']
    assert samples[0]['t'] >= 4.0
    assert samples[-1]['t'] <= 6.05
    assert progress and progress[-1][0] == 1.0
    assert out['source_start'] == 4.0
    assert out['source_end'] == 6.0


def test_analyze_window_uses_cache(monkeypatch, tmp_path):
    source = tmp_path/'source.mp4'; source.write_bytes(b'x')
    out_path = tmp_path/'track.json'
    detector = FakeDetector()
    monkeypatch.setattr(face_tracking.cv2, 'VideoCapture', lambda p: FakeCap(p))
    monkeypatch.setattr(face_tracking, '_build_detector', lambda: detector)
    first = face_tracking.analyze_window(source, 1, 2, out_path=out_path, fps=1.0, analysis_width=480)
    calls = detector.calls
    second = face_tracking.analyze_window(source, 1, 2, out_path=out_path, fps=1.0, analysis_width=480)
    assert calls > 0
    assert detector.calls == calls
    assert second['cache_key'] == first['cache_key']
