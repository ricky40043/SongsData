const state = {
  q: "",
  offset: 0,
  limit: 50,
  admin: false,
  currentSongId: null,
};

const $ = (id) => document.getElementById(id);

async function fetchJson(url, options = undefined) {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function loadStats() {
  const stats = await fetchJson("/api/stats");
  $("stats").textContent = state.admin
    ? `歌曲 ${stats.songs} 首 · 暫存 ${stats.staging} 筆 · 待審核 ${stats.pending} 筆`
    : `歌曲 ${stats.songs} 首`;
}

async function loadSongs() {
  const params = new URLSearchParams({
    q: state.q,
    offset: String(state.offset),
    limit: String(state.limit),
  });
  const data = await fetchJson(`/api/songs?${params}`);
  $("listTitle").textContent = state.q ? `搜尋：${state.q}` : "所有歌曲";
  $("countText").textContent = `${data.total} 首`;

  const container = $("songs");
  container.innerHTML = "";
  for (const song of data.items) {
    const btn = document.createElement("button");
    btn.className = "song-row";
    btn.type = "button";

    let titleHtml = escapeHtml(song.title);
    const query = state.q ? state.q.trim() : "";
    if (query) {
      const escapedQuery = escapeRegExp(query);
      const regex = new RegExp(`(${escapedQuery})`, "gi");
      titleHtml = titleHtml.replace(regex, `<mark>$1</mark>`);
    }

    btn.innerHTML = `<strong>${titleHtml}</strong><span>#${song.id}</span>`;
    btn.addEventListener("click", () => loadSong(song.id));
    container.appendChild(btn);
  }
  if (!data.items.length) {
    container.innerHTML = `<div class="song-row"><strong>沒有結果</strong><span>換一個關鍵字試試</span></div>`;
  }

  $("prevBtn").disabled = state.offset === 0;
  $("nextBtn").disabled = state.offset + state.limit >= data.total;
}

async function loadSong(id) {
  state.currentSongId = id;
  const song = await fetchJson(`/api/songs/${id}`);
  $("reviewPanel").hidden = true;
  $("lyrics").hidden = false;

  let titleHtml = escapeHtml(song.title);
  const query = state.q ? state.q.trim() : "";
  if (query) {
    const escapedQuery = escapeRegExp(query);
    const regex = new RegExp(`(${escapedQuery})`, "gi");
    titleHtml = titleHtml.replace(regex, `<mark>$1</mark>`);
  }
  $("songTitle").innerHTML = titleHtml;

  let lyricsHtml = escapeHtml(song.lyrics || "沒有歌詞");
  if (query) {
    const escapedQuery = escapeRegExp(query);
    const regex = new RegExp(`(${escapedQuery})`, "gi");
    lyricsHtml = lyricsHtml.replace(regex, `<mark>$1</mark>`);
  }

  $("lyrics").innerHTML = lyricsHtml;
  $("pptLink").hidden = false;
  $("pptLink").href = `/api/songs/${id}/pptx`;
}

function escapeRegExp(string) {
  return string.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function loadPendingReviews() {
  const data = await fetchJson("/api/imports/pending?limit=50");
  $("songTitle").textContent = "待審核";
  $("pptLink").hidden = true;
  $("lyrics").hidden = true;
  $("reviewPanel").hidden = false;

  const panel = $("reviewPanel");
  panel.innerHTML = "";
  if (!data.items.length) {
    panel.innerHTML = `<div class="review-item"><h3>沒有待審核項目</h3></div>`;
    return;
  }

  for (const item of data.items) {
    const div = document.createElement("div");
    div.className = "review-item";
    div.innerHTML = `
      <h3>${escapeHtml(item.title)}</h3>
      <div class="review-meta">
        #${item.id} · ${escapeHtml(item.source_site)} ${escapeHtml(item.source_external_id)}
        · ${escapeHtml(item.duplicate_status)}
        ${item.possible_duplicate_song_id ? `· 可能重複：#${item.possible_duplicate_song_id} ${escapeHtml(item.possible_duplicate_title || "")}` : ""}
      </div>
      <pre class="review-lyrics">${escapeHtml(item.lyrics || "")}</pre>
      <div class="review-actions">
        <button type="button" data-action="duplicate" data-id="${item.id}">標記重複</button>
        <button type="button" data-action="force" data-id="${item.id}">強制新增</button>
        ${item.possible_duplicate_song_id ? `<button type="button" data-action="open" data-id="${item.possible_duplicate_song_id}">看正式歌曲</button>` : ""}
      </div>
    `;
    panel.appendChild(div);
  }
}

async function refreshAll() {
  await Promise.all([loadStats(), loadSongs()]);
}

function doSearch() {
  state.q = $("searchInput").value.trim();
  state.offset = 0;
  refreshAll().catch(showError);
  if (state.currentSongId) {
    loadSong(state.currentSongId).catch(console.error);
  }
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function showError(error) {
  $("stats").textContent = `讀取失敗：${error.message}`;
}

$("searchBtn").addEventListener("click", doSearch);
$("refreshBtn").addEventListener("click", () => refreshAll().catch(showError));
$("adminToggleBtn").addEventListener("click", () => {
  state.admin = !state.admin;
  $("reviewBtn").hidden = !state.admin;
  $("adminToggleBtn").textContent = state.admin ? "一般模式" : "管理";
  refreshAll().catch(showError);
});
$("reviewBtn").addEventListener("click", () => loadPendingReviews().catch(showError));
$("reviewPanel").addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const id = button.dataset.id;
  if (button.dataset.action === "open") {
    await loadSong(id);
    return;
  }
  const actionUrl =
    button.dataset.action === "duplicate"
      ? `/api/imports/${id}/duplicate`
      : `/api/imports/${id}/approve-force`;
  await fetchJson(actionUrl, { method: "POST" });
  await Promise.all([loadStats(), loadPendingReviews()]);
});
$("searchInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    doSearch();
  }
});
$("searchInput").addEventListener("search", (event) => {
  doSearch();
});
$("prevBtn").addEventListener("click", () => {
  state.offset = Math.max(0, state.offset - state.limit);
  refreshAll().catch(showError);
});
$("nextBtn").addEventListener("click", () => {
  state.offset += state.limit;
  refreshAll().catch(showError);
});

refreshAll().catch(showError);
