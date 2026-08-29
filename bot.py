import os
import asyncio

from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler


TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

application = (
    Application.builder()
    .token(TOKEN)
    .updater(None)
    .build()
)


async def start(update: Update, context):
    await update.message.reply_text(
        "Привет! 🍽️\n\n"
        "Я будущий помощник по меню Марианны и Павла.\n\n"
        "Пока я умею только здороваться 😄\n"
        "Но скоро научусь составлять меню, рецепты и списки покупок."
    )


async def help_command(update: Update, context):
    await update.message.reply_text(
        "Доступные команды:\n\n"
        "/start — запустить бота\n"
        "/help — помощь"
    )


application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_command))


flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Menu bot is alive!"


@flask_app.route("/telegram", methods=["POST"])
async def telegram_webhook():
    update = Update.de_json(
        request.get_json(),
        application.bot
    )

    await application.update_queue.put(update)

    return "OK"


async def run():
    await application.initialize()
    await application.start()

    port = int(os.environ.get("PORT", 10000))

    from hypercorn.asyncio import serve
    from hypercorn.config import Config

    config = Config()
    config.bind = [f"0.0.0.0:{port}"]

    await serve(flask_app, config)


if __name__ == "__main__":
    asyncio.run(run())
