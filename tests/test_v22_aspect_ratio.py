from app.services import layouts
from app.services.render import resolve_output_geometry, build_render_plan


def test_resolve_output_geometry_for_supported_ratios():
    assert resolve_output_geometry('9:16') == (1080, 1920)
    assert resolve_output_geometry('4:5') == (1080, 1350)
    assert resolve_output_geometry('1:1') == (1080, 1080)
    assert resolve_output_geometry('16:9') == (1920, 1080)
    assert resolve_output_geometry('9:16', preview=True) == (270, 480)
    assert resolve_output_geometry('16:9', preview=True) == (854, 480)


def test_render_plan_uses_aspect_ratio_geometry():
    plan = build_render_plan({'aspect_ratio': '4:5'}, preview=False)
    assert plan['aspect_ratio'] == '4:5'
    assert plan['output_size'] == (1080, 1350)


def test_every_layout_targets_requested_output_geometry():
    for preset in layouts.list_layout_presets():
        graph = layouts.build_layout_filter(preset['id'], output_size=(1080, 1350))
        assert '[vout]' in graph
        assert '1080:1350' in graph


def test_editor_state_inherits_project_aspect_ratio(monkeypatch, tmp_path):
    import json
    from app import db
    from app.services import editor
    monkeypatch.setattr(db, 'DB_PATH', tmp_path/'ratio.db')
    db.init_db(); now=db.now_iso()
    db.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES(1,'ratio@test.local','x',?)",(now,))
    db.execute("INSERT INTO projects(id,user_id,title,source_type,mode,status,progress,message,settings_json,created_at,updated_at) VALUES('p',1,'P','upload','smart','done',100,'ok',?,?,?)",(json.dumps({'aspect_ratio':'4:5'}),now,now))
    db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,created_at) VALUES('c','p','C',0,10,?)",(now,))
    state=editor.get_or_create_edit_state('c')
    assert state['aspect_ratio']=='4:5'
