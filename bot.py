import os

from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler

app = Flask(__name__)

telegram_app = (
    Application.builder()
    .token(os.environ["TELEGRAM_BOT_TOKEN"])
    .updater(None)
    .build()
)


async def start(update: Update, context):
    await update.message.reply_text(
        "Привет! 🍽️\n\n"
        "Я будущий помощник по меню Марианны и Павла.\n"
        "Пока я только учусь, но скоро буду составлять "
        "меню, рецепты и списки покупок."
    )


async def help_command(update: Update, context):
    await update.message.reply_text(
        "Доступные команды:\n\n"
        "/start — запустить бота\n"
        "/help — помощь"
    )


telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("help", help_command))


@app.route("/")
def home():
    return "Menu bot is alive!"


@app.route("/telegram", methods=["POST"])
async def telegram_webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, telegram_app.bot)

    await telegram_app.process_update(update)

    return "OK"


if __name__ == "__main__":
    import asyncio
    from werkzeug.serving import run_simple

    async def main():
        await telegram_app.initialize()

        port = int(os.environ.get("PORT", 10000))

        run_simple(
            "0.0.0.0",
            port,
            app,
            threaded=False,
        )

    asyncio.run(main())
