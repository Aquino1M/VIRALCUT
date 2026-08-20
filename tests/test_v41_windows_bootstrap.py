from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_launcher_is_minimal_ascii_wrapper_without_delayed_expansion():
    raw = (ROOT / 'VIRALCLIP.bat').read_bytes()
    text = raw.decode('ascii')
    low = text.lower()
    assert 'enabledelayedexpansion' not in low
    assert 'chcp 65001' not in low
    assert 'tools\\bootstrap.py' in low
    assert 'py -3.12' in low
    assert 'goto :python_missing' in low


def test_bootstrap_labels_v41_and_supported_modes():
    text = (ROOT / 'tools/bootstrap.py').read_text(encoding='utf-8')
    assert 'ViralClip Studio V4.2' in text
    for mode in ('start', 'repair', 'diagnose', 'update', 'safe'):
        assert mode in text


def test_launcher_reprobes_python_after_winget_without_requiring_new_terminal():
    text = (ROOT / 'VIRALCLIP.bat').read_text(encoding='ascii').lower()
    assert r'%localappdata%\programs\python\python312\python.exe' in text
    assert 'goto :detect_after_install' in text
    assert ':detect_after_install' in text
