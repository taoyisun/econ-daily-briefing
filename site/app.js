/* 每日学术简报前端:读取 data.json,按 tab 渲染 */
let DATA = null;
let state = { tab: "papers", rel: "all", q: "", src: "all" };

// 每个 tab 的"来源"字段
const SOURCE_FIELD = { papers: "journal", working_papers: "source", news: "source", reports: "source" };

const $ = (s) => document.querySelector(s);
const esc = (s) => (s || "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ---------- 主题 ----------
function initTheme() {
  const saved = localStorage.getItem("theme");
  const dark = saved ? saved === "dark"
    : window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  $("#themeBtn").onclick = () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("theme", next);
  };
}

// ---------- 数据 ----------
async function load() {
  const r = await fetch("data.json?_=" + Date.now());
  DATA = await r.json();
  const d = new Date(DATA.generated_at);
  $("#updatedAt").textContent = "更新于 " + d.toLocaleString("zh-CN", { hour12: false });
  render();
}

function relOf(it) { return it.ai_relevance || it.relevance || "low"; }

function renderSourceChips() {
  const box = $("#sourceFilter");
  const field = SOURCE_FIELD[state.tab];
  if (!field || !DATA) { box.innerHTML = ""; return; }
  const counts = {};
  (DATA[state.tab] || []).forEach((it) => {
    const s = it[field] || "其他";
    counts[s] = (counts[s] || 0) + 1;
  });
  const names = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);
  box.innerHTML =
    `<button class="chip ${state.src === "all" ? "active" : ""}" data-src="all">全部来源</button>` +
    names.map((n) =>
      `<button class="chip ${state.src === n ? "active" : ""}" data-src="${esc(n)}">${esc(n)} · ${counts[n]}</button>`
    ).join("");
  box.querySelectorAll(".chip").forEach((b) => {
    b.onclick = () => { state.src = b.dataset.src; render(); };
  });
}

function matches(it) {
  if (state.src !== "all") {
    const field = SOURCE_FIELD[state.tab];
    if (field && (it[field] || "其他") !== state.src) return false;
  }
  if (state.rel !== "all") {
    const r = relOf(it);
    if (state.rel === "high" && r !== "high") return false;
    if (state.rel === "medium" && r === "low") return false;
  }
  if (state.q) {
    const hay = [it.title, it.title_zh, it.authors, it.journal, it.source, it.name]
      .join(" ").toLowerCase();
    if (!hay.includes(state.q)) return false;
  }
  return true;
}

// ---------- 渲染 ----------
function itemCard(it) {
  const rel = relOf(it);
  const meta = [];
  if (it.journal) meta.push(`<span class="badge">${esc(it.journal)}</span>`);
  if (it.source && !it.journal) meta.push(`<span class="badge">${esc(it.source)}</span>`);
  if (it.authors) meta.push(esc(it.authors));
  if (it.published) meta.push(it.published.slice(0, 10));
  if (rel === "high") meta.push(`<span class="tag high">🔥 高相关</span>`);
  (it.topics || []).forEach((t) => meta.push(`<span class="tag">${esc(t)}</span>`));

  const abstract = it.abstract || it.summary || "";
  let body = "";
  if (it.abstract_zh) body += `<div class="abstract-zh">${esc(it.abstract_zh)}</div>`;
  if (abstract)
    body += `<details><summary>英文摘要</summary><div class="abstract">${esc(abstract)}</div></details>`;

  return `<div class="card ${rel === "high" ? "high" : ""}">
    <div class="card-title"><a href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.title)}</a></div>
    ${it.title_zh ? `<div class="card-title-zh">${esc(it.title_zh)}</div>` : ""}
    <div class="card-meta">${meta.join(" ")}</div>
    ${it.ai_reason ? `<div class="ai-reason">💡 ${esc(it.ai_reason)}</div>` : ""}
    ${body}
  </div>`;
}

function confCard(c) {
  let dl = "待确认";
  let cls = "";
  if (c.deadline) {
    const days = Math.ceil((new Date(c.deadline) - Date.now()) / 86400000);
    dl = `${c.deadline}(${days >= 0 ? "剩 " + days + " 天" : "已截止"})`;
    if (days >= 0 && days <= 30) cls = "soon";
  }
  return `<div class="card">
    <div class="card-title"><a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.name)}</a></div>
    <div class="card-meta">
      <span>投稿截止:<span class="conf-deadline ${cls}">${esc(dl)}</span></span>
      ${c.event_date ? `<span>会期:${esc(c.event_date)}</span>` : ""}
      ${c.location ? `<span>${esc(c.location)}</span>` : ""}
    </div>
    ${c.notes ? `<div class="abstract">${esc(c.notes)}</div>` : ""}
  </div>`;
}

function render() {
  if (!DATA) return;
  const el = $("#content");
  $("#filters").style.display = state.tab === "conferences" ? "none" : "flex";
  renderSourceChips();

  if (state.tab === "conferences") {
    const confs = [...(DATA.conferences || [])].sort((a, b) =>
      (a.deadline || "9999") < (b.deadline || "9999") ? -1 : 1);
    el.innerHTML = confs.length
      ? confs.map(confCard).join("")
      : `<div class="empty">暂无会议信息 —— 编辑仓库里的 conferences.yml 添加</div>`;
    return;
  }

  const items = (DATA[state.tab] || []).filter(matches);
  if (!items.length) {
    el.innerHTML = `<div class="empty">没有符合条件的内容</div>`;
    return;
  }

  // 期刊论文按 tier 分组,其余按时间平铺
  if (state.tab === "papers") {
    const groups = {};
    items.forEach((it) => (groups[it.tier || "其他"] ||= []).push(it));
    const order = ["Top-5", "Public", "Urban", "其他"];
    const label = { "Top-5": "Top-5 综合", Public: "公共经济 / 财政", Urban: "城市 / 区域" };
    el.innerHTML = order.filter((t) => groups[t]).map((t) =>
      `<div class="group-head">${label[t] || t} · ${groups[t].length} 篇</div>` +
      groups[t].map(itemCard).join("")).join("");
  } else {
    el.innerHTML = items.map(itemCard).join("");
  }
}

// ---------- 事件 ----------
document.querySelectorAll(".tab").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    state.tab = b.dataset.tab;
    state.src = "all";
    render();
  };
});
document.querySelectorAll("#relevanceFilter .chip").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll("#relevanceFilter .chip").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    state.rel = b.dataset.rel;
    render();
  };
});
$("#searchBox").oninput = (e) => { state.q = e.target.value.trim().toLowerCase(); render(); };

initTheme();
load();
