#!/bin/bash
# Скрипт для перезапуска сервисов без sudo и systemctl

set -e
cd /home/ubuntu/apps/whatsupp

echo "==> Installing dependencies..."
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "==> Stopping old processes..."
# Останавливаем процессы напрямую через pkill
pkill -f "gunicorn.*app:app" || echo "No gunicorn process found"
pkill -f "python.*telegram_bot.py" || echo "No telegram bot process found"

sleep 2

echo "==> Starting services..."
# Создаем директорию для логов если нет
mkdir -p logs

# Запускаем gunicorn для WhatsApp webhook
nohup venv/bin/gunicorn -b 127.0.0.1:8000 app:app > logs/webhook.log 2>&1 &
WEBHOOK_PID=$!
echo "Started webhook with PID: $WEBHOOK_PID"

# Запускаем Telegram бота
nohup venv/bin/python telegram_bot.py > logs/telegram.log 2>&1 &
TELEGRAM_PID=$!
echo "Started telegram bot with PID: $TELEGRAM_PID"

sleep 2

echo "==> Checking services..."
if pgrep -f "gunicorn.*app:app" > /dev/null; then
    echo "✓ WhatsApp webhook is running"
else
    echo "✗ WhatsApp webhook failed to start"
    tail -20 logs/webhook.log
    exit 1
fi

if pgrep -f "python.*telegram_bot.py" > /dev/null; then
    echo "✓ Telegram bot is running"
else
    echo "✗ Telegram bot failed to start"
    tail -20 logs/telegram.log
    exit 1
fi

echo "==> Deploy completed successfully!"
