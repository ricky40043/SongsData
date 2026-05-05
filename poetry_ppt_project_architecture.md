# 詩歌搜尋與 PPT 自動產生系統 - 專案架構目標

## 1. 專案背景

在敬拜、聚會或臨時需要唱詩歌的情境中，常常會遇到以下問題：

- 不知道完整歌名，只記得其中一句歌詞。
- 臨時需要快速找到正確詩歌。
- 找到歌詞後，還需要立即產生可投影的 PPT。
- 不同網站上的歌詞格式、版本、用字可能不同。
- 手動製作 PPT 花時間，而且容易分頁不一致。

本專案目標是建立一套 **本地化詩歌資料庫 + 快速搜尋 + PPT 自動產生系統**。

系統不依賴每次即時查詢外部網站，而是先將外部來源資料整理成自己的標準資料庫，之後搜尋與產 PPT 都直接使用本地資料。

---

## 2. 核心目標

### 2.1 主要目標

使用者輸入一句歌詞後，系統可以快速找到相符詩歌，並根據預先整理好的段落與投影片設定，立即產生 PPT。

```text
輸入一句歌詞
    ↓
搜尋本地詩歌資料庫
    ↓
找到候選詩歌
    ↓
選擇正確歌曲
    ↓
顯示歌詞與 PPT 預覽
    ↓
現場微調
    ↓
產生 PPTX
```

### 2.2 系統定位

本系統不是單純爬蟲，也不是單純 PPT 產生器，而是：

```text
多來源詩歌資料匯入系統
+
詩歌資料標準化系統
+
本地高速搜尋系統
+
歌詞 PPT 自動產生系統
```

---

## 3. 設計原則

### 3.1 本地資料庫優先

外部網站只作為資料來源與補充來源，不作為即時正式查詢來源。

正確流程：

```text
外部網站 / 手動匯入 / 檔案匯入
    ↓
暫存區 ImportStaging
    ↓
解析 / 正規化 / 去重 / 人工審核
    ↓
正式詩歌資料庫
    ↓
搜尋與 PPT 產生
```

不建議流程：

```text
使用者搜尋
    ↓
即時爬多個網站
    ↓
直接產 PPT
```

原因：

- 外部網站速度不可控。
- HTML 結構可能改版。
- 可能被網站擋請求。
- 歌詞版本可能不一致。
- 歌詞正確性與授權狀態不明。
- 現場使用不能等待網路爬取。

---

## 4. 系統總體架構

```text
Frontend - Vue 3
    ↓
Backend API - .NET 8 Web API
    ↓
Database - SQL Server
    ↓
Search Layer - SQL / Meilisearch
    ↓
PPT Generator - PptxGenJS / OpenXML / ShapeCrawler
```

### 4.1 前端

建議技術：

- Vue 3
- TypeScript
- Naive UI
- HTML 投影片即時預覽

主要功能：

- 歌詞搜尋
- 搜尋結果列表
- 歌曲詳情
- 歌詞段落編輯
- PPT 預覽
- PPT 設定調整
- 匯入審核後台

---

### 4.2 後端

建議技術：

- .NET 8 Web API
- Entity Framework Core
- SQL Server
- Background Queue

主要功能：

- 歌曲搜尋 API
- 歌曲管理 API
- 歌詞匯入 API
- 外部網站 Provider 管理
- 歌詞正規化
- 去重判斷
- PPT 產生
- 匯入審核流程

---

### 4.3 搜尋引擎

第一版可先使用 SQL Server 查詢。

後續若需要更好的即時搜尋與模糊搜尋，可加入：

- Meilisearch
- Typesense
- OpenSearch / Elasticsearch

建議順序：

```text
第一版：SQL Server + NormalizedText LIKE
第二版：Meilisearch
第三版：進階模糊搜尋與排名
```

---

### 4.4 PPT 產生器

可選方案：

| 技術 | 說明 | 建議程度 |
|---|---|---:|
| PptxGenJS | Node.js 生 PPT，開發快 | 高 |
| OpenXML SDK | .NET 原生，控制力高但較硬 | 中 |
| ShapeCrawler | .NET 操作 PPT，較好寫 | 中高 |
| Aspose.Slides | 功能完整但商業授權 | 視預算 |

建議第一版使用：

```text
.NET API + Node.js PPT Generator Service + PptxGenJS
```

如果想完全 .NET 化，可改用：

```text
.NET API + ShapeCrawler / OpenXML SDK
```

---

## 5. 資料流程

### 5.1 外部資料匯入流程

```text
指定網站 URL / 搜尋結果 / 手動貼上歌詞
    ↓
Crawler / Importer
    ↓
取得 RawTitle / RawLyrics / SourceUrl
    ↓
寫入 SongImportStaging
    ↓
Normalizer 正規化
    ↓
Duplicate Detector 去重判斷
    ↓
Auto Slide Splitter 自動切頁
    ↓
人工審核
    ↓
正式入庫 Songs / SongVersions / SongLines / SongSlides
```

### 5.2 搜尋流程

```text
使用者輸入歌詞片段
    ↓
NormalizeKeyword
    ↓
查 SongLines / SongLyrics / SongAliases
    ↓
計算相似度與排名
    ↓
回傳候選歌曲
    ↓
使用者選歌
```

### 5.3 PPT 產生流程

```text
選擇歌曲
    ↓
讀取 SongSlides 預設投影片
    ↓
套用 PPT Template
    ↓
前端預覽
    ↓
使用者微調
    ↓
建立 SongPresentation
    ↓
產生 PPTX
    ↓
下載
```

---

## 6. 建議資料庫設計

## 6.1 Songs

儲存歌曲主資料。

```sql
CREATE TABLE Songs (
    Id INT IDENTITY PRIMARY KEY,
    Title NVARCHAR(300) NOT NULL,
    NormalizedTitle NVARCHAR(300) NOT NULL,
    Album NVARCHAR(300) NULL,
    Author NVARCHAR(300) NULL,
    Composer NVARCHAR(300) NULL,
    CopyrightNote NVARCHAR(1000) NULL,
    IsVerified BIT NOT NULL DEFAULT 0,
    CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    UpdatedAt DATETIME2 NULL
);
```

---

## 6.2 SongVersions

同一首歌可能有不同版本。

```sql
CREATE TABLE SongVersions (
    Id INT IDENTITY PRIMARY KEY,
    SongId INT NOT NULL,
    VersionName NVARCHAR(100) NOT NULL,
    RawLyrics NVARCHAR(MAX) NOT NULL,
    NormalizedLyrics NVARCHAR(MAX) NOT NULL,
    LyricsHash CHAR(64) NOT NULL,
    IsDefault BIT NOT NULL DEFAULT 0,
    CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    FOREIGN KEY (SongId) REFERENCES Songs(Id)
);
```

---

## 6.3 SongSections

儲存段落，例如 Verse、Chorus、Bridge。

```sql
CREATE TABLE SongSections (
    Id INT IDENTITY PRIMARY KEY,
    SongId INT NOT NULL,
    VersionId INT NULL,
    SectionType NVARCHAR(50) NOT NULL,
    DisplayName NVARCHAR(100) NULL,
    SectionOrder INT NOT NULL,
    FOREIGN KEY (SongId) REFERENCES Songs(Id),
    FOREIGN KEY (VersionId) REFERENCES SongVersions(Id)
);
```

---

## 6.4 SongLines

儲存每一行歌詞，方便搜尋與命中顯示。

```sql
CREATE TABLE SongLines (
    Id INT IDENTITY PRIMARY KEY,
    SongId INT NOT NULL,
    VersionId INT NULL,
    SectionId INT NULL,
    LineOrder INT NOT NULL,
    Text NVARCHAR(500) NOT NULL,
    NormalizedText NVARCHAR(500) NOT NULL,
    FOREIGN KEY (SongId) REFERENCES Songs(Id),
    FOREIGN KEY (VersionId) REFERENCES SongVersions(Id),
    FOREIGN KEY (SectionId) REFERENCES SongSections(Id)
);
```

---

## 6.5 SongSlides

儲存預設 PPT 分頁。

```sql
CREATE TABLE SongSlides (
    Id INT IDENTITY PRIMARY KEY,
    SongId INT NOT NULL,
    VersionId INT NULL,
    SlideOrder INT NOT NULL,
    SectionName NVARCHAR(100) NULL,
    Text NVARCHAR(MAX) NOT NULL,
    LineCount INT NOT NULL,
    Notes NVARCHAR(500) NULL,
    FOREIGN KEY (SongId) REFERENCES Songs(Id),
    FOREIGN KEY (VersionId) REFERENCES SongVersions(Id)
);
```

---

## 6.6 SongAliases

儲存歌曲別名。

```sql
CREATE TABLE SongAliases (
    Id INT IDENTITY PRIMARY KEY,
    SongId INT NOT NULL,
    AliasTitle NVARCHAR(300) NOT NULL,
    NormalizedAliasTitle NVARCHAR(300) NOT NULL,
    FOREIGN KEY (SongId) REFERENCES Songs(Id)
);
```

---

## 6.7 SongSources

儲存來源資訊。

```sql
CREATE TABLE SongSources (
    Id INT IDENTITY PRIMARY KEY,
    SongId INT NOT NULL,
    SourceSite NVARCHAR(100) NOT NULL,
    SourceUrl NVARCHAR(1000) NULL,
    SourceExternalId NVARCHAR(100) NULL,
    ImportedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    FOREIGN KEY (SongId) REFERENCES Songs(Id)
);
```

---

## 6.8 SongImportStaging

匯入暫存區。外部抓回來的資料不直接進正式資料表。

```sql
CREATE TABLE SongImportStaging (
    Id INT IDENTITY PRIMARY KEY,
    SourceSite NVARCHAR(100) NOT NULL,
    SourceUrl NVARCHAR(1000) NULL,
    SourceExternalId NVARCHAR(100) NULL,
    RawTitle NVARCHAR(300) NOT NULL,
    RawLyrics NVARCHAR(MAX) NOT NULL,
    NormalizedTitle NVARCHAR(300) NOT NULL,
    NormalizedLyrics NVARCHAR(MAX) NOT NULL,
    LyricsHash CHAR(64) NOT NULL,
    ParseStatus NVARCHAR(50) NOT NULL,
    DuplicateStatus NVARCHAR(50) NOT NULL,
    PossibleDuplicateSongId INT NULL,
    ErrorMessage NVARCHAR(1000) NULL,
    CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME()
);
```

---

## 6.9 SongPresentations

儲存某一次實際產生 PPT 的版本。

```sql
CREATE TABLE SongPresentations (
    Id INT IDENTITY PRIMARY KEY,
    SongId INT NOT NULL,
    Title NVARCHAR(300) NOT NULL,
    CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    FOREIGN KEY (SongId) REFERENCES Songs(Id)
);
```

---

## 6.10 SongPresentationSlides

儲存當次 PPT 的實際分頁內容。

```sql
CREATE TABLE SongPresentationSlides (
    Id INT IDENTITY PRIMARY KEY,
    PresentationId INT NOT NULL,
    SlideOrder INT NOT NULL,
    Text NVARCHAR(MAX) NOT NULL,
    FontSize INT NULL,
    BackgroundColor NVARCHAR(20) NULL,
    TextColor NVARCHAR(20) NULL,
    FOREIGN KEY (PresentationId) REFERENCES SongPresentations(Id)
);
```

---

## 7. 正規化規則

搜尋用文字需要正規化，顯示用文字保留原始版本。

### 7.1 建議處理項目

```text
祢 → 你
袮 → 你
祂 → 他
衪 → 他
裏 → 裡
臺 → 台
全形空白 → 移除
半形空白 → 移除
標點符號 → 移除
英文大小寫 → 小寫
繁簡轉換 → 統一搜尋版本
```

### 7.2 C# 範例

```csharp
public static string NormalizeLyric(string input)
{
    if (string.IsNullOrWhiteSpace(input))
        return string.Empty;

    return input
        .Trim()
        .Replace(" ", "")
        .Replace("　", "")
        .Replace("，", "")
        .Replace(",", "")
        .Replace("。", "")
        .Replace(".", "")
        .Replace("！", "")
        .Replace("!", "")
        .Replace("？", "")
        .Replace("?", "")
        .Replace("祢", "你")
        .Replace("袮", "你")
        .Replace("祂", "他")
        .Replace("衪", "他")
        .Replace("裏", "裡")
        .Replace("臺", "台")
        .ToLower();
}
```

---

## 8. 去重策略

### 8.1 第一層：來源 ID 去重

同一來源網站、同一外部 ID 不重複匯入。

```text
SourceSite + SourceExternalId
```

例如：

```text
TaiwanBible + 2729
```

---

### 8.2 第二層：Hash 去重

根據正規化後的歌詞產生 Hash。

```text
LyricsHash = SHA256(NormalizedLyricsWithoutSpaces)
```

如果 Hash 相同，基本可視為同一版本。

---

### 8.3 第三層：相似度去重

針對不同來源但內容相近的歌曲，計算相似度。

建議權重：

| 比對項目 | 權重 |
|---|---:|
| 歌名相似度 | 30% |
| 歌詞全文相似度 | 40% |
| 前 4 行相似度 | 20% |
| 專輯 / 作者 / 來源資訊 | 10% |

建議判斷：

| 分數 | 處理方式 |
|---:|---|
| 95 以上 | 自動視為重複 |
| 80～95 | 進入待審核 |
| 80 以下 | 視為不同歌曲 |

---

## 9. 外部網站 Provider 架構

不要把每個網站的解析邏輯寫死在主流程裡。

建議使用 Provider 架構。

```csharp
public interface ILyricCrawler
{
    string SourceSite { get; }

    Task<List<CrawlSongItem>> SearchAsync(string keyword);

    Task<CrawlSongDetail?> GetDetailAsync(string url);
}
```

範例 Provider：

```text
TaiwanBibleCrawler
OtherLyricSiteCrawler
GoogleSearchProvider
ManualPasteImporter
OpenLyricsImporter
OpenLPImporter
```

---

## 10. API 規劃

### 10.1 搜尋歌曲

```http
GET /api/songs/search?keyword=現在活著的不再是我
```

回傳：

```json
{
  "keyword": "現在活著的不再是我",
  "results": [
    {
      "songId": 1,
      "title": "不再是我乃是基督",
      "matchedLine": "現在活著的不再是我",
      "score": 98,
      "isVerified": true
    }
  ]
}
```

---

### 10.2 取得歌曲詳情

```http
GET /api/songs/{songId}
```

---

### 10.3 匯入單首外部歌曲

```http
POST /api/import/song
```

Body：

```json
{
  "sourceSite": "TaiwanBible",
  "sourceUrl": "https://taiwanbible.com/web/lyrics/view.jsp?ID=2729"
}
```

---

### 10.4 查詢待審核匯入資料

```http
GET /api/import/staging?status=Pending
```

---

### 10.5 審核通過匯入資料

```http
POST /api/import/staging/{id}/approve
```

---

### 10.6 產生 PPT

```http
POST /api/songs/{songId}/ppt
```

Body：

```json
{
  "layout": "16:9",
  "linesPerSlide": 4,
  "fontSize": 40,
  "fontFamily": "Microsoft JhengHei",
  "backgroundColor": "#000000",
  "textColor": "#FFFFFF",
  "showTitle": false,
  "showSource": true
}
```

---

## 11. PPT 預設切頁規則

第一版可使用簡單規則：

```text
每頁 2～4 行
空行視為段落分隔
太長的句子允許自動縮小字體
保留原始行順序
副歌重複不自動刪除
```

後續可進階支援：

```text
Verse / Chorus / Bridge / Ending
歌曲流程 V1 → C → V2 → C → B → C
自訂每頁行數
自訂背景
自訂字體
自訂模板
多首歌合併成一份 PPT
```

---

## 12. 效能估算

### 12.1 資料量估算

以 20,000 首詩歌估算：

| 項目 | 粗估 |
|---|---:|
| Songs | 20,000 筆 |
| SongLines | 600,000～1,000,000 筆 |
| SongSlides | 100,000～160,000 筆 |
| 資料庫大小 | 500MB～2GB |
| 含索引與多版本 | 可能 3～5GB |

結論：

```text
20,000 首詩歌不是大資料，SQL Server 可以輕鬆處理。
真正困難的是資料清理，不是容量。
```

---

### 12.2 搜尋速度估算

| 方案 | 預估速度 |
|---|---:|
| SQL LIKE 查 SongLines | 100ms～1 秒 |
| SQL Full-Text Search | 約 50ms～500ms |
| Meilisearch | 約 10ms～100ms |
| API 含網路回應 | 約 50ms～300ms |

第一版可接受目標：

```text
搜尋回應時間：1 秒內
PPT 產生時間：0.5～3 秒
```

---

## 13. 開發階段規劃

## 第一階段：MVP

目標：先做出可以用的最小版本。

功能：

```text
1. 建立 Songs / SongLines / SongSlides 資料表
2. 支援手動貼上歌詞匯入
3. 支援單首 URL 匯入
4. 自動正規化歌詞
5. 自動切 PPT 頁
6. 歌詞搜尋
7. PPT 預覽
8. PPTX 下載
```

預估時間：

```text
約 1～2 週
```

---

## 第二階段：外部資料來源

功能：

```text
1. TaiwanBible Provider
2. 多網站 Provider 架構
3. Google 搜尋輔助找來源
4. 匯入暫存區 SongImportStaging
5. 匯入前預覽
6. 匯入審核
```

預估時間：

```text
約 2～4 週
```

---

## 第三階段：資料品質管理

功能：

```text
1. 歌曲去重
2. 版本管理 SongVersions
3. 別名管理 SongAliases
4. 相似歌曲待審核
5. 歌詞人工修正
6. 段落管理
7. 預設 PPT 分頁管理
```

預估時間：

```text
約 2～4 週
```

---

## 第四階段：正式敬拜工具化

功能：

```text
1. 多首歌歌單 Worship Set
2. 多首歌合併產 PPT
3. PPT 主題模板
4. 歌詞投影模式
5. 歌詞版權註記
6. CCLI / 來源管理
7. 使用者權限
8. 匯入紀錄與異動紀錄
```

預估時間：

```text
約 1～2 個月
```

---

## 14. 主要風險

### 14.1 版權風險

外部網站歌詞不代表可自由使用。

系統應保留：

```text
來源網站
來源網址
匯入時間
匯入者
版權註記
是否確認授權
```

建議外部資料只進入暫存區，正式使用前需要確認。

---

### 14.2 資料品質風險

常見問題：

```text
同歌不同名
同名不同歌
祢 / 你 / 袮
祂 / 他 / 衪
裡 / 裏
繁體 / 簡體
分行不同
副歌重複次數不同
錯字
漏字
不同來源版本不同
```

處理方式：

```text
RawLyrics 保留原文
NormalizedLyrics 搜尋用
SongVersions 管理不同版本
SongAliases 管理別名
DuplicateReview 人工處理疑似重複
```

---

### 14.3 爬蟲風險

不要暴力全站掃描。

建議策略：

```text
1. 優先匯入常用詩歌
2. 支援單首 URL 匯入
3. 支援搜尋不到時外部查詢
4. 背景低頻率補資料
5. 遵守網站使用規範
6. 設定請求間隔與錯誤重試
```

---

## 15. 最終建議

本專案應該先從「自己的詩歌資料庫」開始，而不是從「即時查所有網站」開始。

正確方向：

```text
先匯入
再整理
再審核
再搜尋
再產 PPT
```

第一版只要完成：

```text
手動匯入歌詞
+
單首 URL 匯入
+
本地搜尋
+
自動切頁
+
PPT 下載
```

就已經能解決主要痛點。

後面再逐步加入：

```text
多網站爬蟲
資料去重
版本管理
歌單管理
PPT 模板
敬拜投影流程
```

最重要的原則：

```text
外部資料只進暫存區。
正式可搜尋、可產 PPT 的資料，必須是你自己整理過的標準資料。
```
