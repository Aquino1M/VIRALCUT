from pathlib import Path


def test_project_page_technical_output_is_dynamic():
    text=Path('app/templates/project.html').read_text(encoding='utf-8')
    assert '<b>Saída:</b> {{ output_resolution }}' in text
    assert '<b>Saída:</b> 1080×1920' not in text


def test_editor_export_card_uses_dynamic_preview_and_final_resolution():
    text=Path('app/templates/editor.html').read_text(encoding='utf-8')
    assert '{{ preview_resolution }}' in text
    assert '{{ output_resolution }}' in text
    assert 'Final 1080×1920' not in text
