#!/bin/bash
# Скрипт для обновления зависимостей и рестарта сервисов через systemd

cd /home/ubuntu/apps/whatsupp || { echo "Failed to cd"; exit 1; }

echo "==> Installing dependencies..."
if [ -f venv/bin/activate ]; then
    source venv/bin/activate
    pip install --upgrade pip -q
    pip install -r requirements.txt -q
    echo "Dependencies installed"
else
    echo "ERROR: venv not found!"
    exit 1
fi

echo "==> Restarting services via systemd..."
# Убиваем процессы - systemd автоматически перезапустит их (Restart=on-failure)
# Используем pkill с опцией -TERM для graceful shutdown
pkill -TERM -f "gunicorn.*app:app" && echo "Sent TERM to gunicorn" || echo "No gunicorn found"
pkill -TERM -f "python.*telegram_bot.py" && echo "Sent TERM to telegram bot" || echo "No telegram bot found"

echo "==> Waiting for systemd to restart services..."
sleep 5

echo "==> Checking service status..."
if pgrep -f "gunicorn.*app:app" > /dev/null; then
    echo "✓ WhatsApp webhook is running"
else
    echo "⚠ WhatsApp webhook not detected (may still be starting)"
fi

if pgrep -f "python.*telegram_bot.py" > /dev/null; then
    echo "✓ Telegram bot is running"
else
    echo "⚠ Telegram bot not detected (may still be starting)"
fi

echo "==> Deploy completed!"
echo "Note: If systemd services are configured, they will auto-restart"
exit 0
