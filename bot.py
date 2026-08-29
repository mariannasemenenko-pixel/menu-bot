import os
import asyncio

from flask import Flask
from openai import OpenAI

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

client = OpenAI(api_key=OPENAI_API_KEY)


SYSTEM_PROMPT = """
Ты — дружелюбный личный помощник Марианны и Павла.

Пока твоя задача — просто общаться с ними и отвечать на вопросы.
Позже ты будешь помогать им составлять меню, рецепты и списки покупок.

Отвечай на русском языке.
Будь понятным, дружелюбным и не слишком многословным.
"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! 🍽️\n\n"
        "Я подключён к ИИ.\n"
        "Напиши мне что-нибудь!"
    )


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text

    try:
        response = client.responses.create(
            model="gpt-5-mini",
            instructions=SYSTEM_PROMPT,
            input=user_message,
        )

        await update.message.reply_text(response.output_text)

    except Exception as e:
        print("OPENAI ERROR:", repr(e))

        await update.message.reply_text(
            "Произошла ошибка при обращении к ИИ 😔"
        )


async def run_bot():
    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            chat
        )
    )

    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    print("Telegram bot started!")

    # Держим приложение запущенным
    await asyncio.Event().wait()


app = Flask(__name__)


@app.route("/")
def home():
    return "Menu bot is alive!"


async def main():
    bot_task = asyncio.create_task(run_bot())

    from hypercorn.asyncio import serve
    from hypercorn.config import Config

    config = Config()
    config.bind = [
        f"0.0.0.0:{os.environ.get('PORT', '10000')}"
    ]

    await serve(app, config)


if __name__ == "__main__":
    asyncio.run(main())
