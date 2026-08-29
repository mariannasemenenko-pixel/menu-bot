import os
import asyncio
import json
import re

from flask import Flask
from openai import OpenAI
from supabase import create_client

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# ============================================================
# НАСТРОЙКИ
# ============================================================

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

client = OpenAI(api_key=OPENAI_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ============================================================
# СИСТЕМНЫЙ ПРОМПТ
# ============================================================

SYSTEM_PROMPT = """
Ты — личный помощник по планированию питания для Марианны и Павла.

Твоя главная задача — создавать практичные меню на 3 дня, рецепты и списки покупок с минимальным количеством готовки.

## Марианна

Марианна категорически не ест:
- любые фрукты;
- любые овощи, кроме картофеля;
- ягоды;
- острое.

Марианна находится на дефиците калорий.

Еда для неё должна быть:
- сытной;
- достаточно объёмной;
- относительно низкокалорийной;
- не слишком жирной;
- с нормальным количеством белка.

Не предлагай запрещённые продукты даже в небольших количествах, соусах или как украшение.

## Павел

Павел ест всё, но не любит жирные и тяжёлые блюда.

Его цель — набор мышечной массы без лишнего набора жира.

Не делай его питание экстремально калорийным или очень жирным.

Завтрак Павла должен быть обычным средним по размеру, не огромным.

## ЦИКЛ

Один цикл меню длится 3 дня.

В течение всех трёх дней одинаковыми остаются:
- завтрак Павла;
- основное блюдо;
- гарнир/дополнение;
- овощное дополнение Павла;
- хрустящая низкокалорийная закуска Марианны.

Всё необходимое готовится один раз в первый день.

В следующие два дня желательно только разогревать и раскладывать еду.

## ПРИГОТОВЛЕНИЕ

Использовать только:
- плиту;
- духовку.

Не использовать аэрогриль, миксер или другую специальную технику.

Блюда должны быть простыми или максимум средней сложности.

Главный приоритет — минимум готовки.

## ПОРЦИИ

Для Марианны и Павла рассчитывай порции отдельно.

Всегда указывай:
- количество ингредиентов;
- количество готового блюда;
- размер дневной порции;
- сколько приготовить всего на 3 дня.

## КБЖУ

КБЖУ рассчитывай арифметически по фактическому количеству ингредиентов.

Для каждого человека отдельно указывай:
- калории;
- белки;
- жиры;
- углеводы.

Не увеличивай калорийность Павла просто за счёт масла, сливок или других жирных продуктов.

## ЗАКУСКА МАРИАННЫ

Простое хрустящее дополнение:
- без овощей;
- без фруктов;
- без ягод;
- не острое;
- до 100 ккал на дневную порцию;
- не требует ежедневной готовки.

## ОВОЩИ ПАВЛА

Павлу добавляй простое овощное дополнение, рассчитанное сразу на 3 дня.

## ХРАНЕНИЕ

Все блюда должны реалистично храниться 3 дня.

## ПОКУПКИ

Создавай список продуктов на весь 3-дневный цикл.

Учитывай:
- двух человек;
- все 3 дня;
- реальные размеры порций;
- все ингредиенты;
- соусы и заправки.

Группируй покупки по категориям.

Ориентируйся на продукты, доступные в Суботице, в первую очередь IDEA и MAXI.

## ОСТАТКИ

Если пользователь сообщает, что продукты уже есть дома, учитывай их и вычитай из списка покупок.

## ЗАМЕНЫ

При замене продукта или блюда пересчитай:
- ингредиенты;
- порции;
- КБЖУ;
- покупки.

## ИСТОРИЯ

Учитывай предыдущие меню и оценки.

Не повторяй одно и то же основное блюдо слишком часто.

Любимые блюда можно повторять.

Если блюдо отмечено как «больше не готовить», не предлагай его снова без прямой просьбы.

## ПАМЯТЬ

Используй переданную память.

Если данные уже есть в памяти — НЕ спрашивай их повторно.

Особенно не спрашивай повторно:
- рост;
- вес;
- цели;
- ограничения;
- предпочтения;
- продукты дома;
- оценки блюд.

Если пользователь сообщает новые постоянные данные — используй их.

Если пользователь явно меняет данные — используй новые значения вместо старых.

## НОВОЕ МЕНЮ

Когда пользователь пишет «Новое меню» или аналогичную команду, сразу создавай новый полный 3-дневный цикл.

Не задавай повторно вопросы о данных, которые уже есть в памяти.

Формат:

🍽️ МЕНЮ НА 3 ДНЯ — ЦИКЛ N

Затем:
- завтрак Павла;
- основное блюдо;
- дополнение Павла;
- дополнение Марианны;
- приготовление;
- список покупок;
- КБЖУ.

## СЕГОДНЯ

Если пользователь спрашивает, что есть сегодня, показывай текущее меню.

## ОБЩИЕ ПРАВИЛА

Главный приоритет — практичность.

Не усложняй рецепты ради разнообразия.

Не нарушай ограничения Марианны.

Не делай Павлу жирное питание ради калорий.

Не делай Павлу огромные завтраки.

Не делай Марианне маленькие порции только ради снижения калорийности.

Отвечай на русском языке.
"""


# ============================================================
# ПАМЯТЬ SUPABASE
# ============================================================

def empty_memory():
    return {
        "profile": {},
        "food_at_home": {},
        "liked_dishes": [],
        "disliked_dishes": [],
        "dish_ratings": [],
        "current_menu": None,
        "menu_history": [],
    }


def load_user_memory(user_id, first_name):
    try:
        result = (
            supabase
            .table("bot_memory")
            .select("memory")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )

        if result.data:
            data = result.data[0].get("memory")

            if isinstance(data, dict):
                return data

    except Exception as e:
        print("SUPABASE LOAD ERROR:", repr(e))

    data = empty_memory()
    data["profile"]["name"] = first_name

    return data


def save_user_memory(user_id, memory_data):
    try:
        result = (
            supabase
            .table("bot_memory")
            .select("id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )

        if result.data:
            (
                supabase
                .table("bot_memory")
                .update({
                    "memory": memory_data
                })
                .eq("user_id", user_id)
                .execute()
            )
        else:
            (
                supabase
                .table("bot_memory")
                .insert({
                    "user_id": user_id,
                    "memory": memory_data
                })
                .execute()
            )

        print("MEMORY SAVED")

    except Exception as e:
        print("SUPABASE SAVE ERROR:", repr(e))


# ============================================================
# АВТОМАТИЧЕСКОЕ СОХРАНЕНИЕ ПРОСТЫХ ДАННЫХ
# ============================================================

def extract_memory_updates(text):
    text_lower = text.lower()
    updates = {}

    # Рост
    height = re.search(
        r"(?:рост|ростом)\s*(?:у меня\s*)?(\d{2,3})\s*(?:см|сантиметров)?",
        text_lower
    )

    if height:
        updates["height_cm"] = int(height.group(1))

    # Вес
    weight = re.search(
        r"(?:вес|вешу|весом)\s*(?:у меня\s*)?(\d{2,3}(?:[.,]\d+)?)\s*(?:кг|килограмм)?",
        text_lower
    )

    if weight:
        updates["weight_kg"] = float(
            weight.group(1).replace(",", ".")
        )

    return updates


# ============================================================
# РАСПОЗНАВАНИЕ ОЦЕНОК
# ============================================================

def extract_rating(text):
    text_lower = text.lower()

    rating = None

    if "🚫" in text or "больше никогда" in text_lower or "больше не готовить" in text_lower:
        rating = "🚫"
    elif "❤️" in text or "очень понрав" in text_lower:
        rating = "❤️"
    elif "🙂" in text or "нормально" in text_lower:
        rating = "🙂"
    elif "😐" in text or "не понрав" in text_lower:
        rating = "😐"

    return rating


# ============================================================
# ДЛИННЫЕ СООБЩЕНИЯ
# ============================================================

async def send_long_message(message, text):
    max_length = 3900

    if len(text) <= max_length:
        await message.reply_text(text)
        return

    chunks = []

    while len(text) > max_length:
        cut = text.rfind("\n", 0, max_length)

        if cut < 1000:
            cut = max_length

        chunks.append(text[:cut])
        text = text[cut:].lstrip()

    if text:
        chunks.append(text)

    for chunk in chunks:
        await message.reply_text(chunk)


# ============================================================
# START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! 🍽️\n\n"
        "Я помощник Марианны и Павла по меню.\n\n"
        "Я могу запоминать ваши данные, "
        "продукты дома, предпочтения и оценки блюд.\n\n"
        "Напиши мне что-нибудь!"
    )


# ============================================================
# ОСНОВНОЙ ЧАТ
# ============================================================

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = str(update.effective_user.id)
    user_message = update.message.text.strip()

    print("MESSAGE:", user_message)

    user_memory = load_user_memory(
        user_id,
        update.effective_user.first_name
    )

    # -----------------------------------------
    # Простые данные: рост / вес
    # -----------------------------------------

    updates = extract_memory_updates(user_message)

    if updates:
        if "profile" not in user_memory:
            user_memory["profile"] = {}

        user_memory["profile"].update(updates)

        save_user_memory(
            user_id,
            user_memory
        )

        print("PROFILE UPDATED:", updates)

    # -----------------------------------------
    # Оценки блюд
    # -----------------------------------------

    rating = extract_rating(user_message)

    if rating:
        if "dish_ratings" not in user_memory:
            user_memory["dish_ratings"] = []

        user_memory["dish_ratings"].append({
            "rating": rating,
            "comment": user_message
        })

        # 🚫 одновременно добавляем в список
        # нежелательных блюд
        if rating == "🚫":
            if "disliked_dishes" not in user_memory:
                user_memory["disliked_dishes"] = []

            user_memory["disliked_dishes"].append(
                user_message
            )

        save_user_memory(
            user_id,
            user_memory
        )

    # -----------------------------------------
    # Компактная память для OpenAI
    # -----------------------------------------

    memory_context = json.dumps(
        user_memory,
        ensure_ascii=False,
        separators=(",", ":")
    )

    # Защита от бесконечного роста памяти
    if len(memory_context) > 12000:
        memory_context = memory_context[:12000]

    prompt = f"""
Сохранённая память пользователя:

{memory_context}

Новое сообщение пользователя:

{user_message}

Используй сохранённую память.

Не спрашивай повторно информацию, которая уже есть в памяти.

Если пользователь сообщает новую постоянную информацию, учитывай её.

Если пользователь просит новое меню — сразу создавай меню,
используя сохранённые данные.
"""

    # -----------------------------------------
    # OpenAI
    # -----------------------------------------

    try:
        response = client.responses.create(
            model="gpt-5-mini",
            instructions=SYSTEM_PROMPT,
            input=prompt,
        )

        answer = response.output_text.strip()

        print("OPENAI OK")

    except Exception as e:
        print("OPENAI ERROR:", repr(e))

        await update.message.reply_text(
            "Произошла ошибка при обращении к ИИ 😔"
        )

        return

    # -----------------------------------------
    # Telegram
    # -----------------------------------------

    try:
        await send_long_message(
            update.message,
            answer
        )

        print("TELEGRAM RESPONSE SENT")

    except Exception as e:
        print("TELEGRAM ERROR:", repr(e))


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Menu bot is alive!"


# ============================================================
# TELEGRAM
# ============================================================

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

    await asyncio.Event().wait()


# ============================================================
# MAIN
# ============================================================

async def main():
    asyncio.create_task(run_bot())

    from hypercorn.asyncio import serve
    from hypercorn.config import Config

    config = Config()

    config.bind = [
        f"0.0.0.0:{os.environ.get('PORT', '10000')}"
    ]

    await serve(app, config)


if __name__ == "__main__":
    asyncio.run(main())
