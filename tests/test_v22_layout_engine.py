import shutil
import subprocess

import pytest

from app.services import layouts

TRACKING_SWITCH = {
    'tracks': [
        {'id':'a','samples':[
            {'t':0.0,'center':[.25,.4],'activity':.9},
            {'t':1.0,'center':[.26,.4],'activity':.8},
            {'t':3.0,'center':[.26,.4],'activity':.1},
            {'t':4.0,'center':[.27,.4],'activity':.1},
        ]},
        {'id':'b','samples':[
            {'t':0.0,'center':[.75,.4],'activity':.1},
            {'t':1.0,'center':[.74,.4],'activity':.1},
            {'t':3.0,'center':[.73,.4],'activity':.85},
            {'t':4.0,'center':[.72,.4],'activity':.9},
        ]},
    ]
}


def test_podcast_dynamic_switches_track_priority_over_time():
    graph = layouts.build_layout_filter('podcast-dynamic', tracking=TRACKING_SWITCH, clip_duration=4.0)
    assert 'if(lt(t' in graph
    assert '.2500' in graph or '.2600' in graph
    assert '.7500' in graph or '.7400' in graph


def test_one_face_multi_panel_layout_uses_distinct_framing_recipes():
    one = {'tracks':[TRACKING_SWITCH['tracks'][0]]}
    for lid in ('quad','six-split','brainrot','tri-split'):
        graph = layouts.build_layout_filter(lid, tracking=one)
        crops = [part for part in graph.split(';') if 'crop=' in part]
        assert len(crops) >= 2
        assert len(set(crops)) >= 2


def test_ensure_layout_overlays_adds_title_for_branded_layouts_only_once():
    state={'layout_preset_id':'choquei-movimento','overlays':[]}
    out=layouts.ensure_layout_overlays(state, 'Título importante')
    assert any(x.get('autoLayoutTitle') for x in out['overlays'])
    out2=layouts.ensure_layout_overlays(out, 'Título importante')
    assert len([x for x in out2['overlays'] if x.get('autoLayoutTitle')]) == 1


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg missing')
@pytest.mark.parametrize('track_count',[0,1,2,3])
def test_all_layouts_parse_for_common_face_counts(track_count):
    tracking={'tracks': TRACKING_SWITCH['tracks'][:track_count]}
    if track_count == 3:
        tracking['tracks'].append({'id':'c','samples':[{'t':0,'center':[.5,.3],'activity':.3}]})
    for preset in layouts.list_layout_presets():
        graph=layouts.build_layout_filter(preset['id'],tracking=tracking,output_size=(540,960),clip_duration=4.0)
        proc=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','lavfi','-i','testsrc2=s=1280x720:r=5:d=0.2','-filter_complex',graph,'-map','[vout]','-frames:v','1','-f','null','-'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        assert proc.returncode==0, f"{preset['id']} count={track_count}: {proc.stderr}"
