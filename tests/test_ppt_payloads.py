from app.services.ppt import (
    MAX_DISPLAY_WIDTH_PER_LINE,
    _display_width,
    build_songppt_slide_payloads,
    song_pptx_filename,
)


def test_songppt_payloads_use_two_lines_and_repeat_marker():
    raw = "A\nB\nA\nB\nC｜D\nE"

    slides = build_songppt_slide_payloads(raw)

    assert slides == [
        {"lines": ["A", "B"], "repeat": 2},
        {"lines": ["C", "D"], "repeat": 1},
        {"lines": ["E"], "repeat": 1},
    ]


def test_songppt_payloads_split_long_web_lyrics_before_ppt_wraps():
    raw = "(小羊詩歌)\n充滿我心，哦！主聖靈，掌管我的心為祢居所；更新我心，哦！主聖靈，現活著的已不再是我，而是永活主在我心中！"

    slides = build_songppt_slide_payloads(raw)
    flattened = [line for slide in slides for line in slide["lines"]]

    assert "小羊詩歌" not in "\n".join(flattened)
    assert not any("，" in line or "！" in line for line in flattened)
    assert all(len(slide["lines"]) <= 2 for slide in slides)
    assert all(_display_width(line) <= MAX_DISPLAY_WIDTH_PER_LINE for line in flattened)


def test_songppt_payloads_do_not_pair_orphan_tail_with_next_lyric():
    raw = """
    (我心旋律)
    那一葉心帆啊 何時漂盡汪洋的孤獨
    得一世的豐富 照樣是塵封的歸宿
    聰明的你和我 可否証出生命的解數
    """

    slides = build_songppt_slide_payloads(raw)

    assert slides == [
        {"lines": ["那一葉心帆啊 何時漂盡汪洋的孤獨", "得一世的豐富 照樣是塵封的歸宿"], "repeat": 1},
        {"lines": ["聰明的你和我 可否証出生命的解數"], "repeat": 1},
    ]


def test_songppt_payloads_keep_wrapped_line_on_its_own_slide():
    raw = "紅葉醉舞下的風鈴 我聽到造物主的細語\n風雨依然是風雨 人生不再是無奈結束"

    slides = build_songppt_slide_payloads(raw)

    assert slides == [
        {"lines": ["紅葉醉舞下的風鈴", "我聽到造物主的細語"], "repeat": 1},
        {"lines": ["風雨依然是風雨", "人生不再是無奈結束"], "repeat": 1},
    ]


def test_song_pptx_filename_uses_safe_title():
    assert song_pptx_filename('耶穌/珍寶: When He cometh?', 12) == "耶穌_珍寶_ When He cometh.pptx"
