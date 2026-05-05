from app.services.normalizer import normalize_text


def test_normalize_text_removes_punctuation_and_unifies_terms():
    assert normalize_text("祢，袮！祂 臺灣 裏面") == "你你他台灣裡面"
