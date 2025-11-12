#!/bin/bash
# Скрипт для перезапуска сервисов без sudo

set -e
cd /home/ubuntu/apps/whatsupp

echo "==> Installing dependencies..."
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "==> Stopping services..."
# Останавливаем процессы через systemctl (если запущены как сервисы)
systemctl --user stop whatsapp-webhook.service 2>/dev/null || true
systemctl --user stop telegram-leadbot.service 2>/dev/null || true

# Альтернативно - убиваем через pkill
pkill -f "gunicorn.*app:app" || true
pkill -f "python.*telegram_bot.py" || true

sleep 2

echo "==> Starting services..."
# Запускаем через systemd user services
systemctl --user start whatsapp-webhook.service || {
    # Если systemd user services не настроены, запускаем напрямую
    nohup venv/bin/gunicorn -b 127.0.0.1:8000 app:app > logs/webhook.log 2>&1 &
}

systemctl --user start telegram-leadbot.service || {
    nohup venv/bin/python telegram_bot.py > logs/telegram.log 2>&1 &
}

sleep 2

echo "==> Checking services..."
pgrep -f "gunicorn.*app:app" && echo "✓ WhatsApp webhook is running" || echo "✗ WhatsApp webhook failed"
pgrep -f "python.*telegram_bot.py" && echo "✓ Telegram bot is running" || echo "✗ Telegram bot failed"

echo "==> Deploy completed!"
