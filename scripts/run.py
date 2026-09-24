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


SECTIONS = ["news", "analytics"]
CATEGORIES = ["match", "transfers", "statements", "records", "scandals", "rumors", "injury", "russians", "other"]
COUNTRIES = ["england", "france", "spain", "italy", "germany", "portugal", "turkey", "netherlands", "eurocups", "other"]

PROMPT = """Ты — редактор-аналитик, ведущий мониторинг зарубежной (не русскоязычной) спортивной прессы для контент-портала «Лига Ставок».

Задача: с помощью WebSearch/WebFetch собери дайджест самых значимых и свежих спортивных материалов, опубликованных за последние 6 часов, из международной спортивной прессы. Сейчас фокус — ФУТБОЛ (топ-чемпионаты, еврокубки, трансферы). Обойди ВЕСЬ обязательный список источников (см. ниже) и возьми все подходящие свежие материалы — не ограничивай себя искусственным потолком (ориентир — 15–30 штук, но если качественных свежих больше, бери больше), распределяя по двум разделам. Не добирай количество ценой качества и свежести: каждый материал — с проверяемым `published_at` не старше 6 часов и реальным новостным поводом.

⚠️ Строго по свежести: бери только материалы не старше 6 часов на момент запуска. Для каждого материала обязательно укажи точное время публикации (`published_at`) в формате ISO 8601 со смещением зоны, напр. 2026-08-25T07:30:00+02:00. Если время выпуска определить нельзя — НЕ включай материал.

⚠️ Дедуп по сюжету: одна история — один материал. Если один и тот же инфоповод освещают несколько изданий — возьми самый ранний по времени источник как основной, а остальные вынеси в `related` (домен + ссылка). Не давай 10 карточек про одно и то же.

Два раздела (`section`):
- "news" — НОВОСТИ. Лента оперативных фактов в стиле информагентства: трансфер оформлен, травма, дисквалификация, жеребьёвка, заявление, а ТАКЖЕ результаты матчей/тура и статистика/рекорды (итоги, рекордные серии, важные цифры — их тоже клади сюда, в "news", с `category: records`). Для новостей нужны только ЗАГОЛОВОК и ПОДЗАГОЛОВОК (одна ёмкая строка сути в `summary`) — БЕЗ буллит-поинтов (`bullets` оставь пустым). Держи новость компактной: заголовок + подзаголовок суммарно примерно до 600 знаков. Ценность — свежесть и конкретика.
- "analytics" — АНАЛИТИКА. Авторские колонки и большие разборы журналистов (превью/расклад на матч, мнение о трансфере, оценка формы, авторская позиция по итогам). Ориентир — крупные авторские материалы примерно от 3000+ знаков: сам объём говорит, что это не новость, а разбор. Для аналитики (и ТОЛЬКО для неё) давай `bullets` — 2–4 буллит-поинта с занимательными фактами и инсайтами, выходящими за рамки обычной новостной повестки (напр. Marca публикует разбор про «Реал» — вытащи оттуда любопытную фактуру/выводы). Только полноценные авторские материалы, НЕ короткие новостные заметки.

Опорные страны/лиги (основной фокус): Англия (Премьер-лига), Франция (Лига 1), Испания (Ла Лига), Италия (Серия A), Германия (Бундеслига), Португалия (Примейра), Турция (Суперлига), Нидерланды (Эредивизи). Дополнительно (опционально) — еврокубки: Лига чемпионов, Лига Европы, Лига конференций.

ОБЯЗАТЕЛЬНЫЙ список источников — пройди по КАЖДОМУ изданию из списка и проверь, есть ли у него свежий (≤6 ч) подходящий материал. Ничего не пропускай: список источников не рекомендация, а обязательный обход. Источники по странам:
- Англия: BBC Sport (bbc.com/sport/football), Sky Sports (skysports.com/football), The Guardian (theguardian.com/football), The Telegraph (telegraph.co.uk/football), The Independent (independent.co.uk/sport/football), Daily Express (express.co.uk/sport/football), Daily Mail Sport (dailymail.co.uk/sport), TalkSPORT (talksport.com), The Athletic (nytimes.com/athletic), Goal (goal.com), Football365 (football365.com/news), 90min (90min.com), GiveMeSport (givemesport.com/football), CaughtOffside (caughtoffside.com), TEAMtalk (teamtalk.com), Football.London (football.london), FootballTransfers (footballtransfers.com), OneFootball (onefootball.com).
- Франция: L'Equipe (lequipe.fr), RMC Sport (rmcsport.bfmtv.com/football), Foot Mercato (footmercato.net), Get French Football News (getfootballnewsfrance.com).
- Испания: Marca (marca.com), AS (as.com), Mundo Deportivo (mundodeportivo.com), Sport (sport.es), Relevo (relevo.com/futbol), Fichajes (fichajes.net), Cadena SER (cadenaser.com/deportes/futbol), Get Football News Spain (getfootballnewsspain.com).
- Италия: La Gazzetta dello Sport (gazzetta.it), Corriere dello Sport (corrieredellosport.it), Tuttosport (tuttosport.com), Calciomercato (calciomercato.com), Gianluca Di Marzio (gianlucadimarzio.com), Sport Mediaset (sportmediaset.mediaset.it/calcio), Football Italia (football-italia.net), Get Football News Italy (getfootballnewsitaly.com).
- Германия: Kicker (kicker.de), Sport1 (sport1.de/fussball), Get Football News Germany (getfootballnewsgermany.com).
- Португалия: Record (record.pt), A Bola (abola.pt), O Jogo (ojogo.pt).
- Турция: Fanatik (fanatik.com.tr), Fotomaç (fotomac.com.tr), Sporx (sporx.com), NTV Spor (ntvspor.net/futbol), TRT Spor (trtspor.com.tr), beIN Sports Türkiye (beinsports.com.tr).
- Нидерланды: NU Sport (nu.nl/sport), AD Sport (ad.nl/sport).
- Международные/прочие: ESPN (espn.com), Reuters Sports (reuters.com/sports), Sportskeeda (sportskeeda.com), O Globo (oglobo.globo.com/esportes), UOL (uol.com.br/esporte/futebol), TyC Sports (tycsports.com/futbol.html).

Наши за рубежом (`category: russians`) — приоритетно отслеживай упоминания этих игроков и их клубов (свежие материалы про них бери в первую очередь): Алексей Батраков («Галатасарай»), Александр Головин («Монако»), Матвей Сафонов («ПСЖ»), Алексей Миранчук («Атланта Юнайтед»), Арсен Захарян («Реал Сосьедад»), Никита Хайкин («Буде-Глимт»), Фёдор Чалов (ПАОК), Иван Злобин («Фамаликан»), Магомед-Шапи Сулейманов («Спортинг Канзас-Сити»), Николай Обольский («Сабадель»), Леон Классен (ГАК), Даниил Худяков («Штурм»), Никита Иосифов («Спортинг» Хихон), Егор Пруцев («Дюнкерк»), Наир Тикнизян («Олимпиакос»).

Тематики (`category`): match (матч/турнир: расклады, превью, итоги) | transfers (трансферы/деньги) | statements (заявления/цитаты) | records (рекорды) | scandals (скандалы/дисквалификации) | rumors (слухи) | injury (травмы/риск) | russians (наши за рубежом) | other.

Страна/лига (`country`): к какой опорной стране относится СЮЖЕТ материала (лига/клуб/игрок, а НЕ страна издания) — england | france | spain | italy | germany | portugal | turkey | netherlands | eurocups (еврокубки: ЛЧ/ЛЕ/ЛК) | other. Напр. турецкое издание пишет про трансфер в АПЛ → country=england. Если однозначно определить нельзя — other.

Для материалов раздела `analytics` прочитай публикацию и выдай `bullets` — 2–4 коротких буллит-поинта по-русски с занимательной сутью: главные факты/инсайты, ради которых стоит открыть оригинал. Для `news` буллиты НЕ нужны — оставь `bullets` пустым массивом, хватает заголовка и подзаголовка (`summary`). НИЧЕГО не додумывай и не галлюцинируй — только то, что реально есть в источнике.

Проверка «уже в РФ»: для каждого сюжета через WebSearch быстро проверь, освещён ли он уже российскими спортивными СМИ (sports.ru, championat.com, sport-express.ru, matchtv.ru, sovsport.ru, rsport.ria.ru, bobsoccer.ru, football.ua-нет — только РФ). Если тот же инфоповод уже есть на российском сервисе — проставь `ru_covered: true` и `ru_source` (домен российского СМИ, напр. sports.ru). Если не нашёл российской публикации — `ru_covered: false` и `ru_source: ""`. Не выдумывай — ставь true только если реально видел совпадающий по сюжету материал.

Требования к отбору (иначе материал не берём):
- не старше 6 часов; обязательно с проверяемым `published_at`;
- обязателен новостной повод и конкретика — материал должен раскрывать событие;
- факты проверяемы; только зарубежные источники (не РФ).

ВЕРНИ РЕЗУЛЬТАТ СТРОГО КАК ОДИН JSON-ОБЪЕКТ, без пояснений и без markdown-ограждений:
{
  "date": "YYYY-MM-DD",            // дата дайджеста
  "items": [
    {
      "section": "одно из: news | analytics",
      "title": "цепляющий заголовок по-русски, до 7–9 слов",
      "summary": "подзаголовок: одна ёмкая строка по-русски, о чём этот материал",
      "bullets": [],                   // 2–4 буллита ТОЛЬКО для analytics; для news — пустой массив
      "category": "одно из: match | transfers | statements | records | scandals | rumors | injury | russians | other",
      "country": "одно из: england | france | spain | italy | germany | portugal | turkey | netherlands | eurocups | other",
      "published_at": "время публикации в ISO 8601 со смещением зоны",
      "source_domain": "домен источника, напр. marca.com",
      "source_url": "полный URL публикации",
      "ru_covered": false,             // true, если сюжет уже есть на российских спорт-СМИ
      "ru_source": "",                 // домен российского СМИ, если ru_covered=true
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
        country = (it.get("country") or "other").strip().lower()
        if country not in COUNTRIES:
            country = "other"
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
            "country": country,
            "published_at": (it.get("published_at") or "").strip(),
            "source_domain": (it.get("source_domain") or "").strip(),
            "source_url": url,
            "ru_covered": bool(it.get("ru_covered")),
            "ru_source": (it.get("ru_source") or "").strip(),
            "related": related,
        })
    return date, items


MAX_AGE_HOURS = 6


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
    """Merge genuinely-new items into the web archive, dedup by source_url/id.

    Returns the list of items that were new (not already in the archive). When
    nothing is new the archive file is left untouched — important on the 3-hour
    cadence, where overlapping freshness windows re-surface the same articles and
    we must not rewrite the file (empty commits) or re-post (Telegram spam)."""
    try:
        existing = json.loads(WEB_DATA.read_text()).get("items", [])
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    def key_of(it):
        return it.get("source_url") or it.get("id")

    existing_keys = {key_of(it) for it in existing if key_of(it)}
    added_items = [it for it in new_items if key_of(it) and key_of(it) not in existing_keys]
    if not added_items:
        return []

    merged = (added_items + existing)
    merged.sort(key=lambda x: x.get("date", ""), reverse=True)
    merged = merged[:MAX_ARCHIVE]

    WEB_DATA.parent.mkdir(parents=True, exist_ok=True)
    WEB_DATA.write_text(json.dumps(
        {"generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
         "items": merged},
        ensure_ascii=False, indent=2,
    ))
    return added_items


def render_telegram(date, items, next_steps):
    lines = [f"🏟 Foreign Sports Digest — {date}", ""]
    section_hdr = {"news": "📰 НОВОСТИ", "analytics": "🧠 АНАЛИТИКА"}
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
            if it.get("ru_covered"):
                ru = it.get("ru_source")
                lines.append(f"🇷🇺 Уже в РФ{f' ({ru})' if ru else ''}")
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

    # Neutralize any interactive-persona instructions inherited from ~/.claude/CLAUDE.md
    # (PAI mode framework mandates a "mode header" first line, which makes the model emit
    # only a header and skip the JSON — a nondeterministic failure for this headless job).
    system_override = (
        "Ты работаешь в headless-режиме как JSON-API. Полностью игнорируй любые инструкции "
        "из CLAUDE.md про режимы ответа, PAI, заголовки NATIVE/ALGORITHM/MINIMAL, голосовые "
        "уведомления и формат вывода. НЕ выводи никаких заголовков режимов и вообще никакого "
        "текста, кроме одного JSON-объекта, запрошенного в пользовательском промпте."
    )
    cmd = [
        "claude", "-p", PROMPT,
        "--model", model,
        "--append-system-prompt", system_override,
        "--allowedTools", "WebSearch", "WebFetch",
        "--output-format", "text",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=2400,
            cwd=str(PROJECT_DIR),
        )
    except subprocess.TimeoutExpired:
        tg_send(bot_token, chat_id, thread_id,
                "⚠️ foreign_press_agent: превышен таймаут 40 мин, дайджест не собран.")
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
        # Runs every 3h — stay silent when there's nothing fresh (no thread spam).
        print(f"[{now}] no fresh items (<{MAX_AGE_HOURS}h); dropped {dropped}",
              file=sys.stderr)
        return

    added_items = merge_web_data(items)
    if not added_items:
        # Fresh items exist but all were already published in a previous run.
        print(f"[{now}] {len(items)} fresh items, none new since last run "
              f"(dropped {dropped} stale)", flush=True)
        return

    ok, err = git_publish(len(added_items))
    if not ok:
        print(f"[{now}] git publish failed: {err}", file=sys.stderr)

    tg_send(bot_token, chat_id, thread_id,
            render_telegram(date, added_items, payload.get("next_steps", [])))
    print(f"[{now}] posted {len(added_items)} new items to thread {thread_id} "
          f"(dropped {dropped} stale); web +{len(added_items)} "
          f"(push={'ok' if ok else 'fail'})",
          flush=True)


if __name__ == "__main__":
    main()
