from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_version_is_4_1():
    assert (ROOT / 'VERSION').read_text(encoding='utf-8').strip() == '4.2.0'


def test_v41_release_notes_and_docs_exist():
    assert (ROOT / 'docs/V4.1_RELEASE_NOTES.md').exists()
    assert (ROOT / 'docs/superpowers/specs/2026-08-20-viralclip-v4.1-smart-studio-engine-design.md').exists()
    assert (ROOT / 'docs/superpowers/plans/2026-08-20-viralclip-v4.1-smart-studio-engine.md').exists()


def test_editor_keeps_single_automatic_download_action():
    html = (ROOT / 'app/templates/editor.html').read_text(encoding='utf-8')
    assert 'Renderizar preview' not in html
    assert 'Render final' not in html
    assert 'id="downloadFinal"' in html
