from app.services import preview


def test_clean_layout_fingerprint_changes_when_layout_changes():
    tracking = {'version': 2, 'tracks': [{'id': 'a', 'samples': [{'t': 0, 'center': [0.2, 0.4]}]}]}
    a = preview.edit_state_fingerprint({'layout_preset_id': 'single', 'layout_config': {}}, tracking, '9:16')
    b = preview.edit_state_fingerprint({'layout_preset_id': 'split', 'layout_config': {}}, tracking, '9:16')
    assert a != b


def test_clean_layout_fingerprint_ignores_caption_only_changes():
    tracking = {'version': 2, 'tracks': []}
    a = preview.edit_state_fingerprint({'layout_preset_id': 'single', 'caption_config': {'fontSize': 40}}, tracking, '9:16')
    b = preview.edit_state_fingerprint({'layout_preset_id': 'single', 'caption_config': {'fontSize': 90}}, tracking, '9:16')
    assert a == b


def test_clean_layout_path_is_fingerprinted(tmp_path, monkeypatch):
    monkeypatch.setattr(preview, 'PREVIEW_DIR', tmp_path)
    p1 = preview.clean_layout_path('clip1', {'layout_preset_id': 'single'}, {}, '9:16')
    p2 = preview.clean_layout_path('clip1', {'layout_preset_id': 'split'}, {}, '9:16')
    assert p1 != p2
    assert p1.parent == tmp_path / 'clean'
