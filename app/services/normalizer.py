from hashlib import sha256
import re
import unicodedata


CHAR_REPLACEMENTS = str.maketrans(
    {
        "祢": "你",
        "袮": "你",
        "祂": "他",
        "衪": "他",
        "裏": "裡",
        "臺": "台",
        "妳": "你",
    }
)

PUNCTUATION_RE = re.compile(r"[\s\u3000，,。．.！!？?、；;：「」『』（）()\[\]【】《》〈〉\-—_…~`'\"“”‘’|/\\]+")


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.translate(CHAR_REPLACEMENTS)
    normalized = PUNCTUATION_RE.sub("", normalized)
    return normalized.lower()


def lyrics_hash(normalized_lyrics: str) -> str:
    return sha256(normalized_lyrics.encode("utf-8")).hexdigest()


def clean_lines(raw_lyrics: str) -> list[str]:
    lines = []
    for line in raw_lyrics.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        cleaned = line.strip()
        if cleaned:
            lines.append(cleaned)
    return lines
