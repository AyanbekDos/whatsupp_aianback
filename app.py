import logging
import os
from typing import Dict, Iterable, Optional, Tuple

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

WA_TOKEN = os.getenv("WA_TOKEN")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WA_VERIFY_TOKEN = os.getenv("WA_VERIFY_TOKEN", "change_me")
WA_PHONE_NUMBER_ID = os.getenv("WA_PHONE_NUMBER_ID")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "z-ai/glm-4.5-air:free")
OPENROUTER_URL = os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")
OPENROUTER_SYSTEM_PROMPT = os.getenv(
    "OPENROUTER_SYSTEM_PROMPT",
    "Ты виртуальный ассистент компании, отвечаешь уважительно, кратко и по делу. "
    "Если не знаешь ответа — уточни детали.",
)
OPENROUTER_REFERRER = os.getenv("OPENROUTER_REFERRER", "https://example.com")
OPENROUTER_TITLE = os.getenv("OPENROUTER_TITLE", "WhatsAppTelegramBridge")
ENABLE_AI_AUTOREPLY = os.getenv("ENABLE_AI_AUTOREPLY", "true").lower() not in {"0", "false", "no"}

required_env = {
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
}

if ENABLE_AI_AUTOREPLY:
    required_env.update({
        "WA_TOKEN": WA_TOKEN,
        "WA_PHONE_NUMBER_ID": WA_PHONE_NUMBER_ID,
        "OPENROUTER_API_KEY": OPENROUTER_API_KEY,
    })

missing_env = [name for name, value in required_env.items() if not value]

if missing_env:
    raise RuntimeError(f"Missing required environment variables: {', '.join(missing_env)}")

TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
WHATSAPP_API_BASE = f"https://graph.facebook.com/v19.0/{WA_PHONE_NUMBER_ID}" if WA_PHONE_NUMBER_ID else None


def build_contact_index(contacts: Iterable[Dict]) -> Dict[str, str]:
    index: Dict[str, str] = {}
    for contact in contacts or []:
        wa_id = contact.get("wa_id")
        if not wa_id:
            continue
        index[wa_id] = contact.get("profile", {}).get("name", "")
    return index


def iter_whatsapp_messages(payload: Dict) -> Iterable[Tuple[str, Dict]]:
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contact_index = build_contact_index(value.get("contacts", []))
            for message in value.get("messages", []):
                sender = message.get("from", "unknown")
                sender_name = contact_index.get(sender, "")
                yield sender_name, message


def format_message(sender_name: str, message: Dict) -> str:
    sender_id = message.get("from", "unknown")
    msg_type = message.get("type", "text")
    body = ""

    if msg_type == "text":
        body = message.get("text", {}).get("body", "")
    elif msg_type == "interactive":
        interactive = message.get("interactive", {})
        interactive_type = interactive.get("type")
        if interactive_type == "button_reply":
            reply = interactive.get("button_reply", {})
            body = f"Button reply: {reply.get('title')} (id: {reply.get('id')})"
        elif interactive_type == "list_reply":
            reply = interactive.get("list_reply", {})
            body = f"List reply: {reply.get('title')} (id: {reply.get('id')})"
    else:
        body = f"{msg_type} message received (not forwarded in detail)."

    header = sender_name or "Unknown contact"
    return f"WhatsApp message from {header} ({sender_id}):\n{body}"


def extract_plain_text(message: Dict) -> Optional[str]:
    msg_type = message.get("type")
    if msg_type == "text":
        return message.get("text", {}).get("body")
    if msg_type == "interactive":
        interactive = message.get("interactive", {})
        interactive_type = interactive.get("type")
        if interactive_type == "button_reply":
            return interactive.get("button_reply", {}).get("title")
        if interactive_type == "list_reply":
            return interactive.get("list_reply", {}).get("title")
    return None


def send_to_telegram(text: str) -> bool:
    if not TELEGRAM_CHAT_ID:
        logger.warning("TELEGRAM_CHAT_ID is not set; message skipped.")
        return False

    response = requests.post(
        f"{TELEGRAM_API_BASE}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "disable_web_page_preview": True
        },
        timeout=10,
    )

    if not response.ok:
        logger.error("Failed to send message to Telegram: %s", response.text)
        return False

    return True


def generate_ai_reply(sender_name: str, user_message: str) -> Optional[str]:
    if not ENABLE_AI_AUTOREPLY or not user_message:
        return None

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": OPENROUTER_REFERRER,
        "X-Title": OPENROUTER_TITLE,
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": OPENROUTER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Клиент ({sender_name or 'неизвестно'}): {user_message}",
            },
        ],
    }

    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        logger.error("OpenRouter request failed: %s", exc)
        return None

    choices = data.get("choices") or []
    if not choices:
        logger.error("OpenRouter returned no choices: %s", data)
        return None

    message = choices[0].get("message", {})
    content = message.get("content")

    if isinstance(content, list):
        # Some models may return a list of parts; concatenate if so.
        content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)

    if not isinstance(content, str):
        logger.error("Unexpected OpenRouter content format: %s", content)
        return None

    return content.strip()


def send_whatsapp_reply(recipient_id: str, text: str) -> bool:
    if not (ENABLE_AI_AUTOREPLY and WHATSAPP_API_BASE and text and recipient_id):
        return False

    try:
        response = requests.post(
            f"{WHATSAPP_API_BASE}/messages",
            headers={
                "Authorization": f"Bearer {WA_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "to": recipient_id,
                "type": "text",
                "text": {
                    "preview_url": False,
                    "body": text.strip(),
                },
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        logger.error("Failed to send reply to WhatsApp: %s", exc)
        return False

    if not response.ok:
        logger.error("WhatsApp API error: %s", response.text)
        return False

    return True


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == WA_VERIFY_TOKEN:
        return challenge, 200

    logger.warning("Webhook verification failed: mode=%s token=%s", mode, token)
    return "Verification failed", 403


@app.route("/webhook", methods=["POST"])
def handle_whatsapp_webhook():
    payload = request.get_json()
    if not payload:
        logger.info("Received empty payload.")
        return jsonify({"status": "ignored"}), 200

    forwarded = 0
    for sender_name, message in iter_whatsapp_messages(payload):
        text = format_message(sender_name, message)
        if send_to_telegram(text):
            forwarded += 1

        customer_text = extract_plain_text(message)
        ai_reply = generate_ai_reply(sender_name, customer_text or "")
        if ai_reply and send_whatsapp_reply(message.get("from", ""), ai_reply):
            send_to_telegram(f"🤖 Ответ, отправленный клиенту:\n{ai_reply}")

    return jsonify({"forwarded": forwarded}), 200


@app.get("/healthz")
def healthcheck():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
