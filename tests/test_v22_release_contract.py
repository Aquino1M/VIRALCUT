from pathlib import Path


def test_release_keeps_v22_or_newer_migration_lineage():
    major = int(Path('VERSION').read_text(encoding='utf-8').strip().split('.')[0])
    assert major >= 2


def test_readme_keeps_v22_reliability_and_real_aspect_ratios():
    text = Path('README.md').read_text(encoding='utf-8')
    assert 'V2.2' in text
    assert '1080×1350' in text
    assert '1080×1080' in text
    assert '1920×1080' in text
    assert 'Reprocessar projeto' in text
    assert 'Caption Engine' in text
    assert 'Layout' in text


def test_release_notes_exist_and_cover_migration():
    path = Path('docs/V2.2_RELEASE_NOTES.md')
    assert path.exists()
    text = path.read_text(encoding='utf-8')
    assert 'V2.2' in text
    assert 'V2.1' in text
    assert 'pasta nova' in text.lower()
