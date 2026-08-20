from pathlib import Path
from tools import setup_acceleration


def test_whispercpp_installer_is_optional_when_build_tools_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(setup_acceleration, 'ROOT', tmp_path)
    monkeypatch.setattr(setup_acceleration.shutil, 'which', lambda name: None)
    assert setup_acceleration.install_whispercpp_runtime(install_model=False) is False


def test_whispercpp_uses_pinned_official_source_archive():
    assert setup_acceleration.WHISPERCPP_VERSION.startswith('v')
    assert 'github.com/ggml-org/whisper.cpp/archive/refs/tags/' in setup_acceleration.WHISPERCPP_SOURCE_URL
