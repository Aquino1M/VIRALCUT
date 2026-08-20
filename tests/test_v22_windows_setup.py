from pathlib import Path


def test_installer_prefers_directml_compatible_python_before_creating_venv():
    text = Path('install.bat').read_text(encoding='utf-8')
    assert ':find_compatible_python' in text
    assert 'py -3.12 -V' in text
    assert 'py -3.11 -V' in text
    assert 'py -3.10 -V' in text
    assert '%PY_COMPAT% -m venv .venv' in text
    assert 'Python.Python.3.12' in text


def test_installer_runs_a_single_health_check_at_the_end():
    text = Path('install.bat').read_text(encoding='utf-8')
    assert 'tools\\check_system.py' in text


def test_diagnostic_script_uses_consolidated_system_check():
    text = Path('diagnostico.bat').read_text(encoding='utf-8')
    assert 'tools\\check_system.py' in text


def test_system_check_covers_acceleration_youtube_fonts_and_tracking():
    path = Path('tools/check_system.py')
    assert path.exists()
    text = path.read_text(encoding='utf-8')
    for marker in ('check_acceleration', 'check_youtube', 'Face Tracking', 'Fontes', 'Python compativel'):
        assert marker in text
