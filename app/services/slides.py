from app.services.normalizer import clean_lines


def split_lyrics_to_slides(raw_lyrics: str, max_lines_per_slide: int = 4) -> list[str]:
    lines = clean_lines(raw_lyrics)
    slides: list[str] = []
    for idx in range(0, len(lines), max_lines_per_slide):
        slides.append("\n".join(lines[idx : idx + max_lines_per_slide]))
    return slides
