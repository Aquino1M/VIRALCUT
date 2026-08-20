from pathlib import Path


def test_project_polling_reloads_only_on_terminal_transition():
    text=Path('app/templates/project.html').read_text(encoding='utf-8')
    assert 'initialProjectStatus' in text
    assert "d.clips>0)location.reload" not in text
    assert "lastProjectStatus!==d.status" in text


def test_project_page_has_retry_action_for_failed_processing():
    text=Path('app/templates/project.html').read_text(encoding='utf-8')
    assert '/retry' in text
    assert 'Reprocessar projeto' in text
