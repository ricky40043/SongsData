FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:///./data/songs.db

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gzip \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY app ./app
COPY scripts ./scripts

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

RUN chmod +x scripts/render_start.sh

EXPOSE 10000

CMD ["bash", "scripts/render_start.sh"]
