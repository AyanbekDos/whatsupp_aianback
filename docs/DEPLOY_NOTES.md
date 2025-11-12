# Руководство: репозиторий `whatsupp_aianback`, деплой и автодоставка

  ## 1. Локальный репозиторий

  ```bash
  cd /home/07112025/whatsupp_aianback
  rm -rf .git                    # если вдруг есть старый origin
  git init
  git add .
  git commit -m "Initial import"

  ### Подключение GitHub

  1. Создай пустой репозиторий whatsupp_aianback в своём GitHub-аккаунте.
  2. Добавь удалённый origin и пушни main:

     git remote add origin git@github.com:<username>/whatsupp_aianback.git
     git push -u origin main

  ## 2. Сервер bot.smetai.online (DigitalOcean FRA1)

  ### 2.1. DNS (Cloudflare)

  - A‑запись: bot.smetai.online → 167.172.188.168, Proxy Status = DNS only.

  ### 2.2. Подготовка Droplet

  ssh ubuntu@167.172.188.168
  sudo apt update && sudo apt upgrade -y
  sudo apt install -y python3-venv python3-pip git nginx snapd
  sudo snap install --classic certbot
  sudo ufw allow OpenSSH
  sudo ufw allow 'Nginx Full'
  sudo ufw enable

  ### 2.3. Код и виртуальное окружение

  mkdir -p ~/apps/whatsupp && cd ~/apps/whatsupp
  git clone git@github.com:<username>/whatsupp_aianback.git .
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt gunicorn
  cp .env.example .env             # заполнить реальными токенами / chat_id

  ### 2.4. systemd-сервисы

  /etc/systemd/system/whatsapp-webhook.service

  [Unit]
  Description=WhatsApp webhook (gunicorn)
  After=network.target

  [Service]
  User=ubuntu
  WorkingDirectory=/home/ubuntu/apps/whatsupp
  Environment="PYTHONUNBUFFERED=1"
  ExecStart=/home/ubuntu/apps/whatsupp/venv/bin/gunicorn -b 127.0.0.1:8000 app:app
  Restart=on-failure

  [Install]
  WantedBy=multi-user.target

  /etc/systemd/system/telegram-leadbot.service

  [Unit]
  Description=Telegram lead bot
  After=network.target

  [Service]
  User=ubuntu
  WorkingDirectory=/home/ubuntu/apps/whatsupp
  Environment="PYTHONUNBUFFERED=1"
  ExecStart=/home/ubuntu/apps/whatsupp/venv/bin/python telegram_bot.py
  Restart=on-failure

  [Install]
  WantedBy=multi-user.target

  Активировать:

  sudo systemctl daemon-reload
  sudo systemctl enable --now whatsapp-webhook telegram-leadbot
  sudo systemctl status whatsapp-webhook telegram-leadbot

  ### 2.5. Nginx + HTTPS

  /etc/nginx/sites-available/whatsapp

  server {
      server_name bot.smetai.online;

      location / {
          proxy_pass http://127.0.0.1:8000;
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          proxy_set_header X-Forwarded-Proto $scheme;
      }
  }

  sudo ln -s /etc/nginx/sites-available/whatsapp /etc/nginx/sites-enabled/
  sudo nginx -t && sudo systemctl reload nginx
  sudo certbot --nginx -d bot.smetai.online

  Проверка: curl https://bot.smetai.online/healthz.

  ### 2.6. Настройка Meta

  - WhatsApp → API Setup → Webhook → URL https://bot.smetai.online/webhook.
  - Токен проверки = WA_VERIFY_TOKEN из .env.
  - Включить поле messages.

  ## 3. CI/CD через GitHub Actions

  ### 3.1. Доступ по SSH из GitHub

  1. Сгенерируй deploy key (на своей машине):

     ssh-keygen -t ed25519 -f ~/.ssh/whatsupp_do -C "whatsupp deploy"
  2. ~/.ssh/whatsupp_do.pub добавь в /home/ubuntu/.ssh/authorized_keys на сервере.
  3. Закрой парольный вход (если нужно) и проверь: ssh -i ~/.ssh/whatsupp_do ubuntu@167.172.188.168.

  ### 3.2. Secrets в GitHub

  В Settings → Secrets → Actions добавь:

  - DO_SSH_HOST = 167.172.188.168
  - DO_SSH_USER = ubuntu
  - DO_SSH_KEY = содержимое ~/.ssh/whatsupp_do (приватный ключ)

  ### 3.3. Workflow .github/workflows/deploy.yml

  name: Deploy to bot.smetai.online

  on:
    push:
      branches: [main]

  jobs:
    deploy:
      runs-on: ubuntu-latest
      steps:
        - name: Checkout
          uses: actions/checkout@v4

        - name: Copy files via rsync
          uses: burnett01/rsync-deployments@v6.0
          with:
            switches: -avz --delete
            path: .
            remote_path: /home/ubuntu/apps/whatsupp
            remote_host: ${{ secrets.DO_SSH_HOST }}
            remote_user: ${{ secrets.DO_SSH_USER }}
            remote_key: ${{ secrets.DO_SSH_KEY }}

        - name: Install deps & restart services
          uses: appleboy/ssh-action@v1.0.0
          with:
            host: ${{ secrets.DO_SSH_HOST }}
            username: ${{ secrets.DO_SSH_USER }}
            key: ${{ secrets.DO_SSH_KEY }}
            script: |
              cd /home/ubuntu/apps/whatsupp
              /home/ubuntu/apps/whatsupp/venv/bin/pip install -r requirements.txt
              sudo systemctl restart whatsapp-webhook telegram-leadbot

  > .env на сервере не коммить — хранится вручную. В workflow можно добавить шаг cp /home/ubuntu/.env.whatsupp .env если нужно.

  После merge в main Actions автоматически выгрузит код на Droplet, обновит зависимости и перезапустит сервисы.

  ## 4. Мониторинг

  - Логи вебхука: sudo journalctl -fu whatsapp-webhook.
  - Логи Telegram‑бота: sudo journalctl -fu telegram-leadbot.
  - Сертификат: sudo certbot renew --dry-run.
  - Бэкапы .env и conversation_logs/ — через cron/rsync/S3, если требуется.

  ## 5. Локальная разработка

  - Работай в ветке, меняй промпты/логику.
  - git commit → git push origin main.
  - CI/CD сам доставит на bot.smetai.online.
  - Meta webhook остаётся неизменным, локальный Cloudflare tunnel больше не нужен.