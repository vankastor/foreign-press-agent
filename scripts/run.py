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
from datetime import datetime, timezone
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


CATEGORIES = ["regulation", "ma", "operators", "product", "analytics", "sports", "other"]

PROMPT = """Ты — аналитик, ведущий мониторинг зарубежной (не русскоязычной) прессы для Head of Product Analytics беттинг-компании «Лига Ставок».

Задача: с помощью WebSearch найди 5–8 самых значимых новостей за последние ~24–48 часов из международной прессы по темам:
- iGaming / sports betting индустрия (регуляции, M&A, крупные операторы, технологии, продукты);
- значимые спортивные события, влияющие на беттинг;
- продуктовая аналитика, growth, retention практики в gambling/betting;
- всё, что может быть полезно для стратегии продукта беттинг-компании.

Только зарубежные источники (EN и др.), не РФ.

ВЕРНИ РЕЗУЛЬТАТ СТРОГО КАК ОДИН JSON-ОБЪЕКТ, без пояснений и без markdown-ограждений:
{
  "date": "YYYY-MM-DD",            // дата дайджеста
  "items": [
    {
      "title": "краткий заголовок по-русски",
      "summary": "1–2 предложения сути по-русски",
      "why": "почему это важно для продуктовой аналитики ЛС, 1 строка по-русски",
      "category": "одно из: regulation | ma | operators | product | analytics | sports | other",
      "source_domain": "домен источника, напр. igamingbusiness.com",
      "source_url": "полный URL публикации"
    }
  ],
  "next_steps": ["1–2 коротких next steps для продуктовой команды, по-русски"]
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
        items.append({
            "id": f"{date}-{slugify(title)}",
            "date": it.get("date", date),
            "title": title,
            "summary": (it.get("summary") or "").strip(),
            "why": (it.get("why") or "").strip(),
            "category": cat,
            "source_domain": (it.get("source_domain") or "").strip(),
            "source_url": url,
        })
    return date, items


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
    lines = [f"🗞 Foreign Press Digest — {date}", ""]
    icon = {
        "regulation": "⚖️", "ma": "🤝", "operators": "🏢",
        "product": "🧩", "analytics": "📊", "sports": "🏆", "other": "•",
    }
    for it in items:
        lines.append(f"{icon.get(it['category'], '•')} {it['title']}")
        if it["summary"]:
            lines.append(it["summary"])
        if it["why"]:
            lines.append(f"→ Почему важно: {it['why']}")
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
        header = f"🗞 Foreign Press Digest — {now}\n\n"
        tg_send(bot_token, chat_id, thread_id, header + out)
        print(f"[{now}] posted raw digest ({len(out)} chars); JSON parse failed",
              file=sys.stderr)
        return

    date, items = normalize_items(payload)
    added = merge_web_data(items)
    ok, err = git_publish(added)
    if not ok:
        print(f"[{now}] git publish failed: {err}", file=sys.stderr)

    tg_send(bot_token, chat_id, thread_id,
            render_telegram(date, items, payload.get("next_steps", [])))
    print(f"[{now}] posted {len(items)} items to thread {thread_id}; "
          f"web +{added} (push={'ok' if ok else 'fail'})", flush=True)


if __name__ == "__main__":
    main()
