from pathlib import Path

from app.services import captions

CUES=[
 {'start_time':0.0,'end_time':0.3,'text':'um','word_index':0},
 {'start_time':0.3,'end_time':0.6,'text':'dois','word_index':1},
 {'start_time':0.6,'end_time':0.9,'text':'tres','word_index':2},
 {'start_time':1.8,'end_time':2.1,'text':'quatro','word_index':3},
]


def _ass(tmp_path: Path, **cfg):
    p=tmp_path/'x.ass'
    base={'fontFamily':'Arial','fontSize':60,'wordsPerPage':4,'maxLines':2,'pageDurationMs':900,'positionX':540,'positionY':1200}
    base.update(cfg)
    captions.build_ass(CUES, base, p)
    return p.read_text(encoding='utf-8')


def test_page_duration_splits_long_gap_into_new_page(tmp_path):
    text=_ass(tmp_path, pageDurationMs=900)
    # quatro is beyond the 900ms page window and must not share the first page event.
    dialogue=[x for x in text.splitlines() if x.startswith('Dialogue:')]
    assert any('QUATRO' in x.upper() or 'quatro' in x for x in dialogue)
    assert all(not ('um' in x and 'quatro' in x) for x in dialogue)


def test_max_lines_emits_separate_line_positions_using_line_height(tmp_path):
    text=_ass(tmp_path, wordsPerPage=4, maxLines=2, lineHeight=1.5)
    dialogue=[x for x in text.splitlines() if x.startswith('Dialogue:')]
    assert any('\\pos(540,1155)' in x or '\\pos(540,1245)' in x for x in dialogue)


def test_karaoke_uses_ass_karaoke_timing_tags(tmp_path):
    text=_ass(tmp_path, animationType='karaoke')
    assert '\\k30' in text


def test_rainbow_assigns_multiple_word_colors(tmp_path):
    text=_ass(tmp_path, animationType='rainbow')
    assert text.count('\\c&H') >= 4
    assert '&H' in text


def test_word_pop_uses_timed_transform(tmp_path):
    text=_ass(tmp_path, animationType='word-pop', popDurationMs=180, popScalePeak=1.2)
    assert '\\t(0,180,' in text
    assert '\\fscx120' in text


def test_scaling_words_uses_configured_scale_amount(tmp_path):
    text=_ass(tmp_path, animationType='scaling-words', scaleAmount=.4, popDurationMs=200)
    assert '\\fscx140' in text
    assert '\\fscy140' in text


def test_background_fade_and_alignment_are_preserved(tmp_path):
    text=_ass(tmp_path, backgroundOpacity=.7, backgroundRadius=12, fadeInMs=100, fadeOutMs=150, align='right')
    assert 'BorderStyle' in text
    assert ',3,' in [x for x in text.splitlines() if x.startswith('Style:')][0]
    assert '\\fad(100,150)' in text
    assert ',3,20,20,20,1' in text
