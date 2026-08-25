#!/usr/bin/env python3
"""foreign_press_agent — periodic foreign-press monitor.

Runs headless Claude (reuses the Claude Code subscription, no extra API key),
asks it to search foreign (non-Russian) press for iGaming / sports-betting
industry news relevant to Liga Stavok, then posts the digest into the
"Foreign Press Agent" takopi Telegram thread.

Secrets: the Telegram bot_token + chat_id are read at runtime from
~/.takopi/takopi.toml (the single source of truth). This project's .env holds
only non-secret config (thread id, model). No third-party secrets are stored.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path.home()
TAKOPI_CONFIG = HOME / ".takopi" / "takopi.toml"
PROJECT_DIR = Path(__file__).resolve().parent.parent


def load_env():
    env_path = PROJECT_DIR / ".env"
    cfg = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg


def load_takopi_secrets():
    text = TAKOPI_CONFIG.read_text()
    bot_token = None
    chat_id = None
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r'bot_token\s*=\s*"([^"]+)"', s)
        if m:
            bot_token = m.group(1)
        m = re.match(r"chat_id\s*=\s*(-?\d+)", s)
        if m and chat_id is None:
            chat_id = int(m.group(1))
    if not bot_token or chat_id is None:
        raise RuntimeError("bot_token/chat_id not found in takopi.toml")
    return bot_token, chat_id


def tg_send(bot_token, chat_id, thread_id, text):
    # Telegram messages cap at 4096 chars; chunk on line boundaries.
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    for chunk in chunk_text(text, 3900):
        payload = {
            "chat_id": chat_id,
            "message_thread_id": int(thread_id),
            "text": chunk,
            "disable_web_page_preview": True,
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            res = json.loads(resp.read())
            if not res.get("ok"):
                raise RuntimeError(f"Telegram error: {res}")
        time.sleep(0.5)


def chunk_text(text, size):
    lines = text.split("\n")
    buf = ""
    for ln in lines:
        if len(buf) + len(ln) + 1 > size:
            if buf:
                yield buf
            buf = ln
        else:
            buf = ln if not buf else buf + "\n" + ln
    if buf:
        yield buf


SECTIONS = ["news", "stats", "analytics"]
CATEGORIES = ["match", "transfers", "statements", "records", "scandals", "rumors", "injury", "russians", "other"]

PROMPT = """Ты — редактор-аналитик, ведущий мониторинг зарубежной (не русскоязычной) спортивной прессы для контент-портала «Лига Ставок».

Задача: с помощью WebSearch/WebFetch собери дайджест самых значимых и свежих спортивных материалов, опубликованных за последние 12 часов, из международной спортивной прессы. Сейчас фокус — ФУТБОЛ (топ-чемпионаты, еврокубки, трансферы). Найди как можно больше подходящих материалов — целься в 15–25 штук, распределённых по трём разделам (см. ниже). Не добирай количество ценой качества и свежести: лучше меньше, но каждый — с проверяемым `published_at` не старше 12 часов и реальным новостным поводом. Старайся наполнить все три раздела, а не только «Новости».

⚠️ Строго по свежести: бери только материалы не старше 12 часов на момент запуска. Для каждого материала обязательно укажи точное время публикации (`published_at`) в формате ISO 8601 со смещением зоны, напр. 2026-08-25T07:30:00+02:00. Если время выпуска определить нельзя — НЕ включай материал.

⚠️ Дедуп по сюжету: одна история — один материал. Если один и тот же инфоповод освещают несколько изданий — возьми самый ранний по времени источник как основной, а остальные вынеси в `related` (домен + ссылка). Не давай 10 карточек про одно и то же.

Три раздела (`section`):
- "news" — НОВОСТИ. Короткие оперативные факты: трансфер оформлен, травма, дисквалификация, жеребьёвка, заявление. Ценность — свежесть и конкретика, не авторский разбор.
- "stats" — СТАТИСТИКА. Фактические результаты и цифры: итоги матчей/тура, владение, удары, карточки, тоталы, статистические обзоры. По возможности КОНСОЛИДИРУЙ по туру целиком (а не по каждому матчу отдельно): общий итог тура + ключевые цифры.
- "analytics" — АНАЛИТИКА. Авторские колонки и разборы журналистов: мнение о трансфере, расклад/превью на матч, оценка формы, авторская позиция по итогам. Только полноценные авторские материалы, НЕ короткие новостные заметки.

Приоритетные источники (ищи прежде всего в них):
Marca (marca.com), AS (as.com), Mundo Deportivo (mundodeportivo.com), Sport.es (sport.es), ESPN (espn.com), L'Equipe (lequipe.fr), Get French Football News (getfootballnewsfrance.com), La Gazzetta dello Sport (gazzetta.it), Corriere dello Sport (corrieredellosport.it), Tuttosport (tuttosport.com), Calciomercato (calciomercato.com), Kicker (kicker.de), Sky Sports (skysports.com), Daily Mail Sport (dailymail.co.uk/sport), TalkSPORT (talksport.com), Goal (goal.com), The Athletic (nytimes.com/athletic), O Globo (oglobo.globo.com/esportes), Record (record.pt), NU Sport (nu.nl/sport), AD Sport (ad.nl/sport), Reuters Sports (reuters.com/sports), Sportskeeda (sportskeeda.com), Fanatik (fanatik.com.tr).

Тематики (`category`): match (матч/турнир: расклады, превью, итоги) | transfers (трансферы/деньги) | statements (заявления/цитаты) | records (рекорды) | scandals (скандалы/дисквалификации) | rumors (слухи) | injury (травмы/риск) | russians (наши за рубежом) | other.

Для КАЖДОГО материала прочитай публикацию и выдай `bullets` — 2–4 коротких буллит-поинта по-русски с сутью: о чём материал, главные факты/выводы. Задача буллитов — чтобы читатель по ним понял, о чём статья, и решил, идти ли читать оригинал. НИЧЕГО не додумывай и не галлюцинируй — только то, что реально есть в источнике.

Требования к отбору (иначе материал не берём):
- не старше 12 часов; обязательно с проверяемым `published_at`;
- обязателен новостной повод и конкретика — материал должен раскрывать событие;
- факты проверяемы; только зарубежные источники (не РФ).

ВЕРНИ РЕЗУЛЬТАТ СТРОГО КАК ОДИН JSON-ОБЪЕКТ, без пояснений и без markdown-ограждений:
{
  "date": "YYYY-MM-DD",            // дата дайджеста
  "items": [
    {
      "section": "одно из: news | stats | analytics",
      "title": "цепляющий заголовок по-русски, до 7–9 слов",
      "summary": "одна строка по-русски: о чём этот материал",
      "bullets": ["короткий буллит с сутью", "ещё буллит", "ещё буллит"],
      "category": "одно из: match | transfers | statements | records | scandals | rumors | injury | russians | other",
      "published_at": "время публикации в ISO 8601 со смещением зоны",
      "source_domain": "домен источника, напр. marca.com",
      "source_url": "полный URL публикации",
      "related": [{"domain": "домен другого издания про тот же сюжет", "url": "URL"}]
    }
  ],
  "next_steps": ["1–2 идеи, что из этого стоит развить в материал для портала, по-русски"]
}
Только JSON. Ничего кроме JSON."""


WEB_DATA = PROJECT_DIR / "web" / "data" / "news.json"


def slugify(text):
    s = re.sub(r"[^\w]+", "-", text.lower(), flags=re.UNICODE).strip("-")
    return s[:60] or "item"


def extract_json(text):
    """Pull the first JSON object out of Claude's text output (ignores prose/fences)."""
    start = text.find("{")
    if start == -1:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
        return obj
    except json.JSONDecodeError:
        return None


def normalize_items(payload):
    date = payload.get("date") or datetime.now().strftime("%Y-%m-%d")
    items = []
    for it in payload.get("items", []):
        url = (it.get("source_url") or "").strip()
        title = (it.get("title") or "").strip()
        if not title:
            continue
        cat = (it.get("category") or "other").strip().lower()
        if cat not in CATEGORIES:
            cat = "other"
        section = (it.get("section") or "news").strip().lower()
        if section not in SECTIONS:
            section = "news"
        bullets = [b.strip() for b in (it.get("bullets") or []) if isinstance(b, str) and b.strip()][:4]
        related = []
        for r in (it.get("related") or []):
            if isinstance(r, dict) and (r.get("url") or "").strip():
                related.append({
                    "domain": (r.get("domain") or "").strip(),
                    "url": (r.get("url") or "").strip(),
                })
        items.append({
            "id": f"{date}-{slugify(title)}",
            "date": it.get("date", date),
            "section": section,
            "title": title,
            "summary": (it.get("summary") or "").strip(),
            "bullets": bullets,
            "category": cat,
            "published_at": (it.get("published_at") or "").strip(),
            "source_domain": (it.get("source_domain") or "").strip(),
            "source_url": url,
            "related": related,
        })
    return date, items


MAX_AGE_HOURS = 12


def parse_dt(s):
    """Parse an ISO 8601 datetime (with time component). Returns aware datetime or None."""
    if not s:
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:  # no offset given — assume UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def filter_fresh(items, max_age_hours=MAX_AGE_HOURS):
    """Keep only items with a verifiable publish time within the last max_age_hours."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)
    future_skew = now + timedelta(hours=2)  # tolerate small clock/timezone skew
    fresh, dropped = [], 0
    for it in items:
        dt = parse_dt(it.get("published_at"))
        if dt is not None and cutoff <= dt <= future_skew:
            fresh.append(it)
        else:
            dropped += 1
    return fresh, dropped


MAX_ARCHIVE = 2000


def merge_web_data(new_items):
    """Merge new items into the web archive, dedup by source_url/id. Returns count added."""
    try:
        existing = json.loads(WEB_DATA.read_text()).get("items", [])
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    def key_of(it):
        return it.get("source_url") or it.get("id")

    existing_keys = {key_of(it) for it in existing if key_of(it)}
    added = sum(1 for it in new_items if key_of(it) and key_of(it) not in existing_keys)

    seen = set()
    merged = []
    for it in new_items + existing:
        k = key_of(it)
        if k and k in seen:
            continue
        if k:
            seen.add(k)
        merged.append(it)
    merged.sort(key=lambda x: x.get("date", ""), reverse=True)
    merged = merged[:MAX_ARCHIVE]

    WEB_DATA.parent.mkdir(parents=True, exist_ok=True)
    WEB_DATA.write_text(json.dumps(
        {"generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
         "items": merged},
        ensure_ascii=False, indent=2,
    ))
    return added


def render_telegram(date, items, next_steps):
    lines = [f"🏟 Foreign Sports Digest — {date}", ""]
    section_hdr = {"news": "📰 НОВОСТИ", "stats": "📊 СТАТИСТИКА", "analytics": "🧠 АНАЛИТИКА"}
    for section in SECTIONS:
        group = [it for it in items if it.get("section") == section]
        if not group:
            continue
        lines.append(section_hdr[section])
        lines.append("")
        for it in group:
            lines.append(it["title"])
            if it["summary"]:
                lines.append(it["summary"])
            for b in it.get("bullets", []):
                lines.append(f"• {b}")
            if it["source_domain"]:
                lines.append(f"Источник: {it['source_domain']} — {it['source_url']}")
            lines.append("")
    if next_steps:
        lines.append("Next steps:")
        for ns in next_steps:
            lines.append(f"— {ns}")
    return "\n".join(lines).strip()


def git_publish(count):
    """Commit the refreshed web data and push so the public site updates."""
    try:
        subprocess.run(["git", "add", "web/data/news.json"],
                       cwd=str(PROJECT_DIR), check=True, capture_output=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"],
                          cwd=str(PROJECT_DIR)).returncode == 0:
            return True, "nothing to commit"
        subprocess.run(
            ["git", "-c", "user.name=Ivan Kastornov", "-c", "user.email=vankastor@local",
             "commit", "-m", f"web: +{count} news items ({datetime.now():%Y-%m-%d})"],
            cwd=str(PROJECT_DIR), check=True, capture_output=True, text=True,
        )
        subprocess.run(["git", "push"], cwd=str(PROJECT_DIR),
                       check=True, capture_output=True, text=True, timeout=120)
        return True, ""
    except subprocess.CalledProcessError as e:
        return False, (e.stderr or e.stdout or str(e))[:300]
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:300]


def main():
    cfg = load_env()
    thread_id = cfg.get("FPA_THREAD_ID") or os.environ.get("FPA_THREAD_ID")
    model = cfg.get("FPA_MODEL", "claude-opus-5")
    if not thread_id:
        print("FPA_THREAD_ID not set", file=sys.stderr)
        sys.exit(1)

    bot_token, chat_id = load_takopi_secrets()
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    print(f"[{now}] foreign_press_agent run start", flush=True)

    cmd = [
        "claude", "-p", PROMPT,
        "--model", model,
        "--allowedTools", "WebSearch", "WebFetch",
        "--output-format", "text",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=1200,
            cwd=str(PROJECT_DIR),
        )
    except subprocess.TimeoutExpired:
        tg_send(bot_token, chat_id, thread_id,
                "⚠️ foreign_press_agent: превышен таймаут 20 мин, дайджест не собран.")
        print("timeout", file=sys.stderr)
        sys.exit(1)

    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        err = (proc.stderr or "").strip()[:500]
        msg = f"⚠️ foreign_press_agent: claude завершился с ошибкой (rc={proc.returncode}). {err}"
        tg_send(bot_token, chat_id, thread_id, msg)
        print(msg, file=sys.stderr)
        sys.exit(1)

    payload = extract_json(out)
    if not payload or not payload.get("items"):
        # Fallback: preserve original behavior — post whatever Claude returned.
        header = f"🏟 Foreign Sports Digest — {now}\n\n"
        tg_send(bot_token, chat_id, thread_id, header + out)
        print(f"[{now}] posted raw digest ({len(out)} chars); JSON parse failed",
              file=sys.stderr)
        return

    date, items = normalize_items(payload)
    items, dropped = filter_fresh(items)
    if not items:
        tg_send(bot_token, chat_id, thread_id,
                f"🏟 Foreign Sports Digest — {date}\n\n"
                f"За последние {MAX_AGE_HOURS} ч свежих материалов не нашлось "
                f"(отброшено устаревших/без даты: {dropped}).")
        print(f"[{now}] no fresh items (<{MAX_AGE_HOURS}h); dropped {dropped}",
              file=sys.stderr)
        return

    added = merge_web_data(items)
    ok, err = git_publish(added)
    if not ok:
        print(f"[{now}] git publish failed: {err}", file=sys.stderr)

    tg_send(bot_token, chat_id, thread_id,
            render_telegram(date, items, payload.get("next_steps", [])))
    print(f"[{now}] posted {len(items)} items to thread {thread_id} "
          f"(dropped {dropped} stale); web +{added} (push={'ok' if ok else 'fail'})",
          flush=True)


if __name__ == "__main__":
    main()
