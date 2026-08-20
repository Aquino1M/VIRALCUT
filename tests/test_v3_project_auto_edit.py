from pathlib import Path

from app.services import jobs, projects


def test_new_projects_can_enable_auto_edit_settings():
    cfg = projects.normalize_project_settings({
        'auto_edit_enabled': 'on',
        'auto_edit_style': 'politica',
        'auto_edit_intensity': 'viral',
    })
    assert cfg['auto_edit_enabled'] is True
    assert cfg['auto_edit_style'] == 'politica'
    assert cfg['auto_edit_intensity'] == 'viral'


def test_existing_projects_without_flag_do_not_silently_enable_auto_edit():
    cfg = projects.normalize_project_settings({})
    assert cfg['auto_edit_enabled'] is False


def test_apply_project_auto_edit_builds_plan_and_renders(monkeypatch, tmp_path):
    source = tmp_path / 'source.mp4'
    target = tmp_path / 'clip.mp4'
    source.write_bytes(b'x')
    target.write_bytes(b'y')
    calls = {}

    def fake_plan(clip_id, **kwargs):
        calls['plan'] = (clip_id, kwargs)
        return {'composition': {'duration': 12}, 'tracks': []}

    def fake_render(*args, **kwargs):
        calls['render'] = (args, kwargs)
        target.write_bytes(b'final')
        return {'encoder': 'h264_nvenc', 'resolution': '1080x1920'}

    monkeypatch.setattr(jobs.auto_edit_service, 'build_auto_edit_plan', fake_plan)
    monkeypatch.setattr(jobs.timeline_render, 'render_timeline_clip', fake_render)
    monkeypatch.setattr(jobs.editor_service, 'list_caption_cues', lambda _clip_id: [])

    result = jobs._apply_project_auto_edit(
        clip_id='clip-1',
        settings={'auto_edit_enabled': True, 'auto_edit_style': 'politica', 'auto_edit_intensity': 'viral'},
        source=source,
        video_out=target,
        start=5.0,
        end=17.0,
        edit_state={'layout_preset_id': 'auto'},
        transcript={'words': []},
        tracking={'tracks': []},
    )
    assert result['encoder'] == 'h264_nvenc'
    assert calls['plan'][0] == 'clip-1'
    assert calls['plan'][1]['style'] == 'politica'
    assert calls['plan'][1]['intensity'] == 'viral'
    assert calls['render'][1]['timeline_data']['composition']['duration'] == 12


def test_new_project_form_offers_auto_edit_before_processing():
    html = Path('app/templates/new_project.html').read_text(encoding='utf-8')
    assert 'name="auto_edit_enabled"' in html
    assert 'name="auto_edit_style"' in html
    assert 'name="auto_edit_intensity"' in html
