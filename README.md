# Songs Data MVP

本專案是「詩歌資料庫 + 爬蟲匯入 + 搜尋 API + PPTX 產生」的第一版 MVP。

正式環境的 SQLite 資料庫是主機持久化資料，不納入 Git 版控。部署只更新程式與容器，必須保留主機上的 `data/songs.db`。

目前已實作：

- SQLite 預設資料庫，透過 `DATABASE_URL` 可切 PostgreSQL。
- TaiwanBible 單首 ID 區間爬蟲。
- `SongImportStaging` 暫存匯入，不直接污染正式資料表。
- 歌名、歌詞正規化與 lyrics hash 去重。
- 非重複資料可自動核准寫入 `songs` / `song_versions` / `song_lines` / `song_slides`。
- FastAPI 搜尋與 PPTX 下載 API。
- 可由 API／前端新增詩歌，並沿用正規化與 lyrics hash 去重。
- CLI 可跑 2 萬 ID 區間匯入。

## 安裝

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

## 初始化資料庫

```bash
songs init
````

## 小範圍測試爬蟲

```bash
songs crawl-taiwanbible --start-id 2136 --end-id 2136 --auto-approve --delay 1
songs stats
songs search 安靜知你是神
```

## 跑 TaiwanBible 約 2 萬筆 ID 區間

TaiwanBible 行動版搜尋頁顯示目前約 19,323 首詩歌。若要自動化建立資料庫，直接跑完整站爬蟲：

```bash
songs crawl-taiwanbible-all
```

這個命令預設會：

- 從 `ID=1` 掃到 `ID=30000`。
- 抓到歌詞後先進 `SongImportStaging`。
- 非 hash 重複的歌曲自動核准入正式資料表。
- 每次請求保留 `.env` 的 `CRAWLER_DELAY_SECONDS=1.0` 延遲。
- 中斷後可直接重跑；已存在於暫存區或正式來源表的 ID 會跳過，不會再次抓取。

若要調整掃描上限：

```bash
songs crawl-taiwanbible-all --max-id 40000
```

若要加速，可以開 5 路並行：

```bash
songs crawl-taiwanbible-all --concurrency 5 --delay 1
```

`--delay 1` 是每個 worker 抓完一筆後等 1 秒；`--concurrency 5` 約等於最多同時 5 個請求。建議先不要超過 5，避免來源網站擋請求。

若要先 smoke test，只抓成功 5 首就停：

```bash
songs crawl-taiwanbible-all --stop-after-success 5
```

若只想先進暫存區，人工審核後再入正式庫：

```bash
songs crawl-taiwanbible-all --auto-approve false
songs approve-pending --limit 100
```

## 啟動 API

```bash
uvicorn app.main:app --reload
```

常用 API：

- `GET /api/health`
- `GET /api/songs/search?keyword=現在活著的不再是我`
- `POST /api/songs`
- `GET /api/songs/{song_id}`
- `GET /api/imports/pending`
- `POST /api/imports/{staging_id}/approve`
- `GET /api/songs/{song_id}/pptx`

## Docker

本專案可以直接包成 Docker image；SQLite 資料庫不放入 image，而是由執行環境提供的持久化 `data/songs.db`。

Build：

```bash
docker build -t songs-data:local .
```

Run：

```bash
docker run --rm -p 10000:10000 songs-data:local
```

開啟：

```text
http://localhost:10000
```

Docker Compose 會把主機的：

```text
./data
```

掛載到容器的 `/app/data`。因此正式部署前，請先確認主機已有 `data/songs.db`；第一次使用空資料庫時，應先透過匯入或新增流程建立資料。

本機測試結果：

```text
/api/health -> {"status":"ok"}
/api/stats  -> {"songs":16328,"staging":19227,"pending":0}
image size  -> 約 303MB
```

## 部署到 Render

本專案已包含 Render Blueprint 設定：

```text
render.yaml
scripts/render_start.sh
.python-version
```

### 部署方式

1. 把專案推到 GitHub。
2. 到 Render 建立 Blueprint，選這個 repo。
3. Render 會讀取 `render.yaml` 自動建立 Python Web Service。

目前 `render.yaml` 使用 Docker runtime：

```yaml
runtime: docker
healthCheckPath: /api/health
```

Render Web Service 必須綁定 `0.0.0.0` 和 `$PORT`。`scripts/render_start.sh` 已處理：

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-10000}"
```

### SQLite 持久化注意事項

Render 免費 Web Service 沒有 persistent disk，且本專案不再把 SQLite seed 放進 Git。若部署到 Render，請改用 PostgreSQL 或其他具持久化能力的外部資料庫：

```text
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DBNAME
```

### 主機部署的資料保留

主機部署使用 Docker Compose 的 `./data:/app/data` 掛載。Git 同步或 `docker compose up --build` 不會刪除或重新下載主機上的 `data/songs.db`；請將資料庫視為部署主機的資料資產，並另外安排備份。

## 產生 PPTX

```bash
songs make-pptx 1 --output data/exports/song-1.pptx
```

目前 PPTX 會套用從 `/Users/ricky/Desktop/songPPT/template.pptx` 複製過來的模板：

- 專案內模板：`app/templates/songppt-template.pptx`
- 備份模板：`data/templates/songppt-template.pptx`
- 輸出格式：黑底黃字。
- 每張最多 2 排歌詞。
- 連續相同投影片會合併，第三排顯示 `(xN)`。

## 後續建議

- 加 Alembic migration。
- 加 PostgreSQL `pg_trgm` 或 Meilisearch。
- 擴充更多 provider。
- 做前端審核介面。
- 對重複候選加入 rapidfuzz 相似度審核流程。
# SongsData
