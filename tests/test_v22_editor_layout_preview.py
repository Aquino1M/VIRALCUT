from pathlib import Path


def test_editor_js_reloads_clean_video_after_layout_change():
    text = Path('app/static/editor.js').read_text(encoding='utf-8')
    assert 'reloadCleanVideoForLayout' not in text
    assert 'scheduleLayoutFrame' in text
    assert 'layoutCanvas' in text
    assert 'data-layout' in text or 'layout-card' in text
