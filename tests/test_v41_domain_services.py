from __future__ import annotations

import json
from pathlib import Path

from app import db


def setup_db(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'v41.db')
    db.init_db()
    now = db.now_iso()
    db.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES(1,'u@test.com','x',?)", (now,))
    db.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES(2,'other@test.com','x',?)", (now,))
    db.execute("INSERT INTO projects(id,user_id,title,source_type,mode,settings_json,created_at,updated_at) VALUES('p1',1,'P','upload','smart','{}',?,?)", (now, now))
    db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,score,created_at) VALUES('c1','p1','Isso vai gerar muita discussão',0,42,9.1,?)", (now,))
    return now


def test_v41_migrations_create_new_tables_and_columns(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    with db.connect() as conn:
        tables = {r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        clip_cols = {r['name'] for r in conn.execute('PRAGMA table_info(clips)')}
        project_cols = {r['name'] for r in conn.execute('PRAGMA table_info(projects)')}
        cue_cols = {r['name'] for r in conn.execute('PRAGMA table_info(caption_cues)')}
        user_cols = {r['name'] for r in conn.execute('PRAGMA table_info(users)')}
    assert {'studio_templates', 'brand_kits', 'publish_queue'} <= tables
    assert 'analysis_json' in clip_cols
    assert {'brand_kit_id', 'template_id'} <= project_cols
    assert {'highlight', 'emoji'} <= cue_cols
    assert 'performance_mode' in user_cols


def test_viral_score_returns_0_to_100_with_expected_breakdown():
    from app.services import viral_score
    result = viral_score.score_clip_payload({
        'title': 'Ninguém teve coragem de falar isso',
        'hook': 'Você não vai acreditar no que ele revelou',
        'reason': 'Declaração polêmica que deve gerar comentários e compartilhamentos',
        'text': 'nunca contaram esse segredo e agora a verdade apareceu',
        'duration': 44,
        'score': 9.2,
    })
    assert 0 <= result['score'] <= 100
    assert result['label'] in {'Baixo', 'Médio', 'Alto', 'Muito alto'}
    assert set(result['breakdown']) == {'hook','curiosity','emotion','controversy','clarity','shareability','comments','retention'}
    assert all(0 <= v <= 100 for v in result['breakdown'].values())
    assert result['breakdown']['curiosity'] >= 60


def test_template_can_be_created_owned_and_applied_to_clip(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    from app.services import studio_templates, editor
    template = studio_templates.create_template(1, 'Meu Viral', {
        'caption_preset_id': 'mrbeast',
        'layout_preset_id': 'split',
        'caption_config': {'fontSize': 88},
        'auto_edit': {'style': 'podcast-viral', 'intensity': 'viral'},
    })
    assert studio_templates.get_template(2, template['id']) is None
    result = studio_templates.apply_template(1, template['id'], ['c1'])
    assert result['updated'] == 1
    state = editor.get_or_create_edit_state('c1')
    assert state['caption_preset_id'] == 'mrbeast'
    assert state['layout_preset_id'] == 'split'
    assert state['caption_config']['fontSize'] == 88


def test_brand_kit_applies_caption_brand_and_asset_overlays(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    from app.services import brand_kits, editor
    now = db.now_iso()
    logo = tmp_path / 'logo.png'; logo.write_bytes(b'png')
    db.execute("INSERT INTO brand_assets(id,user_id,name,asset_type,file_path,config_json,created_at,updated_at) VALUES('a1',1,'Logo','logo',?,'{}',?,?)", (str(logo), now, now))
    kit = brand_kits.create_brand_kit(1, 'Canal A', {
        'font_family': 'Anton', 'primary_color': '#FFE600', 'secondary_color': '#FFFFFF',
        'cta_text': 'SIGA PARA MAIS', 'asset_ids': ['a1']
    })
    result = brand_kits.apply_brand_kit(1, kit['id'], ['c1'])
    assert result['updated'] == 1
    state = editor.get_or_create_edit_state('c1')
    assert state['caption_config']['fontFamily'] == 'Anton'
    assert state['caption_config']['primaryColor'] == '#FFE600'
    assert any(o.get('type') == 'logo' and o.get('path') == str(logo) for o in state['overlays'])
    assert any(o.get('type') == 'cta' and o.get('text') == 'SIGA PARA MAIS' for o in state['overlays'])


def test_publishing_queue_is_truthful_and_explicit(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    from app.services import publishing
    item = publishing.enqueue(1, 'c1', platform='tiktok', scheduled_at='2026-08-21T18:00:00', caption='Legenda')
    assert item['status'] == 'scheduled'
    assert item['platform'] == 'tiktok'
    assert publishing.update_status(2, item['id'], 'published') is None
    updated = publishing.update_status(1, item['id'], 'published')
    assert updated['status'] == 'published'


def test_performance_mode_auto_selects_basic_for_low_end_profile():
    from app.services import performance
    policy = performance.resolve_mode({'cpu': {'logical_cores': 4}, 'memory_gb': 8, 'gpu_vendor': 'intel'}, 'auto')
    assert policy['mode'] == 'basic'
    assert policy['proxy_height'] <= 480
    assert policy['final_quality_unchanged'] is True
