const SECTIONS = {
  news: { label: "Новости", icon: "📰", hint: "Оперативные факты" },
  stats: { label: "Статистика", icon: "📊", hint: "Результаты и цифры" },
  analytics: { label: "Аналитика", icon: "🧠", hint: "Авторские разборы" },
};

const CATEGORIES = {
  all: "Все",
  match: "Матч/турнир",
  transfers: "Трансферы",
  statements: "Заявления",
  records: "Рекорды",
  scandals: "Скандалы",
  rumors: "Слухи",
  injury: "Травмы/риск",
  russians: "Наши за рубежом",
  other: "Прочее",
};

const state = { items: [], section: "news", filter: "all" };

const $ = (sel) => document.querySelector(sel);

function fmtDate(iso) {
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
}

function fmtDateTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return d.toLocaleString("ru-RU", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

function catKey(c) {
  return CATEGORIES[c] ? c : "other";
}

function sectionKey(s) {
  return SECTIONS[s] ? s : "news";
}

async function load() {
  try {
    const res = await fetch("data/news.json", { cache: "no-store" });
    const data = await res.json();
    state.items = (data.items || []).slice().sort((a, b) => (a.date < b.date ? 1 : -1));
    renderMeta(data.generated_at);
    renderStats();
    renderSections();
    renderFilters();
    render();
  } catch (e) {
    $("#feed").innerHTML = `<p class="empty">Не удалось загрузить дайджест.</p>`;
  }
}

function renderMeta(generatedAt) {
  if (generatedAt) $("#navMeta").textContent = "обновлено " + fmtDate(generatedAt.slice(0, 10));
}

function sectionItems(section) {
  return state.items.filter((i) => sectionKey(i.section) === section);
}

function renderStats() {
  const stats = Object.keys(SECTIONS).map((s) => [
    sectionItems(s).length,
    SECTIONS[s].label,
  ]);
  $("#heroStats").innerHTML = stats
    .map(([n, l]) => `<div class="stat"><div class="stat__num">${n}</div><div class="stat__label">${l}</div></div>`)
    .join("");
}

function renderSections() {
  $("#sections").innerHTML = Object.keys(SECTIONS)
    .map((s) => {
      const n = sectionItems(s).length;
      return `<button class="seg" data-section="${s}" aria-pressed="${s === state.section}">
        <span class="seg__icon">${SECTIONS[s].icon}</span>
        <span class="seg__label">${SECTIONS[s].label}</span>
        <span class="seg__count">${n}</span>
      </button>`;
    })
    .join("");
  $("#sections")
    .querySelectorAll(".seg")
    .forEach((btn) =>
      btn.addEventListener("click", () => {
        state.section = btn.dataset.section;
        state.filter = "all";
        $("#sections")
          .querySelectorAll(".seg")
          .forEach((b) => b.setAttribute("aria-pressed", b.dataset.section === state.section));
        renderFilters();
        render();
      })
    );
}

function renderFilters() {
  const present = new Set(sectionItems(state.section).map((i) => catKey(i.category)));
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
  const when = fmtDateTime(item.published_at) || fmtDate(item.date);
  const bullets = (item.bullets || []).length
    ? `<ul class="card__bullets">${item.bullets.map((b) => `<li>${escapeHTML(b)}</li>`).join("")}</ul>`
    : "";
  const summary = item.summary
    ? `<p class="card__summary">${escapeHTML(item.summary)}</p>`
    : "";
  const related = (item.related || []).length
    ? `<div class="card__related"><span class="card__related-label">Ещё:</span> ${item.related
        .map((r) => `<a href="${encodeURI(r.url)}" target="_blank" rel="noopener">${escapeHTML(r.domain || "источник")}</a>`)
        .join(" · ")}</div>`
    : "";
  return `
    <article class="card" style="animation-delay:${Math.min(idx * 60, 400)}ms">
      <div class="card__top">
        <span class="tag tag--${cat}">${label}</span>
        <span class="card__date">${when}</span>
      </div>
      <a class="card__title" href="${encodeURI(item.source_url)}" target="_blank" rel="noopener">${escapeHTML(item.title)}</a>
      ${summary}
      ${bullets}
      ${related}
      <a class="card__source" href="${encodeURI(item.source_url)}" target="_blank" rel="noopener">
        <span class="dot"></span>${escapeHTML(item.source_domain)}
        <span class="card__read">Читать оригинал</span>
        <span class="arrow">→</span>
      </a>
    </article>`;
}

function render() {
  const inSection = sectionItems(state.section);
  const items =
    state.filter === "all"
      ? inSection
      : inSection.filter((i) => catKey(i.category) === state.filter);

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
