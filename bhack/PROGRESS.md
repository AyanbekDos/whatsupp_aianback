# Текущее состояние проекта (12 Nov 2025)

## Репозиторий
- `app.py` — Flask-сервис: принимает вебхуки WhatsApp Cloud API (`/webhook`), пересылает их в Telegram (`TELEGRAM_CHAT_ID`) и при `ENABLE_AI_AUTOREPLY=true` запрашивает ответ в OpenRouter (`minimax/minimax-m2:free`), затем шлёт его обратно клиенту через `WA_TOKEN` / `WA_PHONE_NUMBER_ID`.
- `telegram_bot.py` — отдельный Telegram-лид-бот (python-telegram-bot). Сценарий `/start`: спрашивает имя → телефон → запрос, уведомляет группу (`TELEGRAM_NOTIFY_CHAT_ID`) и даёт AI-ответ (тот же OpenRouter).
- `requirements.txt` включает Flask, requests, python-dotenv, python-telegram-bot.
- `README.md` содержит пошаговые инструкции (WhatsApp webhook, OpenRouter, Telegram chat id, запуск обоих сервисов).

## Настройки .env (текущее содержимое)
```
WA_TOKEN=EAA7PMyUaZCCgBP1aNpArmy4YZCZBqM2WGdYwpD4Ksmt4QFlmqEltyIoMZAZAkcgqiYfMswYjLLWhfuEW5UoOTZBGWbQpZCZBWZCKlE3ie3E73oS574n1q2hy03xLACtsHHAFLnE5ZBZBphptEeNIFA1uWdV7N7YFR7pbJvTsAUfJkIy4MZBtuGeazAGZAqZAWH0ZAKs0OFA7QZDZD
TELEGRAM_BOT_TOKEN=8554486691:AAGFGre-hibgD4m40P_FOmPiPUwKyK9c_eA
WA_PHONE_NUMBER_ID=893336607192003
OPENROUTER_API_KEY=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
WA_VERIFY_TOKEN=1235
TELEGRAM_CHAT_ID=-4882226343
```
(Добавь `TELEGRAM_NOTIFY_CHAT_ID`, если планируешь слать заявки в группу, и любые другие переменные из README.)

## Что уже работает
1. **Локальный сервер:** `python app.py` — слушает порт 8000.
2. **Туннель:** `cloudflared tunnel --url http://localhost:8000` выдаёт URL вида `https://simpsons-copyrighted-philips-evident.trycloudflare.com`.
3. **Проверка webhook:** ручной `curl` на `https://…/webhook?hub.mode=subscribe&hub.verify_token=1235&hub.challenge=123` возвращает `123`, т.е. код корректно отвечает.
4. **Telegram бот лидов:** `python telegram_bot.py` — опрашивает пользователя и отсылает карточку (при наличии `TELEGRAM_NOTIFY_CHAT_ID`).

## Что осталось доделать после перезагрузки
1. Включить виртуальное окружение: `source venv/bin/activate`.
2. Запустить `python app.py`.
3. Поднять туннель: `cloudflared tunnel --url http://localhost:8000` (получить новый URL).
4. В Meta → WhatsApp → API Setup → Webhook:
   - Вставить свежий URL (`https://<новый>.trycloudflare.com/webhook`).
   - Ввести тот же `WA_VERIFY_TOKEN=1235`.
   - Нажать `Verify and Save`, включить поле **messages**.
5. Отправить тестовое сообщение на номер WhatsApp, проверить, что оно появляется в Telegram и, при включённом AI, клиент получает ответ.
6. По желанию — запустить `python telegram_bot.py` для Telegram лидов и записать `TELEGRAM_NOTIFY_CHAT_ID` в `.env`.

## Примечания
- Quick Tunnel Cloudflare живёт до перезапуска — после ребута потребуется новый URL.
- Если Meta снова пишет «Проверка не пройдена», проверь, совпадают ли токен и URL. При необходимости можно сменить `WA_VERIFY_TOKEN` в `.env` и сразу же в панели.
