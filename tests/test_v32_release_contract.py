from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_version_and_single_launcher_are_v32_worker_edition():
    assert (ROOT / 'VERSION').read_text(encoding='utf-8').strip() == '4.2.0'
    bat = (ROOT / 'VIRALCLIP.bat').read_text(encoding='utf-8', errors='ignore')
    assert 'ViralClip Studio V4.2' in bat
    assert 'Local Worker' in bat
    assert 'tools\\bootstrap.py' in bat


def test_setup_acceleration_persists_versioned_hardware_auto_profile():
    text = (ROOT / 'tools' / 'setup_acceleration.py').read_text(encoding='utf-8')
    assert 'build_hardware_profile' in text
    assert 'hardware_profile.json' in text
    assert 'directml_ready' in text


def test_bootstrap_describes_hybrid_worker_and_runs_hardware_setup_before_app():
    text = (ROOT / 'tools' / 'bootstrap.py').read_text(encoding='utf-8')
    assert 'ViralClip Studio V4.2' in text
    assert 'Local Worker' in text
    assert 'wait_for_health' in text
    assert 'subprocess.Popen' in text
    assert text.index('setup_acceleration()') < text.index('run.py')


def test_v32_docs_explain_worker_webgpu_window_tracking_and_lite_library():
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    notes = (ROOT / 'docs' / 'V3.2_RELEASE_NOTES.md').read_text(encoding='utf-8')
    architecture = (ROOT / 'ARQUITETURA.md').read_text(encoding='utf-8')
    for marker in (
        'V3.2', 'Local Worker', 'WebGPU', '2 GB',
        'Face Tracking', 'transcrição', 'VIRALCLIP.bat',
    ):
        assert marker in readme
        assert marker in notes
    assert 'Worker Protocol v1' in architecture
    assert 'WebGPU' in architecture
    assert 'tracking' in architecture.lower()


def test_runtime_hardware_and_pairing_state_are_ignored():
    text = (ROOT / '.gitignore').read_text(encoding='utf-8')
    for marker in (
        'data/hardware_profile.json',
        'data/worker_pairing.json',
        'data/assets/catalog.json',
        'data/tracks/*.json',
    ):
        assert marker in text


def test_system_diagnostic_uses_versioned_hardware_auto_profile():
    text = (ROOT / 'tools' / 'check_system.py').read_text(encoding='utf-8')
    assert 'load_or_build_profile' in text
    assert 'Hardware Auto 2.0' in text
    assert 'Render verificado' in text
