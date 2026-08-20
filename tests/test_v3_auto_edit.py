import json
from pathlib import Path

from app import db


def seed(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'auto.db')
    db.init_db()
    now = db.now_iso()
    db.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES(1,'a@a','x',?)", (now,))
    db.execute("INSERT INTO projects(id,user_id,title,source_type,mode,settings_json,created_at,updated_at) VALUES('p1',1,'P','upload','smart',?,?,?)", (json.dumps({'aspect_ratio':'9:16'}), now, now))
    db.execute("INSERT INTO clips(id,project_id,title,start_time,end_time,created_at) VALUES('c1','p1','C',0,24,?)", (now,))
    from app.services import editor
    editor.replace_caption_cues('c1', [
        {'start_time':0.0,'end_time':1.2,'text':'O dólar disparou','word_index':0},
        {'start_time':1.2,'end_time':2.6,'text':'e a bolsa caiu.','word_index':1},
        {'start_time':4.0,'end_time':5.5,'text':'Empresas começaram a demitir','word_index':2},
        {'start_time':5.5,'end_time':7.2,'text':'e o mercado ficou preocupado.','word_index':3},
        {'start_time':11.0,'end_time':12.5,'text':'Depois veio uma recuperação','word_index':4},
        {'start_time':12.5,'end_time':14.5,'text':'que surpreendeu os investidores.','word_index':5},
        {'start_time':18.0,'end_time':20.0,'text':'No fim a economia reagiu.','word_index':6},
    ])


def fake_search(query, *, kind=None, limit=8, orientation=None):
    q = query.lower()
    if kind == 'broll':
        if any(k in q for k in ('dólar','dolar','bolsa','mercado','economia')):
            return [{'id':'money1','kind':'broll','name':'Mercado financeiro','local_path':'/tmp/money.mp4','tags':['money','market'],'score':9,'duration':5,'provider':'test','license':'test'}]
    if kind == 'sfx':
        return [{'id':'impact1','kind':'sfx','name':'Impact','local_path':'/tmp/impact.wav','tags':['impact'],'score':5,'duration':0.5,'provider':'test','license':'test'}]
    if kind == 'filter':
        return [{'id':'cinematic','kind':'filter','name':'Cinematic','local_path':'filter://cinematic','metadata':{'eq':'contrast=1.08'},'score':3,'provider':'viralclip','license':'generated'}]
    return []


def test_auto_edit_reads_transcript_and_builds_multitrack_plan(monkeypatch, tmp_path):
    seed(monkeypatch, tmp_path)
    from app.services import auto_edit
    monkeypatch.setattr(auto_edit.assets, 'search_assets', fake_search)
    plan = auto_edit.build_auto_edit_plan('c1', style='financas', intensity='viral')
    tracks = {t['type']: t for t in plan['tracks']}
    assert tracks['broll']['items']
    assert tracks['sfx']['items']
    assert tracks['effects']['items']
    assert plan['metadata']['autoEdit']['style'] == 'financas'
    assert plan['metadata']['autoEdit']['intensity'] == 'viral'
    assert any('dólar' in x['query'].lower() or 'bolsa' in x['query'].lower() for x in plan['metadata']['autoEdit']['decisions'] if x['action'] == 'broll')


def test_auto_edit_does_not_cover_the_whole_video_with_broll(monkeypatch, tmp_path):
    seed(monkeypatch, tmp_path)
    from app.services import auto_edit
    monkeypatch.setattr(auto_edit.assets, 'search_assets', fake_search)
    plan = auto_edit.build_auto_edit_plan('c1', style='podcast-viral', intensity='normal')
    broll = next(t for t in plan['tracks'] if t['type']=='broll')['items']
    covered = sum(i['duration'] for i in broll)
    assert covered < plan['composition']['duration'] * 0.65


def test_clean_intensity_places_fewer_edits_than_hyper(monkeypatch, tmp_path):
    seed(monkeypatch, tmp_path)
    from app.services import auto_edit, timeline
    monkeypatch.setattr(auto_edit.assets, 'search_assets', fake_search)
    clean = auto_edit.build_auto_edit_plan('c1', intensity='clean')
    # Reset timeline so hyper starts from a clean base.
    t = timeline.get_or_create_timeline('c1')
    for track in t['tracks']:
        if track['type'] in {'broll','sfx','effects','music'}:
            track['items'] = []
    timeline.save_timeline('c1', t)
    hyper = auto_edit.build_auto_edit_plan('c1', intensity='hyper')
    def edits(p):
        return sum(len(t['items']) for t in p['tracks'] if t['type'] in {'broll','sfx','effects'})
    assert edits(hyper) >= edits(clean)
