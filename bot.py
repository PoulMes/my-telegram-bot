import asyncio
import logging
import os
import re
import time
from collections import defaultdict, deque
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
import signal

CONFIG = {
    "TOKEN": os.environ.get("TELEGRAM_BOT_TOKEN"),
    "ADMINS": [],
    "MESSAGES_PER_WINDOW": 5,
    "WINDOW_SECONDS": 8,
    "WARNINGS_TO_MUTE": 3,
    "MUTE_SECONDS": 0,
    "BLACKLIST": ["spamword1", "badword", "скам"],
    "BLOCK_LINKS": True,
    "BLOCK_FORWARDED": False,
    "CAPS_THRESHOLD": 0.85,
    "MIN_CHARS_FOR_CAPS": 8,
    "REPEAT_WINDOW": 3,
    "LONG_MSG_LIMIT": 800,
    "LONG_MSG_SENTENCES": 2,
    "STICKER_REPEAT": 5,
    "EMOJI_RATIO": 0.85,
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_msg_times = defaultdict(lambda: deque())
user_warnings = defaultdict(int)
user_last_texts = defaultdict(lambda: deque(maxlen=CONFIG["REPEAT_WINDOW"]))
user_last_stickers = defaultdict(lambda: deque(maxlen=CONFIG["STICKER_REPEAT"]))
user_last_emojis = defaultdict(lambda: deque()

)

URL_RE = re.compile(r"https?://|\w+\.\w{2,3}(/|$)", re.IGNORECASE)
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u26FF]", re.UNICODE)

def is_admin(user_id: int) -> bool:
    return user_id in CONFIG["ADMINS"]

def contains_blacklist(text: str) -> bool:
    txt = text.lower()
    return any(bad.lower() in txt for bad in CONFIG["BLACKLIST"])

def is_link(text: str) -> bool:
    return bool(URL_RE.search(text))

def caps_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)

def emoji_ratio(text: str) -> float:
    chars = [c for c in text if c.isalpha() or EMOJI_RE.match(c)]
    if not chars:
        return 0.0
    return sum(1 for c in chars if EMOJI_RE.match(c)) / len(chars)

async def warn_user(update: Update, context: ContextTypes.DEFAULT_TYPE, reason: str):
    user = update.effective_user
    user_warnings[user.id] += 1
    warns = user_warnings[user.id]
    logger.info(f"User {user.id} warned ({warns}): {reason}")
    try:
        await update.message.reply_text(f"⚠️ {reason}")
        await update.message.delete()
    except Exception:
        pass

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я антиспам-бот.")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.from_user:
        return

    user = message.from_user
    chat = message.chat

    if chat.type == "private" or is_admin(user.id):
        return

    now = time.time()
    text = message.text or message.caption or ""

    if text:
        last_texts = user_last_texts[user.id]
        last_texts.append(text)
        if len(last_texts) == last_texts.maxlen and all(t == text for t in last_texts):
            await warn_user(update, context, "Повтор одного и того же сообщения")
            return

    if text and len(text) >= CONFIG["LONG_MSG_LIMIT"] and len(re.findall(r'[.!?]\s', text)) < CONFIG["LONG_MSG_SENTENCES"]:
        await warn_user(update, context, "Длинное сообщение одной фразой")
        return

    if message.sticker:
        stickers = user_last_stickers[user.id]
        stickers.append(now)
        while stickers and now - stickers[0] > CONFIG["WINDOW_SECONDS"]:
            stickers.popleft()
        if len(stickers) >= CONFIG["STICKER_REPEAT"]:
            await warn_user(update, context, "Спам стикерами")
            return

    if text and len(text) > 5 and emoji_ratio(text) >= CONFIG["EMOJI_RATIO"]:
        emojis = user_last_emojis[user.id]
        emojis.append(now)
        while emojis and now - emojis[0] > CONFIG["WINDOW_SECONDS"]:
            emojis.popleft()
        if len(emojis) >= 3:
            await warn_user(update, context, "Слишком много эмодзи")
            return

async def main():
    token = CONFIG["TOKEN"]
    if not token:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN env var")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(MessageHandler(filters.ALL & ~filters.StatusUpdate.ALL, message_handler))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(app.updater.stop()))

    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped")
