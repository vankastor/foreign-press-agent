const SECTIONS = {
  news: { label: "Новости", icon: "📰", hint: "Оперативные факты" },
  analytics: { label: "Аналитика", icon: "🧠", hint: "Авторские разборы" },
  russians: { label: "Наши", icon: "🇷🇺", hint: "Россияне за рубежом" },
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

const COUNTRIES = {
  all: "Все страны",
  england: "Англия",
  france: "Франция",
  spain: "Испания",
  italy: "Италия",
  germany: "Германия",
  portugal: "Португалия",
  turkey: "Турция",
  netherlands: "Нидерланды",
  eurocups: "Еврокубки",
  other: "Прочее",
};

const COUNTRY_ORDER = [
  "england", "france", "spain", "italy", "germany",
  "portugal", "turkey", "netherlands", "eurocups", "other",
];

// Fallback: derive country from the source domain when item.country is absent
// (archive items predate the parser's `country` field). Domains whose TLD already
// encodes the country (.it/.es/.de/.pt/.fr/.nl/.tr/.co.uk) are handled by TLD_COUNTRY;
// this map only covers country-specific .com/.net outlets and ambiguous cases.
const DOMAIN_COUNTRY = {
  "goal.com": "england", "skysports.com": "england", "football365.com": "england",
  "footballtransfers.com": "england", "theguardian.com": "england", "onefootball.com": "england",
  "talksport.com": "england", "90min.com": "england", "givemesport.com": "england",
  "caughtoffside.com": "england", "teamtalk.com": "england", "football.london": "england",
  "livescore.com": "england",
  "footmercato.net": "france", "getfootballnewsfrance.com": "france", "rmcsport.bfmtv.com": "france",
  "marca.com": "spain", "as.com": "spain", "mundodeportivo.com": "spain", "sport.es": "spain",
  "relevo.com": "spain", "fichajes.net": "spain", "getfootballnewsspain.com": "spain",
  "eldesmarque.com": "spain", "libertaddigital.com": "spain", "lagrada.org": "spain", "elpais.com": "spain",
  "calciomercato.com": "italy", "tuttosport.com": "italy", "football-italia.net": "italy",
  "tuttomercatoweb.com": "italy", "gianlucadimarzio.com": "italy", "getfootballnewsitaly.com": "italy",
  "kicker.de": "germany", "sport1.de": "germany", "getfootballnewsgermany.com": "germany",
  "fcbinside.com": "germany", "bulinews.com": "germany", "bundesliga.com": "germany",
  "sporx.com": "turkey",
  "uefa.com": "eurocups",
};

const TLD_COUNTRY = {
  ".co.uk": "england", ".uk": "england", ".fr": "france", ".es": "spain",
  ".it": "italy", ".de": "germany", ".pt": "portugal", ".tr": "turkey", ".nl": "netherlands",
};

function countryOf(item) {
  const c = (item.country || "").toLowerCase();
  if (COUNTRIES[c] && c !== "all") return c;
  const dom = (item.source_domain || "").toLowerCase();
  if (DOMAIN_COUNTRY[dom]) return DOMAIN_COUNTRY[dom];
  for (const tld in TLD_COUNTRY) {
    if (dom.endsWith(tld)) return TLD_COUNTRY[tld];
  }
  return "other";
}

const state = { items: [], section: "news", country: "all" };

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
    renderCountries();
    render();
  } catch (e) {
    $("#feed").innerHTML = `<p class="empty">Не удалось загрузить дайджест.</p>`;
  }
}

function renderMeta(generatedAt) {
  if (generatedAt) $("#navMeta").textContent = "обновлено " + fmtDate(generatedAt.slice(0, 10));
}

function sectionItems(section) {
  // "russians" is a cross-cutting lens: every «наши за рубежом» item, regardless
  // of whether it lives in news or analytics. Its cards keep their own section's
  // rendering (bullets stay analytics-only via item.section in cardHTML).
  if (section === "russians") {
    return state.items.filter((i) => catKey(i.category) === "russians");
  }
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
        state.country = "all";
        $("#sections")
          .querySelectorAll(".seg")
          .forEach((b) => b.setAttribute("aria-pressed", b.dataset.section === state.section));
        renderCountries();
        render();
      })
    );
}

function renderCountries() {
  const present = new Set(sectionItems(state.section).map(countryOf));
  const keys = ["all", ...COUNTRY_ORDER.filter((k) => present.has(k))];
  $("#countries").innerHTML = keys
    .map(
      (k) =>
        `<button class="chip" data-country="${k}" aria-pressed="${k === state.country}">${COUNTRIES[k]}</button>`
    )
    .join("");
  $("#countries")
    .querySelectorAll(".chip")
    .forEach((btn) =>
      btn.addEventListener("click", () => {
        state.country = btn.dataset.country;
        $("#countries")
          .querySelectorAll(".chip")
          .forEach((b) => b.setAttribute("aria-pressed", b.dataset.country === state.country));
        render();
      })
    );
}

function cardHTML(item, idx) {
  const cat = catKey(item.category);
  const label = CATEGORIES[cat];
  const when = fmtDateTime(item.published_at) || fmtDate(item.date);
  // Bullets only in Аналитика; Новости is a flat headline+subhead feed.
  const bullets =
    sectionKey(item.section) === "analytics" && (item.bullets || []).length
      ? `<ul class="row__bullets">${item.bullets.map((b) => `<li>${escapeHTML(b)}</li>`).join("")}</ul>`
      : "";
  const summary = item.summary
    ? `<p class="row__summary">${escapeHTML(item.summary)}</p>`
    : "";
  const related = (item.related || []).length
    ? `<span class="row__related"><span class="row__related-label">Ещё:</span> ${item.related
        .map((r) => `<a href="${encodeURI(r.url)}" target="_blank" rel="noopener">${escapeHTML(r.domain || "источник")}</a>`)
        .join(" · ")}</span>`
    : "";
  const ruBadge = item.ru_covered
    ? `<span class="ru-badge" title="Сюжет уже освещён российскими спортивными СМИ${
        item.ru_source ? " · " + escapeHTML(item.ru_source) : ""
      }"><span class="ru-badge__flag">🇷🇺</span>Уже в РФ</span>`
    : "";
  return `
    <article class="row" style="animation-delay:${Math.min(idx * 40, 320)}ms">
      <div class="row__meta">
        <span class="tag tag--${cat}">${label}</span>
        <time class="row__time">${when}</time>
        ${ruBadge}
      </div>
      <div class="row__body">
        <a class="row__title" href="${encodeURI(item.source_url)}" target="_blank" rel="noopener">${escapeHTML(item.title)}</a>
        ${summary}
        ${bullets}
        <div class="row__foot">
          <a class="row__source" href="${encodeURI(item.source_url)}" target="_blank" rel="noopener">
            <span class="dot"></span>${escapeHTML(item.source_domain)}
            <span class="row__read">Читать оригинал</span>
            <span class="arrow">→</span>
          </a>
          ${related}
        </div>
      </div>
    </article>`;
}

function render() {
  let items = sectionItems(state.section);
  if (state.country !== "all") {
    items = items.filter((i) => countryOf(i) === state.country);
  }

  $("#empty").hidden = items.length > 0;

  const groups = {};
  items.forEach((i) => (groups[i.date] ??= []).push(i));
  const dates = Object.keys(groups).sort((a, b) => (a < b ? 1 : -1));

  let idx = 0;
  $("#feed").innerHTML = dates
    .map((date) => {
      const rows = groups[date].map((i) => cardHTML(i, idx++)).join("");
      return `<div class="daygroup">
        <div class="daygroup__label">${fmtDate(date)}</div>
        <div class="list">${rows}</div>
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
