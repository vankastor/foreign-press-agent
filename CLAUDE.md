# foreign_press_agent

Периодический сервис-мониторинг зарубежной (не РФ) прессы для Head of Product Analytics «Лиги Ставок». Раз в сутки собирает дайджест международных новостей по iGaming / sports betting и смежным темам и постит его в takopi-тред «Foreign Press Agent» (thread_id=4179). Язык — русский.

⚠️ **Лига Ставок ≠ Blocklabs.** Мониторинг — только про беттинг/iGaming в контексте ЛС.

## Как работает
- `scripts/run.py` запускается launchd-агентом `com.foreign-press-agent` (ежедневно 08:00 local, `StartCalendarInterval`).
- Внутри вызывает headless Claude (`claude -p`, модель из `FPA_MODEL`, инструменты только `WebSearch`/`WebFetch`) — использует подписку Claude Code, **без сторонних API-ключей**.
- Результат постит в Telegram-тред через Bot API. Логи — `logs/out.log`, `logs/err.log`.

## Секреты
- Своих секретов у проекта нет. Telegram `bot_token` + `chat_id` читаются в рантайме из `~/.takopi/takopi.toml`.
- `.env` (chmod 600, gitignored) — только несекретный конфиг: `FPA_THREAD_ID`, `FPA_MODEL`.

## Наружу не экспонируется
Это periodic job, не сервер: порт не занимает, ingress/туннели не трогает.

## Допущения (можно менять одним сообщением)
Функциональный спек не был задан явно — восстановлен по названию агента. Текущие дефолты:
- **Что мониторим:** iGaming / sports-betting индустрия (регуляции, M&A, операторы, продукт/аналитика), значимые спортивные события. Промпт — в `scripts/run.py` (`PROMPT`).
- **Куда:** takopi-тред «Foreign Press Agent» (4179). Внутренний канал, не публикация наружу.
- **Как часто:** раз в сутки, 08:00. Меняется в plist (`StartCalendarInterval`/`StartInterval`).
- **Движок:** headless Claude Code (подписка), без доп. затрат на API.

Чтобы скорректировать тему/частоту/адресата — скажи, поправлю `PROMPT`, `.env`, plist.

## Управление
```
launchctl list | grep foreign-press-agent          # PID/exit
tail -20 ~/foreign_press_agent/logs/err.log
python3 ~/foreign_press_agent/scripts/run.py        # ручной прогон
launchctl kickstart -k gui/501/com.foreign-press-agent   # форс-запуск
```
