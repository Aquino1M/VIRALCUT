from app.services import timeline_render


def sample_timeline():
    return {
        'schemaVersion':3,
        'composition':{'width':1080,'height':1920,'fps':30,'duration':20},
        'assets':{
            'b1':{'id':'b1','type':'broll','path':'/tmp/broll.mp4'},
            's1':{'id':'s1','type':'sfx','path':'/tmp/hit.wav'},
        },
        'tracks':[
            {'type':'broll','items':[{'id':'bi','type':'broll','assetId':'b1','from':5,'duration':3,'sourceStart':0,'mode':'cover'}]},
            {'type':'sfx','items':[{'id':'si','type':'sfx','assetId':'s1','from':1,'duration':.5,'volumeDb':-6}]},
            {'type':'music','items':[]},
            {'type':'effects','items':[
                {'id':'f','type':'filter','effectId':'cinematic','from':0,'duration':20,'config':{'eq':'contrast=1.08:saturation=.95'}},
                {'id':'z','type':'effect','effectId':'zoom-punch','from':.2,'duration':.4,'config':{'type':'zoom','scale':1.12}},
            ]},
        ],
    }


def test_compile_plan_contains_broll_effect_and_audio_mix():
    plan = timeline_render.compile_postprocess_plan(sample_timeline(), width=1080, height=1920, base_has_audio=True)
    assert len(plan['inputs']) == 2
    graph = plan['filter_complex']
    assert 'overlay=' in graph
    assert "between(t,5.000,8.000)" in graph
    assert 'contrast=1.08' in graph
    assert 'amix=' in graph
    assert 'adelay=1000' in graph
    assert plan['video_map'].startswith('[')
    assert plan['audio_map'].startswith('[')


def test_compile_plan_uses_silence_when_base_has_no_audio():
    plan = timeline_render.compile_postprocess_plan(sample_timeline(), width=540, height=960, base_has_audio=False)
    assert 'anullsrc=' in plan['filter_complex']


def test_no_extra_items_short_circuits_postprocess():
    empty = {'composition':{'duration':10}, 'assets':{}, 'tracks':[{'type':'broll','items':[]},{'type':'sfx','items':[]},{'type':'music','items':[]},{'type':'effects','items':[]}]}
    assert timeline_render.has_timeline_media(empty) is False
