from pathlib import Path


def test_release_version_is_v3_series():
    assert Path('VERSION').read_text(encoding='utf-8').strip() == '4.2.0'


def test_readme_documents_single_bat_local_worker_and_asset_brain():
    text = Path('README.md').read_text(encoding='utf-8')
    for marker in (
        '# ViralClip Studio V3', 'VIRALCLIP.bat', 'NVIDIA', 'AMD', 'Intel',
        'Biblioteca Leve', 'Auto Edit', 'Timeline Pro', '/api/v1/health', 'data/assets',
    ):
        assert marker in text


def test_v3_release_notes_exist_and_explain_v22_migration():
    text = Path('docs/V3_RELEASE_NOTES.md').read_text(encoding='utf-8')
    assert 'V3.1' in text
    assert 'V2.2' in text
    assert 'pasta nova' in text.lower()
    assert '2 GB' in text


def test_system_diagnostic_reports_hardware_and_asset_library():
    text = Path('tools/check_system.py').read_text(encoding='utf-8')
    assert 'Hardware Manager V3' in text
    assert 'Biblioteca Leve' in text
    assert 'starter_pack_status' in text
