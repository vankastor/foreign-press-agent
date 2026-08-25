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


PROMPT = """Ты — аналитик, ведущий мониторинг зарубежной (не русскоязычной) прессы для Head of Product Analytics беттинг-компании «Лига Ставок».

Задача: с помощью WebSearch найди 5–8 самых значимых новостей за последние ~24–48 часов из международной прессы по темам:
- iGaming / sports betting индустрия (регуляции, M&A, крупные операторы, технологии, продукты);
- значимые спортивные события, влияющие на беттинг;
- продуктовая аналитика, growth, retention практики в gambling/betting;
- всё, что может быть полезно для стратегии продукта беттинг-компании.

Только зарубежные источники (EN и др.), не РФ. Для каждой новости:
- заголовок (кратко, по-русски);
- 1–2 предложения сути;
- почему это важно для продуктовой аналитики ЛС (1 строка);
- источник (домен).

Формат — компактный текст для Telegram (без markdown-таблиц). В начале строка с датой. В конце — 1–2 «next steps» для продуктовой команды, если уместно. Пиши по-русски."""


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

    header = f"🗞 Foreign Press Digest — {now}\n\n"
    tg_send(bot_token, chat_id, thread_id, header + out)
    print(f"[{now}] posted digest ({len(out)} chars) to thread {thread_id}", flush=True)


if __name__ == "__main__":
    main()
