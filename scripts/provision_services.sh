#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/ubuntu/apps/whatsupp}"
APP_USER="${APP_USER:-ubuntu}"
SERVER_NAME="${SERVER_NAME:-bot.smetai.online}"
APP_PORT="${APP_PORT:-8080}"
VENV_PATH="${VENV_PATH:-${APP_DIR}/venv}"

UNIT_DIR="/etc/systemd/system"
WEBHOOK_UNIT="${UNIT_DIR}/whatsapp-webhook.service"
LEADBOT_UNIT="${UNIT_DIR}/telegram-leadbot.service"
NGINX_CONF="/etc/nginx/sites-available/whatsapp"
NGINX_LINK="/etc/nginx/sites-enabled/whatsapp"

echo "[provision] configuring systemd units for ${APP_DIR}"
sudo tee "${WEBHOOK_UNIT}" >/dev/null <<EOF
[Unit]
Description=WhatsApp webhook (gunicorn)
After=network.target

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment="PYTHONUNBUFFERED=1"
ExecStart=${VENV_PATH}/bin/gunicorn -b 127.0.0.1:${APP_PORT} app.main:app
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

sudo tee "${LEADBOT_UNIT}" >/dev/null <<EOF
[Unit]
Description=Telegram lead bot
After=network.target

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment="PYTHONUNBUFFERED=1"
ExecStart=${VENV_PATH}/bin/python telegram_bot.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

echo "[provision] reloading systemd daemon"
sudo systemctl daemon-reload
sudo systemctl enable whatsapp-webhook telegram-leadbot >/dev/null 2>&1 || true

echo "[provision] configuring nginx for ${SERVER_NAME}"
sudo tee "${NGINX_CONF}" >/dev/null <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${SERVER_NAME};

    location / {
        proxy_pass http://127.0.0.1:${APP_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

sudo ln -sf "${NGINX_CONF}" "${NGINX_LINK}"
sudo nginx -t
sudo systemctl reload nginx

echo "[provision] restarting application services"
sudo systemctl restart whatsapp-webhook
sudo systemctl restart telegram-leadbot

cat <<MSG
[provision] Done.
If HTTPS is not yet configured, run:
  sudo certbot --nginx -d ${SERVER_NAME}
to obtain a TLS certificate.
MSG
