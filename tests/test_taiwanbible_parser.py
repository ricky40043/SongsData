from app.crawlers.taiwanbible import TaiwanBibleCrawler


def test_parse_detail_from_minimal_html():
    html = """
    <html><body>
    詩歌園地 專輯列表 我的詩歌本 新增詩歌 搜尋詩歌
    安靜
    專輯: 約書亞06-直到世界盡頭
    藏我在翅膀蔭下
    我要安靜知你是神
    MIDI 下載
    本詩歌資料庫編號: 2136
    請注意! 本詩歌歌詞/midi等內容由網友自行新增
    </body></html>
    """
    detail = TaiwanBibleCrawler().parse_detail(
        html,
        "https://www.taiwanbible.com/web/lyrics/view.jsp?ID=2136",
        "2136",
    )

    assert detail is not None
    assert detail.title == "安靜"
    assert "我要安靜知你是神" in detail.lyrics
