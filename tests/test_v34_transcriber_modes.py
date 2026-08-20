from types import SimpleNamespace
from app.services import transcriber


class FakeWord:
    def __init__(self, start, end, word):
        self.start=start; self.end=end; self.word=word


class FakeSegment:
    def __init__(self):
        self.start=0.0; self.end=2.0; self.text=' oi'; self.words=[FakeWord(0.0, 1.0, ' oi')]


class FakeModel:
    def __init__(self): self.calls=[]
    def transcribe(self, _path, **kwargs):
        self.calls.append(kwargs)
        return iter([FakeSegment()]), SimpleNamespace(duration=2.0, language='pt')


def test_faster_whisper_segment_mode_disables_word_timestamps(monkeypatch):
    model=FakeModel()
    monkeypatch.setattr(transcriber, '_get_faster_model', lambda *a, **k: model)
    monkeypatch.setattr(transcriber, '_faster_model_runtime', ('cpu','int8'))
    result=transcriber._transcribe_faster_whisper('x.mp4', None, None, {}, word_timestamps=False)
    assert model.calls[0]['word_timestamps'] is False
    assert result['segments'][0]['words'] == []


def test_faster_whisper_word_mode_keeps_word_timestamps(monkeypatch):
    model=FakeModel()
    monkeypatch.setattr(transcriber, '_get_faster_model', lambda *a, **k: model)
    monkeypatch.setattr(transcriber, '_faster_model_runtime', ('cpu','int8'))
    result=transcriber._transcribe_faster_whisper('x.mp4', None, None, {}, word_timestamps=True)
    assert model.calls[0]['word_timestamps'] is True
    assert result['segments'][0]['words'][0]['word'] == 'oi'


def test_release_asr_models_clears_resident_models():
    transcriber._faster_model = object()
    transcriber._directml_model = object()
    transcriber.release_asr_models()
    assert transcriber._faster_model is None
    assert transcriber._directml_model is None
