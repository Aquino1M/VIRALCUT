from app.services import face_tracking as ft


def test_sample_frame_indices_are_monotonic_and_match_target_rate():
    idx = ft.sample_frame_indices(native_fps=30.0, sample_fps=2.0, frame_count=91)
    assert idx[:5] == [0, 15, 30, 45, 60]
    assert idx[-1] <= 90
    assert idx == sorted(set(idx))


def test_track_activity_at_uses_local_time_window():
    track = {'id':'a','samples':[
        {'t':0.0,'activity':0.1}, {'t':1.0,'activity':0.2},
        {'t':4.0,'activity':0.9}, {'t':5.0,'activity':0.8},
    ]}
    assert ft.track_activity_at(track, 0.5, window=1.2) < 0.3
    assert ft.track_activity_at(track, 4.5, window=1.2) > 0.7


def test_rank_tracks_at_changes_with_time():
    tracking={'tracks':[
        {'id':'a','samples':[{'t':0,'activity':.9},{'t':4,'activity':.1}]},
        {'id':'b','samples':[{'t':0,'activity':.1},{'t':4,'activity':.95}]},
    ]}
    assert ft.rank_tracks_at(tracking, 0, window=.6)[0]['id']=='a'
    assert ft.rank_tracks_at(tracking, 4, window=.6)[0]['id']=='b'
