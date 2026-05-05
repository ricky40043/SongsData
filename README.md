# Songs Data MVP

本專案是「本地詩歌資料庫 + 爬蟲匯入 + 搜尋 API + PPTX 產生」的第一版 MVP。

目前已實作：

- SQLite 預設資料庫，透過 `DATABASE_URL` 可切 PostgreSQL。
- TaiwanBible 單首 ID 區間爬蟲。
- `SongImportStaging` 暫存匯入，不直接污染正式資料表。
- 歌名、歌詞正規化與 lyrics hash 去重。
- 非重複資料可自動核准寫入 `songs` / `song_versions` / `song_lines` / `song_slides`。
- FastAPI 搜尋與 PPTX 下載 API。
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
- `GET /api/songs/{song_id}`
- `GET /api/imports/pending`
- `POST /api/imports/{staging_id}/approve`
- `GET /api/songs/{song_id}/pptx`

## Docker

本專案可以直接包成 Docker image，內含 FastAPI 程式、PPT 模板與壓縮後的 SQLite seed database。

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

啟動時會自動把：

```text
app/seed/songs.db.gz
```

還原成容器內的：

```text
data/songs.db
```

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
app/seed/songs.db.gz
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

### SQLite 固定資料庫

Render 免費 Web Service 沒有 persistent disk，因此本專案採用「固定 SQLite 種子資料庫」：

```text
app/seed/songs.db.gz
```

服務啟動時會自動解壓成：

```text
data/songs.db
```

這代表：

- 適合固定 16,000+ 首歌的查詢與 PPT 產生。
- Render 重啟或重新部署後仍會從 seed 還原資料。
- 不適合在 Render 上跑爬蟲後期待資料永久保存。
- 若要更新歌曲庫，請在本機更新 `data/songs.db` 後重新產生 `app/seed/songs.db.gz` 並重新部署。

重新產生 seed：

```bash
gzip -c data/songs.db > app/seed/songs.db.gz
```

### 若未來改外部資料庫

若要改用 Supabase / Neon / Render Postgres，只要把 Render 的環境變數改成：

```text
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DBNAME
```

但第一版最簡單、免費、最快能跑起來的方式仍是目前的 SQLite seed 檔。

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
