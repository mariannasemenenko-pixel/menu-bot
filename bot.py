````python
import os
import asyncio
import json

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

ВАЖНЕЙШЕЕ ПРАВИЛО:
У тебя есть постоянная память пользователя.
Если информация уже находится в памяти — НИКОГДА не спрашивай её повторно.

============================================================
МАРИАННА
============================================================

Марианна категорически не ест:
- любые фрукты;
- любые овощи, кроме картофеля;
- ягоды;
- острое.

Марианна находится на дефиците калорий.

Еда должна быть:
- сытной;
- достаточно объёмной;
- относительно низкокалорийной;
- не слишком жирной;
- с нормальным количеством белка.

Не предлагай запрещённые продукты даже в соусах, заправках или украшениях.

============================================================
ПАВЕЛ
============================================================

Павел ест всё, но не любит жирные и тяжёлые блюда.

Цель Павла — набор мышечной массы без лишнего набора жира.

Не делай его питание экстремально калорийным или очень жирным.

Завтрак Павла должен быть обычным, средним по размеру.

============================================================
ЦИКЛ МЕНЮ
============================================================

Один цикл длится 3 дня.

Во все три дня одинаковыми остаются:
- завтрак Павла;
- основное блюдо;
- гарнир/дополнение;
- овощное дополнение Павла;
- хрустящая низкокалорийная закуска Марианны.

Всё необходимое готовится один раз в первый день.

В следующие два дня желательно только разогревать и раскладывать еду.

============================================================
ПРИГОТОВЛЕНИЕ
============================================================

Использовать только:
- плиту;
- духовку.

Не использовать аэрогриль, миксер и другую специальную технику.

Блюда простые или максимум средней сложности.

Главный приоритет — минимум готовки.

============================================================
ПОРЦИИ И КБЖУ
============================================================

Для Марианны и Павла рассчитывай порции отдельно.

Всегда указывай:
- количество ингредиентов;
- количество готового блюда;
- размер дневной порции;
- сколько приготовить всего на 3 дня.

КБЖУ рассчитывай арифметически по фактическому количеству ингредиентов.

Для каждого человека отдельно:
- калории;
- белки;
- жиры;
- углеводы.

Не увеличивай калорийность Павла просто за счёт масла, сливок и других жирных продуктов.

============================================================
ЗАКУСКА МАРИАННЫ
============================================================

Простое хрустящее дополнение:
- без овощей;
- без фруктов;
- без ягод;
- не острое;
- до 100 ккал в день;
- не требует ежедневной готовки.

============================================================
ОВОЩИ ПАВЛА
============================================================

Павлу добавляй простое овощное дополнение, рассчитанное сразу на 3 дня.

============================================================
ХРАНЕНИЕ
============================================================

Все блюда должны реалистично храниться 3 дня.

============================================================
ПОКУПКИ
============================================================

Список продуктов на весь 3-дневный цикл.

Учитывай:
- двух человек;
- все 3 дня;
- реальные порции;
- все ингредиенты;
- соусы и заправки.

Группируй покупки по категориям.

Продукты должны быть доступны в Суботице.
В первую очередь ориентируйся на IDEA и MAXI.

============================================================
ОСТАТКИ
============================================================

Если пользователь сообщает, что продукт уже есть дома, учитывай его и вычитай из списка покупок.

============================================================
ЗАМЕНЫ
============================================================

При замене блюда или продукта пересчитай:
- ингредиенты;
- порции;
- КБЖУ;
- список покупок.

============================================================
ИСТОРИЯ И ОЦЕНКИ
============================================================

Учитывай предыдущие меню и оценки.

Не повторяй одно и то же основное блюдо слишком часто.

Если блюдо отмечено как «больше не готовить» — не предлагай его снова без прямой просьбы.

============================================================
ПАМЯТЬ
============================================================

В памяти отдельно хранятся данные Марианны и Павла.

Если пользователь говорит:

«Вес Павла 68 кг. Запомни это»

нужно понимать, что:
person = Pavel
field = weight_kg
value = 68

Если пользователь говорит:

«Мой вес 84 кг»

и контекст показывает, что речь идёт о Марианне, нужно сохранить:
person = Marianna
field = weight_kg
value = 84

Если пользователь говорит:
«Вес Павла теперь 70 кг»

новое значение 70 кг заменяет старое значение 68 кг.

Никогда не переносить данные Марианны на Павла и наоборот.

Если данные уже есть в памяти, не спрашивай их повторно.

============================================================
НОВОЕ МЕНЮ
============================================================

Когда пользователь пишет:
- «Новое меню»
- «Составь новое меню»
- «Давай новое меню»
- или аналогичную команду

сразу создавай полный 3-дневный цикл.

Не спрашивай повторно рост, вес, цели или ограничения, если они уже есть в памяти.

============================================================
СЕГОДНЯ
============================================================

Если пользователь спрашивает, что есть сегодня, показывай текущее меню.

============================================================
ЯЗЫК
============================================================

Отвечай на русском языке.
"""


# ============================================================
# СТРУКТУРА ПАМЯТИ
# ============================================================

def empty_memory():
    return {
        "marianna": {
            "height_cm": None,
            "weight_kg": None,
            "goal": None,
            "other": {}
        },

        "pavel": {
            "height_cm": None,
            "weight_kg": None,
            "goal": None,
            "other": {}
        },

        "shared": {
            "food_at_home": {},
            "liked_dishes": [],
            "disliked_dishes": [],
            "dish_ratings": [],
            "current_menu": None,
            "menu_history": []
        }
    }


# ============================================================
# SUPABASE — ЗАГРУЗКА
# ============================================================

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
                # На случай старой структуры памяти
                data = migrate_memory(data)
                return data

    except Exception as e:
        print("SUPABASE LOAD ERROR:", repr(e))

    data = empty_memory()

    data["marianna"]["other"]["user_name"] = first_name

    return data


# ============================================================
# МИГРАЦИЯ СТАРОЙ ПАМЯТИ
# ============================================================

def migrate_memory(old_memory):
    """
    Если в Supabase уже лежит память старого формата,
    переносим максимально полезные данные в новую структуру.
    """

    new_memory = empty_memory()

    # Если это уже новая структура
    if "marianna" in old_memory or "pavel" in old_memory:
        for key in new_memory:
            if key in old_memory and isinstance(old_memory[key], dict):
                new_memory[key].update(old_memory[key])

        return new_memory

    # Старая структура profile
    profile = old_memory.get("profile", {})

    if "height_cm" in profile:
        new_memory["marianna"]["height_cm"] = profile["height_cm"]

    if "weight_kg" in profile:
        new_memory["marianna"]["weight_kg"] = profile["weight_kg"]

    # Старые списки
    if "food_at_home" in old_memory:
        new_memory["shared"]["food_at_home"] = old_memory["food_at_home"]

    if "liked_dishes" in old_memory:
        new_memory["shared"]["liked_dishes"] = old_memory["liked_dishes"]

    if "disliked_dishes" in old_memory:
        new_memory["shared"]["disliked_dishes"] = old_memory["disliked_dishes"]

    if "dish_ratings" in old_memory:
        new_memory["shared"]["dish_ratings"] = old_memory["dish_ratings"]

    if "current_menu" in old_memory:
        new_memory["shared"]["current_menu"] = old_memory["current_menu"]

    if "menu_history" in old_memory:
        new_memory["shared"]["menu_history"] = old_memory["menu_history"]

    return new_memory


# ============================================================
# SUPABASE — СОХРАНЕНИЕ
# ============================================================

def save_user_memory(user_id, memory_data):
    try:
        existing = (
            supabase
            .table("bot_memory")
            .select("id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )

        if existing.data:
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
# OPENAI — ОПРЕДЕЛЕНИЕ НОВОЙ ПАМЯТИ
# ============================================================

def extract_memory(user_message, current_memory):

    compact_memory = json.dumps(
        current_memory,
        ensure_ascii=False,
        separators=(",", ":")
    )

    prompt = f"""
Ты управляешь постоянной памятью пользователя.

Текущая память:

{compact_memory}

Новое сообщение пользователя:

{user_message}

Определи, сообщает ли пользователь новую постоянную информацию,
которую нужно сохранить.

Особенно обращай внимание на:
- рост;
- вес;
- цели;
- предпочтения;
- нелюбимые продукты;
- любимые блюда;
- продукты дома;
- оценки блюд;
- изменения уже сохранённых данных.

ВАЖНО:

Если пользователь говорит «вес Павла 68 кг»,
это относится к pavel.weight_kg.

Если пользователь говорит «мой вес 84 кг»,
необходимо определить владельца данных из контекста.

Если пользователь говорит «вес Павла теперь 70 кг»,
замени старое значение.

Верни ТОЛЬКО JSON.

Формат:

{{
  "has_update": true,
  "updates": [
    {{
      "person": "pavel",
      "field": "weight_kg",
      "value": 68
    }}
  ]
}}

Если сохранять нечего:

{{
  "has_update": false,
  "updates": []
}}

Допустимые person:
- marianna
- pavel
- shared

Не придумывай информацию.
"""

    try:
        response = client.responses.create(
            model="gpt-5-mini",
            instructions="""
Ты — модуль извлечения постоянной памяти.
Возвращай только валидный JSON без Markdown.
Не придумывай данные.
""",
            input=prompt,
        )

        text = response.output_text.strip()

        # Убираем возможные ```json
        text = text.replace("```json", "").replace("```", "").strip()

        data = json.loads(text)

        if not isinstance(data, dict):
            return []

        if not data.get("has_update"):
            return []

        updates = data.get("updates", [])

        if not isinstance(updates, list):
            return []

        return updates

    except Exception as e:
        print("MEMORY EXTRACTION ERROR:", repr(e))
        return []


# ============================================================
# ПРИМЕНЕНИЕ ИЗМЕНЕНИЙ ПАМЯТИ
# ============================================================

def apply_memory_updates(memory_data, updates):

    for update in updates:

        if not isinstance(update, dict):
            continue

        person = update.get("person")
        field = update.get("field")
        value = update.get("value")

        if person not in ["marianna", "pavel", "shared"]:
            continue

        if not field:
            continue

        # marianna / pavel
        if person in ["marianna", "pavel"]:

            if field in [
                "height_cm",
                "weight_kg",
                "goal"
            ]:
                memory_data[person][field] = value

            else:
                memory_data[person]["other"][field] = value

        # shared
        else:

            if field == "food_at_home":

                if isinstance(value, dict):
                    memory_data["shared"]["food_at_home"].update(value)

            elif field == "liked_dishes":

                if isinstance(value, list):
                    for item in value:
                        if item not in memory_data["shared"]["liked_dishes"]:
                            memory_data["shared"]["liked_dishes"].append(item)

            elif field == "disliked_dishes":

                if isinstance(value, list):
                    for item in value:
                        if item not in memory_data["shared"]["disliked_dishes"]:
                            memory_data["shared"]["disliked_dishes"].append(item)

            elif field == "dish_rating":

                memory_data["shared"]["dish_ratings"].append(value)

            elif field == "current_menu":

                memory_data["shared"]["current_menu"] = value

            elif field == "menu_history":

                if isinstance(value, list):
                    memory_data["shared"]["menu_history"].extend(value)

    return memory_data


# ============================================================
# ДЛИННЫЕ СООБЩЕНИЯ TELEGRAM
# ============================================================

async def send_long_message(message, text):

    max_length = 3900

    if len(text) <= max_length:
        await message.reply_text(text)
        return

    while len(text) > max_length:

        cut = text.rfind("\n", 0, max_length)

        if cut < 1000:
            cut = max_length

        part = text[:cut]

        await message.reply_text(part)

        text = text[cut:].lstrip()

    if text:
        await message.reply_text(text)


# ============================================================
# START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "Привет! 🍽️\n\n"
        "Я помощник Марианны и Павла по меню.\n\n"
        "Я запоминаю ваши данные, продукты дома, "
        "предпочтения и оценки блюд.\n\n"
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

    # Загружаем память
    memory_data = load_user_memory(
        user_id,
        update.effective_user.first_name
    )

    # --------------------------------------------------------
    # 1. Сначала определяем новую постоянную информацию
    # --------------------------------------------------------

    updates = extract_memory(
        user_message,
        memory_data
    )

    if updates:

        print("MEMORY UPDATES:", updates)

        memory_data = apply_memory_updates(
            memory_data,
            updates
        )

        save_user_memory(
            user_id,
            memory_data
        )

    # --------------------------------------------------------
    # 2. Компактная память для основного GPT
    # --------------------------------------------------------

    memory_context = json.dumps(
        memory_data,
        ensure_ascii=False,
        separators=(",", ":")
    )

    # Защита от чрезмерно большой истории
    if len(memory_context) > 15000:
        memory_context = memory_context[:15000]

    prompt = f"""
ПОСТОЯННАЯ ПАМЯТЬ:

{memory_context}

СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ:

{user_message}

Используй память как источник фактов.

ВАЖНО:
- не спрашивай повторно то, что уже известно;
- данные Марианны и Павла не смешивай;
- если пользователь спрашивает конкретное сохранённое значение,
  ответь непосредственно;
- если пользователь просит новое меню — сразу составляй его;
- учитывай продукты дома;
- учитывай оценки и историю блюд;
- не придумывай отсутствующие данные.

Если информации действительно не хватает для выполнения задачи,
тогда задай только необходимый вопрос.
"""

    # --------------------------------------------------------
    # 3. Основной OpenAI
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # 4. Отправляем ответ
    # --------------------------------------------------------

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
# TELEGRAM BOT
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
````
