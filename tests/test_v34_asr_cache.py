from app.services import asr_cache


def test_segment_cache_key_changes_with_model_or_vad(tmp_path, monkeypatch):
    source = tmp_path / "a.bin"
    source.write_bytes(b"abc")
    monkeypatch.setattr(asr_cache, "CACHE_ROOT", tmp_path / "cache")
    k1 = asr_cache.segment_cache_key(source, model="small", language="pt", vad=True)
    k2 = asr_cache.segment_cache_key(source, model="medium", language="pt", vad=True)
    k3 = asr_cache.segment_cache_key(source, model="small", language="pt", vad=False)
    assert len({k1, k2, k3}) == 3


def test_manual_layout_change_is_not_part_of_asr_cache_key(tmp_path, monkeypatch):
    source = tmp_path / "a.bin"
    source.write_bytes(b"abc")
    monkeypatch.setattr(asr_cache, "CACHE_ROOT", tmp_path / "cache")
    a = asr_cache.segment_cache_key(source, model="small", language="pt", vad=True)
    b = asr_cache.segment_cache_key(source, model="small", language="pt", vad=True)
    assert a == b


def test_word_window_key_changes_with_temporal_window(tmp_path, monkeypatch):
    source = tmp_path / "a.bin"
    source.write_bytes(b"abc")
    monkeypatch.setattr(asr_cache, "CACHE_ROOT", tmp_path / "cache")
    a = asr_cache.word_window_cache_key(source, 1.0, 2.0, model="small", language="pt")
    b = asr_cache.word_window_cache_key(source, 1.0, 3.0, model="small", language="pt")
    assert a != b
