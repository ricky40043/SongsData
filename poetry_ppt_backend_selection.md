# 詩歌搜尋與 PPT 自動產生系統：後端技術選型建議

## 1. 結論

本專案第一版建議使用：

```text
Python + FastAPI + PostgreSQL + Meilisearch + python-pptx
```

原因很直接：本專案最困難的地方不是 API 效能，而是：

- 多網站爬蟲
- HTML 解析
- 歌詞清理
- 繁簡轉換
- 祢 / 你 / 袮 等文字正規化
- 相似度比對
- 重複歌曲合併
- PPT 產生

這些工作使用 Python 會比 Go 快很多。

如果未來系統變成正式產品、多教會同時使用、高併發查詢，再考慮將 API 核心改成 Go，並保留 Python Worker 處理爬蟲與 PPT 產生。

---

## 2. Python 與 Go 比較

| 項目 | Python | Go | 建議 |
|---|---:|---:|---|
| 開發速度 | 高 | 中 | Python |
| 爬蟲 | 很方便 | 可行但較硬 | Python |
| HTML 解析 | BeautifulSoup / lxml 成熟 | 可行 | Python |
| 文字正規化 | 很方便 | 需寫較多 | Python |
| 模糊比對 | rapidfuzz 很方便 | 可行但麻煩 | Python |
| PPT 產生 | python-pptx 成熟 | 套件較少 | Python |
| API 效能 | 足夠 | 很好 | Go |
| 高併發 | 中 | 高 | Go |
| 部署 | 中 | 單一 binary，很乾淨 | Go |
| 第一版 MVP | 很適合 | 可行但較慢 | Python |
| 長期產品化 | 可行 | 很適合 | Go + Python Worker |

---

## 3. 專案功能拆解

本系統後端主要包含以下模組：

```text
1. Crawler：爬取外部詩歌網站
2. Parser：解析歌名、歌詞、段落、來源
3. Normalizer：正規化文字
4. Deduplicator：重複歌曲判斷
5. Import Staging：匯入暫存與審核
6. Search API：歌詞搜尋
7. PPT Generator：產生 PowerPoint
8. Admin API：後台管理、審核、修正
```

其中最花時間的是：

```text
Crawler + Parser + Normalizer + Deduplicator + 人工審核流程
```

不是 API 查詢本身。

---

## 4. 第一版建議架構

```text
Vue 3 Frontend
        ↓
FastAPI Backend
        ↓
PostgreSQL
        ↓
Meilisearch
        ↓
python-pptx
```

### 技術組合

| 功能 | 建議技術 |
|---|---|
| 後端 API | FastAPI |
| ORM | SQLAlchemy |
| Migration | Alembic |
| 資料庫 | PostgreSQL |
| 搜尋引擎 | Meilisearch |
| 爬蟲 | httpx / requests |
| HTML 解析 | BeautifulSoup / lxml |
| 模糊比對 | rapidfuzz |
| 繁簡轉換 | OpenCC |
| PPT 產生 | python-pptx |
| 背景任務 | RQ / Celery / FastAPI BackgroundTasks |
| 快取 | Redis，可第二階段再加 |

---

## 5. 第一版資料流程

```text
外部網站 URL / 搜尋結果
        ↓
Crawler 抓取 HTML
        ↓
Parser 解析歌名與歌詞
        ↓
Normalizer 正規化歌詞
        ↓
Deduplicator 判斷是否重複
        ↓
ImportStaging 暫存
        ↓
人工審核
        ↓
正式寫入 Songs / SongLines / SongSlides
        ↓
同步到 Meilisearch
        ↓
前端搜尋
        ↓
選歌
        ↓
PPT 預覽與微調
        ↓
產生 PPTX
```

---

## 6. 為什麼第一版不建議 Go

Go 的執行效能很好，但本專案第一版的瓶頸不是 CPU，也不是高併發。

第一版真正的瓶頸是：

```text
資料來源很髒
HTML 格式不同
同歌不同名
同歌不同版本
祢 / 你 / 袮 不一致
繁簡混用
副歌重複次數不同
分行方式不同
PPT 切頁需要人工調整
```

這類問題用 Python 處理會比較快。

Go 適合後期：

```text
穩定 API
高併發搜尋
權限管理
任務調度
單一執行檔部署
```

但不適合第一版就硬上。

---

## 7. 長期架構建議

如果未來要產品化，可以演進成：

```text
Vue 3 Frontend
        ↓
Go API Service
        ↓
PostgreSQL
        ↓
Meilisearch

Python Worker Service
        ↓
Crawler
Parser
Normalizer
Deduplicator
PPT Generator
```

### 分工

| 模組 | 語言 |
|---|---|
| API | Go |
| 權限 | Go |
| 搜尋查詢 | Go |
| 任務派發 | Go |
| 爬蟲 | Python |
| 歌詞清理 | Python |
| 相似度比對 | Python |
| PPT 產生 | Python |

這樣會比單一語言硬吃全部更合理。

---

## 8. MVP 開發順序

### 第一階段：核心可用

```text
1. 建立 FastAPI 專案
2. 建立 PostgreSQL 資料表
3. 建立 Songs / SongLines / SongSlides
4. 做手動貼上歌詞匯入
5. 做文字正規化
6. 做基本搜尋 API
7. 做 PPT 產生 API
8. 前端串接搜尋與下載 PPT
```

### 第二階段：外部來源匯入

```text
1. 建立 ImportStaging
2. 實作 TaiwanBible 單首 URL 匯入
3. 解析歌名、歌詞、來源 ID
4. 判斷重複資料
5. 建立待審核畫面
6. 審核通過後正式入庫
```

### 第三階段：搜尋強化

```text
1. 加入 Meilisearch
2. 支援打字即時搜尋
3. 支援模糊比對
4. 支援歌名、歌詞、別名搜尋
5. 支援命中句顯示
```

### 第四階段：PPT 編輯強化

```text
1. 每首歌預設切頁
2. 每次聚會可建立自己的歌單
3. 支援現場微調每頁文字
4. 支援 PPT 樣板
5. 支援多首歌一次輸出 PPT
```

---

## 9. 資料量與效能估算

### 資料量

假設 20,000 首歌：

| 項目 | 估算 |
|---|---:|
| 歌詞原文 | 100MB～300MB |
| 正規化歌詞 | 100MB～300MB |
| 每行資料 | 300MB～800MB |
| 預切 PPT 頁 | 100MB～300MB |
| 索引 | 300MB～1GB |
| 總量 | 約 500MB～2GB |

即使做得很肥，大多也在 3～5GB 內。

### 查詢速度

| 查詢方式 | 速度估算 |
|---|---:|
| PostgreSQL LIKE | 100ms～1s |
| PostgreSQL pg_trgm | 50ms～300ms |
| Meilisearch | 10ms～50ms |
| API 往返後體感 | 50ms～150ms |

兩萬首詩歌不是大資料，搜尋速度不是主要問題。

---

## 10. 最重要的提醒

本專案不要直接：

```text
爬蟲 → 正式資料表 → 直接搜尋與產 PPT
```

應該要：

```text
爬蟲 → ImportStaging → 正規化 → 去重 → 人工審核 → 正式資料表
```

原因是詩歌資料一定會有：

```text
同歌不同名
不同版本
錯字
漏字
繁簡差異
祢 / 你 / 袮 差異
分行差異
副歌重複差異
來源錯誤
```

如果沒有暫存與審核流程，資料庫很快會變成資料怪獸。

---

## 11. 最終建議

第一版：

```text
Python + FastAPI + PostgreSQL + Meilisearch + python-pptx
```

第二版：

```text
Python API + Python Worker + Meilisearch
```

產品化後：

```text
Go API + Python Worker
```

一句話：

```text
第一版用 Python，因為你現在需要的是快速做出可用系統；Go 留給後期效能與部署優化。
```
