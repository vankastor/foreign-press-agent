const CATEGORIES = {
  all: "Все",
  regulation: "Регуляции",
  ma: "M&A",
  operators: "Операторы",
  product: "Продукт",
  analytics: "Аналитика",
  sports: "Спорт",
  other: "Прочее",
};

const state = { items: [], filter: "all" };

const $ = (sel) => document.querySelector(sel);

function fmtDate(iso) {
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
}

function catKey(c) {
  return CATEGORIES[c] ? c : "other";
}

async function load() {
  try {
    const res = await fetch("data/news.json", { cache: "no-store" });
    const data = await res.json();
    state.items = (data.items || []).slice().sort((a, b) => (a.date < b.date ? 1 : -1));
    renderMeta(data.generated_at);
    renderStats();
    renderFilters();
    render();
  } catch (e) {
    $("#feed").innerHTML = `<p class="empty">Не удалось загрузить дайджест.</p>`;
  }
}

function renderMeta(generatedAt) {
  if (generatedAt) $("#navMeta").textContent = "обновлено " + fmtDate(generatedAt.slice(0, 10));
}

function renderStats() {
  const items = state.items;
  const sources = new Set(items.map((i) => i.source_domain)).size;
  const days = new Set(items.map((i) => i.date)).size;
  const stats = [
    [items.length, "материалов"],
    [sources, "источников"],
    [days, "дней в архиве"],
  ];
  $("#heroStats").innerHTML = stats
    .map(([n, l]) => `<div class="stat"><div class="stat__num">${n}</div><div class="stat__label">${l}</div></div>`)
    .join("");
}

function renderFilters() {
  const present = new Set(state.items.map((i) => catKey(i.category)));
  const keys = ["all", ...Object.keys(CATEGORIES).filter((k) => k !== "all" && present.has(k))];
  $("#filters").innerHTML = keys
    .map(
      (k) =>
        `<button class="chip" data-cat="${k}" aria-pressed="${k === state.filter}">${CATEGORIES[k]}</button>`
    )
    .join("");
  $("#filters")
    .querySelectorAll(".chip")
    .forEach((btn) =>
      btn.addEventListener("click", () => {
        state.filter = btn.dataset.cat;
        $("#filters")
          .querySelectorAll(".chip")
          .forEach((b) => b.setAttribute("aria-pressed", b.dataset.cat === state.filter));
        render();
      })
    );
}

function cardHTML(item, idx) {
  const cat = catKey(item.category);
  const label = CATEGORIES[cat];
  const why = item.why
    ? `<div class="card__why"><b>Почему важно:</b> ${escapeHTML(item.why)}</div>`
    : "";
  return `
    <a class="card" href="${encodeURI(item.source_url)}" target="_blank" rel="noopener"
       style="animation-delay:${Math.min(idx * 60, 400)}ms">
      <div class="card__top">
        <span class="tag tag--${cat}">${label}</span>
        <span class="card__date">${fmtDate(item.date)}</span>
      </div>
      <h3 class="card__title">${escapeHTML(item.title)}</h3>
      <p class="card__summary">${escapeHTML(item.summary)}</p>
      ${why}
      <div class="card__source">
        <span class="dot"></span>${escapeHTML(item.source_domain)}
        <span class="arrow">→</span>
      </div>
    </a>`;
}

function render() {
  const items =
    state.filter === "all"
      ? state.items
      : state.items.filter((i) => catKey(i.category) === state.filter);

  $("#empty").hidden = items.length > 0;

  const groups = {};
  items.forEach((i) => (groups[i.date] ??= []).push(i));
  const dates = Object.keys(groups).sort((a, b) => (a < b ? 1 : -1));

  let idx = 0;
  $("#feed").innerHTML = dates
    .map((date) => {
      const cards = groups[date].map((i) => cardHTML(i, idx++)).join("");
      return `<div class="daygroup">
        <div class="daygroup__label">${fmtDate(date)}</div>
        <div class="grid">${cards}</div>
      </div>`;
    })
    .join("");
}

function escapeHTML(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

load();
