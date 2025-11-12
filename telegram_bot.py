import asyncio
import json
import logging
import os
from datetime import date, datetime, timedelta, time as dtime, timezone
from functools import partial
from pathlib import Path
from typing import Dict, Optional
from uuid import uuid4

import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATE_NAME, STATE_PHONE, STATE_QUESTION = range(3)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_NOTIFY_CHAT_ID = os.getenv("TELEGRAM_NOTIFY_CHAT_ID")
TELEGRAM_LOG_CHAT_ID = os.getenv("TELEGRAM_LOG_CHAT_ID")
TELEGRAM_APPLICATIONS_CHAT_ID = os.getenv("TELEGRAM_APPLICATIONS_CHAT_ID") or TELEGRAM_NOTIFY_CHAT_ID
TELEGRAM_ANALYTICS_CHAT_ID = os.getenv("TELEGRAM_ANALYTICS_CHAT_ID")
CONVERSATION_LOG_DIR = Path(os.getenv("CONVERSATION_LOG_DIR", "conversation_logs"))
CONVERSATION_LOG_DIR.mkdir(parents=True, exist_ok=True)
DAILY_ANALYTICS_HOUR = int(os.getenv("DAILY_ANALYTICS_HOUR", "23"))
DAILY_ANALYTICS_MINUTE = int(os.getenv("DAILY_ANALYTICS_MINUTE", "30"))
DAILY_ANALYTICS_TZ_NAME = os.getenv("DAILY_ANALYTICS_TZ", "UTC")
ENABLE_DAILY_ANALYTICS = os.getenv("ENABLE_DAILY_ANALYTICS", "true").lower() not in {"0", "false", "no"}

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "z-ai/glm-4.5-air:free")
OPENROUTER_URL = os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")
OPENROUTER_SYSTEM_PROMPT = os.getenv(
    "OPENROUTER_SYSTEM_PROMPT",
    "Ты дружелюбный ассистент отдела продаж. Собираешь контакты, отвечаешь по делу, "
    "если нужно — предлагаешь консультацию менеджера.",
)
OPENROUTER_REFERRER = os.getenv("OPENROUTER_REFERRER", "https://example.com")
OPENROUTER_TITLE = os.getenv("OPENROUTER_TITLE", "TelegramLeadBot")
ENABLE_AI_AUTOREPLY = os.getenv("ENABLE_AI_AUTOREPLY", "true").lower() not in {"0", "false", "no"}

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is required")


def _get_analytics_tz():
    if ZoneInfo:
        try:
            return ZoneInfo(DAILY_ANALYTICS_TZ_NAME)
        except Exception:  # pragma: no cover
            logger.warning("Unknown timezone %s, falling back to UTC", DAILY_ANALYTICS_TZ_NAME)
    return timezone.utc


ANALYTICS_TZ = _get_analytics_tz()


def _log_file_path(target_date: Optional[date] = None) -> Path:
    target_date = target_date or datetime.now(tz=ANALYTICS_TZ).date()
    return CONVERSATION_LOG_DIR / f"{target_date.isoformat()}.jsonl"


def _persist_log_entry(record: Dict) -> None:
    path = _log_file_path()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


async def _log_conversation_message(
    user,
    context: ContextTypes.DEFAULT_TYPE,
    role: str,
    text: str,
    send_to_log_chat: bool = True,
) -> None:
    if not text:
        return

    timestamp = datetime.utcnow().isoformat()
    conversation_id = context.user_data.setdefault(
        "conversation_id",
        f"{user.id}-{uuid4().hex[:8]}",
    )
    entry = {
        "conversation_id": conversation_id,
        "user_id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": role,
        "text": text,
        "timestamp": timestamp,
    }
    transcript = context.user_data.setdefault("transcript", [])
    transcript.append({"role": role, "text": text, "timestamp": timestamp})
    _persist_log_entry(entry)

    if TELEGRAM_LOG_CHAT_ID and send_to_log_chat:
        preview = f"[{timestamp}] {user.full_name} ({user.id})\n{role}: {text}"
        await context.bot.send_message(
            chat_id=TELEGRAM_LOG_CHAT_ID,
            text=preview[:4096],
            disable_notification=True,
        )


def _format_transcript(context: ContextTypes.DEFAULT_TYPE) -> str:
    transcript = context.user_data.get("transcript") or []
    if not transcript:
        return "—"
    lines = [f"{item['role']}: {item['text']}" for item in transcript]
    combined = "\n".join(lines)
    return combined[-4000:] if len(combined) > 4000 else combined


def _call_openrouter(payload: Dict) -> Optional[str]:
    if not (ENABLE_AI_AUTOREPLY and OPENROUTER_API_KEY):
        return None

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": OPENROUTER_REFERRER,
        "X-Title": OPENROUTER_TITLE,
    }

    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        logger.error("OpenRouter API error: %s", exc)
        return None

    choices = data.get("choices") or []
    if not choices:
        logger.error("OpenRouter returned empty choices: %s", data)
        return None

    message = choices[0].get("message", {})
    content = message.get("content")

    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )

    if not isinstance(content, str):
        logger.error("Unexpected OpenRouter response: %s", content)
        return None

    return content.strip()


async def generate_ai_reply(customer_name: str, user_text: str, lead_data: Dict) -> Optional[str]:
    if not user_text:
        return None

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": OPENROUTER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Имя клиента: {customer_name or 'неизвестно'}\n"
                    f"Телефон: {lead_data.get('phone', 'не указан')}\n"
                    f"Первичный запрос: {lead_data.get('question', 'не указан')}\n"
                    f"Сообщение клиента сейчас: {user_text}"
                ),
            },
        ],
    }

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_call_openrouter, payload))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    context.user_data["transcript"] = []
    if update.message:
        await _log_conversation_message(update.effective_user, context, "user", update.message.text)
    greeting = "Привет! Я помогу передать вашу заявку менеджеру.\nКак вас зовут?"
    await update.message.reply_text(greeting)
    await _log_conversation_message(update.effective_user, context, "bot", greeting)
    return STATE_NAME


async def capture_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["name"] = update.message.text.strip()
    await _log_conversation_message(update.effective_user, context, "user", update.message.text)
    prompt = "Отлично. Оставьте, пожалуйста, номер телефона для связи."
    await update.message.reply_text(prompt)
    await _log_conversation_message(update.effective_user, context, "bot", prompt)
    return STATE_PHONE


async def capture_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone = update.message.text.strip()
    await _log_conversation_message(update.effective_user, context, "user", update.message.text)
    if len(phone) < 5:
        await update.message.reply_text("Кажется, номер слишком короткий. Введите номер целиком, пожалуйста.")
        await _log_conversation_message(
            update.effective_user,
            context,
            "bot",
            "Кажется, номер слишком короткий. Введите номер целиком, пожалуйста.",
        )
        return STATE_PHONE

    context.user_data["phone"] = phone
    follow_up = "Расскажите вкратце, какой вопрос или задача у вас?"
    await update.message.reply_text(follow_up)
    await _log_conversation_message(update.effective_user, context, "bot", follow_up)
    return STATE_QUESTION


async def capture_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["question"] = update.message.text.strip()
    await _log_conversation_message(update.effective_user, context, "user", update.message.text)

    awaiting_text = (
        "Спасибо! Вашу заявку передаю менеджеру. Можете задать дополнительные вопросы — я постараюсь помочь."
    )

    await update.message.reply_text(awaiting_text)
    await _log_conversation_message(update.effective_user, context, "bot", awaiting_text)

    await send_application(update, context)
    reply = await generate_ai_reply(
        context.user_data.get("name") or update.effective_user.full_name,
        context.user_data["question"],
        context.user_data,
    )
    if reply:
        await update.message.reply_text(reply)
        await _log_conversation_message(update.effective_user, context, "bot", reply)

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    if update.message:
        await _log_conversation_message(update.effective_user, context, "user", update.message.text)
    cancel_text = "Хорошо, заявку отменяем. Если передумаете — напишите /start."
    await update.message.reply_text(cancel_text)
    await _log_conversation_message(update.effective_user, context, "bot", cancel_text)
    return ConversationHandler.END


async def handle_free_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    await _log_conversation_message(update.effective_user, context, "user", text)
    customer_name = context.user_data.get("name") or update.effective_user.full_name
    reply = await generate_ai_reply(customer_name, text, context.user_data)

    if reply:
        await update.message.reply_text(reply)
        await _log_conversation_message(update.effective_user, context, "bot", reply)
    else:
        fallback = "Спасибо! Передам ваш вопрос менеджеру. Напишите /start, если нужна новая заявка."
        await update.message.reply_text(fallback)
        await _log_conversation_message(update.effective_user, context, "bot", fallback)


async def send_application(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target_chat = TELEGRAM_APPLICATIONS_CHAT_ID or TELEGRAM_NOTIFY_CHAT_ID
    if not target_chat:
        logger.warning("TELEGRAM_APPLICATIONS_CHAT_ID не задан, заявка не отправлена.")
        return

    user = update.effective_user
    data = context.user_data
    transcript_text = _format_transcript(context)

    summary = (
        "Заявка для ИП Aian Back 📋\n"
        f"Имя: {data.get('name', '—')}\n"
        f"Телефон: {data.get('phone', '—')}\n"
        f"Запрос: {data.get('question', '—')}\n"
        f"Telegram: @{user.username or 'нет'} (id {user.id})\n"
        f"Диалог:\n{transcript_text}"
    )

    await context.bot.send_message(chat_id=target_chat, text=summary[:4096])


async def _send_daily_analytics(context: ContextTypes.DEFAULT_TYPE) -> None:
    target_chat = TELEGRAM_ANALYTICS_CHAT_ID or TELEGRAM_LOG_CHAT_ID or TELEGRAM_APPLICATIONS_CHAT_ID
    if not (target_chat and ENABLE_DAILY_ANALYTICS and OPENROUTER_API_KEY):
        return

    report_date = datetime.now(tz=ANALYTICS_TZ).date() - timedelta(days=1)
    log_path = _log_file_path(report_date)
    if not log_path.exists():
        logger.info("Нет логов за %s, отчёт пропущен", report_date)
        return

    log_text = log_path.read_text(encoding="utf-8")
    prompt = (
        f"Ты аналитик ИП Aian Back. Проанализируй диалоги за {report_date}.\n"
        "Отметь: общее количество диалогов, сколько дошло до заявки, повторные обращения, "
        "топ запросов, проблемы и идеи по улучшению. Итог выдай списком.\n\n"
        f"Лог (JSONL):\n{log_text}"
    )

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": "Ты аналитик отдела продаж. Пиши кратко, по пунктам."},
            {"role": "user", "content": prompt},
        ],
    }

    loop = asyncio.get_running_loop()
    summary = await loop.run_in_executor(None, partial(_call_openrouter, payload))
    summary_text = summary or "Не удалось получить ответ от модели."

    await context.bot.send_message(
        chat_id=target_chat,
        text=f"Ежедневная статистика за {report_date}:\n{summary_text[:4000]}",
    )
    with log_path.open("rb") as handle:
        await context.bot.send_document(
            chat_id=target_chat,
            document=handle,
            filename=log_path.name,
            caption=f"Сырой лог переписок за {report_date}",
        )


def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            STATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, capture_name)],
            STATE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, capture_phone)],
            STATE_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, capture_question)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_free_text))

    if application.job_queue:
        daily_time = dtime(hour=DAILY_ANALYTICS_HOUR, minute=DAILY_ANALYTICS_MINUTE, tzinfo=ANALYTICS_TZ)
        application.job_queue.run_daily(_send_daily_analytics, time=daily_time)

    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
