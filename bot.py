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

TABLE_NAME = "bot_memory"


# ============================================================
# СИСТЕМНЫЙ ПРОМПТ
# ============================================================

SYSTEM_PROMPT = """
Ты — личный помощник по планированию питания для Марианны и Павла.

Главная задача — создавать практичные меню на 3 дня, рецепты и списки
покупок с минимальным количеством готовки.

============================================================
МАРИАННА
============================================================

Марианна категорически не ест:
- любые фрукты;
- любые овощи, кроме картофеля;
- ягоды;
- острое.

Это ЖЁСТКИЕ ограничения.

Даже если в памяти пользователя появятся другие предпочтения,
они НЕ отменяют эти ограничения.

Не предлагай Марианне запрещённые продукты:
- отдельно;
- в соусах;
- в заправках;
- в начинках;
- в украшениях;
- в небольших количествах.

Марианна находится на дефиците калорий.

Еда должна быть:
- сытной;
- достаточно объёмной;
- относительно низкокалорийной;
- не слишком жирной;
- с нормальным количеством белка.

Не делай Марианне слишком маленькие порции только ради снижения
калорийности.

============================================================
ПАВЕЛ
============================================================

Павел ест всё, но не любит жирные и тяжёлые блюда.

Цель Павла — набор мышечной массы без лишнего набора жира.

Не делай его питание экстремально калорийным или жирным.

Нужны обычные полноценные блюда с достаточным количеством белка.

Завтрак Павла должен быть обычным, средним по размеру,
а не огромным.

============================================================
ГЛАВНОЕ ПРАВИЛО ЦИКЛА
============================================================

Один цикл = 3 дня.

В течение всех трёх дней одинаковыми остаются:

- завтрак Павла;
- основное блюдо;
- гарнир/дополнение;
- овощное дополнение Павла;
- хрустящее низкокалорийное дополнение Марианны.

Всё необходимое должно быть приготовлено один раз в первый день.

В следующие два дня желательно только:
- разогревать;
- раскладывать;
- собирать готовые порции.

Не планируй ежедневную полноценную готовку.

============================================================
ПРИГОТОВЛЕНИЕ
============================================================

Использовать только:
- плиту;
- духовку.

Не использовать:
- аэрогриль;
- миксер;
- блендер;
- другую специальную технику.

Блюда должны быть простыми или максимум средней сложности.

Главный приоритет — минимум готовки.

============================================================
ПОРЦИИ
============================================================

Для Марианны и Павла рассчитывай порции отдельно.

Всегда указывай:
- количество ингредиентов;
- количество готового блюда;
- дневную порцию каждого человека;
- сколько приготовить всего на 3 дня.

============================================================
КБЖУ
============================================================

КБЖУ рассчитывай арифметически по фактическому количеству
каждого ингредиента.

Используй стандартные средние значения, если точных данных
о продукте нет.

Для каждого человека отдельно указывай:
- калории;
- белки;
- жиры;
- углеводы.

Проверяй арифметику перед выдачей.

Не увеличивай калорийность Павла просто за счёт масла,
сливок или других жирных продуктов.

============================================================
ЗАКУСКА МАРИАННЫ
============================================================

Должно быть простое хрустящее дополнение:

- без овощей;
- без фруктов;
- без ягод;
- не острое;
- до 100 ккал в день;
- не требует ежедневной готовки.

============================================================
ОВОЩНОЕ ДОПОЛНЕНИЕ ПАВЛА
============================================================

Павлу можно добавлять овощи.

Овощное дополнение должно быть рассчитано сразу на 3 дня.

Важно:
овощи Павла НЕ относятся к ограничениям Марианны.

============================================================
ХРАНЕНИЕ
============================================================

Все блюда должны реалистично храниться 3 дня.

Если блюдо плохо подходит для хранения 3 дня —
не используй его.

============================================================
ПОКУПКИ
============================================================

Создавай список продуктов на весь 3-дневный цикл.

Учитывай:
- двух человек;
- все 3 дня;
- реальные размеры порций;
- все ингредиенты;
- соусы;
- заправки;
- специи.

Группируй покупки по категориям.

Продукты должны быть доступны в Суботице.

В первую очередь ориентируйся на:
- IDEA;
- MAXI.

Не используй редкие или экзотические продукты без необходимости.

============================================================
ПРОДУКТЫ ДОМА
============================================================

Память содержит актуальные продукты дома.

Если пользователь говорит:
«Купили 2 кг курицы»

добавь 2 кг курицы.

Если говорит:
«Использовали 500 г курицы»

уменьши остаток на 500 г.

Если говорит:
«Курица закончилась»

удали её из запасов.

Если пользователь спрашивает:
«Что есть дома?»

покажи актуальные известные остатки.

При создании нового меню обязательно учитывай продукты,
которые уже есть дома.

Количество продуктов не придумывай.

============================================================
ПРЕДПОЧТЕНИЯ
============================================================

Память может содержать:

- любимые продукты;
- нелюбимые продукты;
- любимые блюда;
- нелюбимые блюда;
- блюда, которые надоели;
- блюда, которые нельзя предлагать;
- другие комментарии о вкусах.

Учитывай эти данные при создании меню.

ВАЖНО:

Постоянные ограничения важнее обычных предпочтений.

Например, если в памяти появится предпочтение Марианны
к какому-либо овощу, это НЕ отменяет правило,
что Марианна не ест овощи.

============================================================
ОЦЕНКИ
============================================================

Оценки хранятся отдельно.

Возможные оценки:

❤️ очень понравилось
🙂 нормально
😐 не понравилось
🚫 больше никогда

Если пользователь сообщает оценку блюда,
сохрани её.

Если блюдо получило 🚫 — не предлагай его снова,
если пользователь прямо не попросит.

Если блюдо получило ❤️ — его можно повторить позже.

Также учитывай комментарии:
- «надоело»;
- «слишком жирное»;
- «слишком сложно»;
- «долго готовить»;
- «можно повторять»;
- и т.п.

============================================================
ИСТОРИЯ МЕНЮ
============================================================

Память содержит текущий цикл и несколько последних циклов.

Используй историю, чтобы:
- не повторять одно и то же слишком часто;
- учитывать понравившиеся блюда;
- учитывать неудачные блюда;
- постепенно разнообразить меню.

============================================================
ЗАМЕНЫ
============================================================

Если пользователь просит заменить продукт или блюдо,
не просто скажи «можно заменить».

Пересчитай:
- ингредиенты;
- количество;
- порции;
- КБЖУ;
- список покупок.

============================================================
НОВОЕ МЕНЮ
============================================================

Когда пользователь пишет:
- «Новое меню»;
- «Составь новое меню»;
- «Давай новое меню»;
- «Сделай новое меню»;
- или аналогичную команду,

сразу создавай полный новый 3-дневный цикл.

Не спрашивай повторно:
- рост;
- вес;
- цели;
- ограничения;
- предпочтения,

если они уже есть в памяти.

Если критически важной информации действительно нет,
задай только необходимый вопрос.

============================================================
СЕГОДНЯ
============================================================

Если пользователь спрашивает:
- «Что сегодня едим?»;
- «Что есть сегодня?»;
- «Что кушать сегодня?»;

показывай текущее меню.

Не создавай новый цикл без просьбы.

============================================================
ПРОСМОТР ПАМЯТИ
============================================================

Если пользователь спрашивает:
- «Что ты обо мне помнишь?»;
- «Что ты помнишь о Павле?»;
- «Что ты помнишь обо мне?»;
- «Какие у нас предпочтения?»;
- «Что есть дома?»;

используй память и отвечай конкретными сохранёнными данными.

Не говори, что информации нет, если она есть в памяти.

============================================================
ГЛАВНОЕ ПРАВИЛО ПАМЯТИ
============================================================

Если данные уже находятся в памяти — НЕ СПРАШИВАЙ ИХ ПОВТОРНО.

Никогда не смешивай данные Марианны и Павла.

Если пользователь сообщает новое значение,
оно заменяет старое значение для этого же человека.

Например:

«Вес Павла теперь 70 кг»

означает:

pavel.weight_kg = 70

а не изменение веса Марианны.

============================================================
ОБЩИЕ ПРАВИЛА
============================================================

Главный приоритет — практичность.

Не усложняй рецепты ради разнообразия.

Не нарушай ограничения Марианны.

Не делай Павлу жирное питание ради набора калорий.

Не делай Павлу огромные завтраки.

Не делай Марианне маленькие порции только ради дефицита.

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
# ЗАГРУЗКА ПАМЯТИ
# ============================================================

def load_user_memory(user_id, first_name):

    try:

        result = (
            supabase
            .table(TABLE_NAME)
            .select("memory")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )

        if result.data:

            data = result.data[0].get("memory")

            if isinstance(data, dict):

                data = migrate_memory(data)

                if not data["marianna"]["other"].get("user_name"):
                    data["marianna"]["other"]["user_name"] = first_name

                return data

    except Exception as e:

        print("SUPABASE LOAD ERROR:", repr(e))

    data = empty_memory()

    data["marianna"]["other"]["user_name"] = first_name

    return data


# ============================================================
# МИГРАЦИЯ
# ============================================================

def migrate_memory(old_memory):

    new_memory = empty_memory()

    if (
        "marianna" in old_memory
        or "pavel" in old_memory
        or "shared" in old_memory
    ):

        for key in new_memory:

            if key in old_memory and isinstance(old_memory[key], dict):

                new_memory[key].update(old_memory[key])

        return new_memory

    profile = old_memory.get("profile", {})

    if "height_cm" in profile:
        new_memory["marianna"]["height_cm"] = profile["height_cm"]

    if "weight_kg" in profile:
        new_memory["marianna"]["weight_kg"] = profile["weight_kg"]

    for field in [
        "food_at_home",
        "liked_dishes",
        "disliked_dishes",
        "dish_ratings",
        "current_menu",
        "menu_history"
    ]:

        if field in old_memory:

            if field in new_memory["shared"]:
                new_memory["shared"][field] = old_memory[field]

    return new_memory


# ============================================================
# СОХРАНЕНИЕ
# ============================================================

def save_user_memory(user_id, memory_data):

    try:

        existing = (
            supabase
            .table(TABLE_NAME)
            .select("id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )

        if existing.data:

            (
                supabase
                .table(TABLE_NAME)
                .update({
                    "memory": memory_data
                })
                .eq("user_id", user_id)
                .execute()
            )

        else:

            (
                supabase
                .table(TABLE_NAME)
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
# ИЗВЛЕЧЕНИЕ НОВОЙ ПАМЯТИ
# ============================================================

def extract_memory(user_message, current_memory):

    compact_memory = json.dumps(
        current_memory,
        ensure_ascii=False,
        separators=(",", ":")
    )

    prompt = f"""
Ты — модуль постоянной памяти.

Текущая память:

{compact_memory}

Новое сообщение пользователя:

{user_message}

Определи, нужно ли изменить постоянную память.

Сохраняй только информацию, которую пользователь действительно
сообщил.

Особенно отслеживай:

1. Марианна:
- рост;
- вес;
- цель;
- предпочтения;
- нелюбимые продукты;
- любимые блюда;
- комментарии.

2. Павел:
- рост;
- вес;
- цель;
- предпочтения;
- нелюбимые продукты;
- любимые блюда;
- комментарии.

3. Общие данные:
- продукты дома;
- количество продуктов;
- любимые блюда;
- нелюбимые блюда;
- оценки;
- комментарии;
- текущий цикл;
- история.

ВАЖНО ПРО ПРОДУКТЫ:

«Купили 2 кг курицы»
→ добавить курицу с количеством 2 кг.

«Использовали 500 г курицы»
→ уменьшить количество.

«Курица закончилась»
→ установить количество 0.

ВАЖНО ПРО ОЦЕНКИ:

❤️ = очень понравилось
🙂 = нормально
😐 = не понравилось
🚫 = больше никогда

Если пользователь оценивает конкретное блюдо,
сохрани название блюда, человека и оценку.

ВАЖНО ПРО ЛЮДЕЙ:

«Вес Павла 68 кг»
→ pavel.weight_kg = 68

«Вес Марианны 84 кг»
→ marianna.weight_kg = 84

«Мой вес 84 кг»
→ используй контекст предыдущей переписки и существующей
памяти, чтобы определить человека.

Не смешивай Марианну и Павла.

Если значение изменилось — новое значение заменяет старое.

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

Допустимые person:

marianna
pavel
shared

Для продуктов используй:

{{
  "person": "shared",
  "field": "food_at_home",
  "value": {{
    "курица": {{
      "amount": 2,
      "unit": "кг"
    }}
  }}
}}

Для оценки:

{{
  "person": "shared",
  "field": "dish_rating",
  "value": {{
    "person": "marianna",
    "dish": "Название блюда",
    "rating": "❤️",
    "comment": "понравилось"
  }}
}}

Если сохранять нечего:

{{
  "has_update": false,
  "updates": []
}}

Не придумывай данные.
"""

    try:

        response = client.responses.create(
            model="gpt-5-mini",
            instructions="""
Ты — модуль извлечения постоянной памяти.

Возвращай только валидный JSON.
Не используй Markdown.
Не добавляй объяснений.
Не придумывай данные.
""",
            input=prompt,
        )

        text = response.output_text.strip()

        text = re.sub(
            r"^```(?:json)?",
            "",
            text,
            flags=re.IGNORECASE
        )

        text = re.sub(
            r"```$",
            "",
            text
        ).strip()

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
# ПРИМЕНЕНИЕ ИЗМЕНЕНИЙ
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

        # ----------------------------------------------------
        # МАРИАННА / ПАВЕЛ
        # ----------------------------------------------------

        if person in ["marianna", "pavel"]:

            if field in [
                "height_cm",
                "weight_kg",
                "goal"
            ]:

                memory_data[person][field] = value

            else:

                memory_data[person]["other"][field] = value

        # ----------------------------------------------------
        # ОБЩАЯ ПАМЯТЬ
        # ----------------------------------------------------

        else:

            if field == "food_at_home":

                if isinstance(value, dict):

                    for product, product_data in value.items():

                        if (
                            isinstance(product_data, dict)
                            and "amount" in product_data
                        ):

                            amount = product_data.get("amount", 0)
                            unit = product_data.get("unit", "")

                            try:
                                amount = float(amount)
                            except:
                                continue

                            existing = (
                                memory_data["shared"]
                                ["food_at_home"]
                                .get(product)
                            )

                            if existing:

                                old_amount = existing.get("amount", 0)
                                old_unit = existing.get("unit", "")

                                if old_unit == unit:
                                    existing["amount"] = (
                                        old_amount + amount
                                    )
                                else:
                                    existing["amount"] = amount
                                    existing["unit"] = unit

                            else:

                                memory_data["shared"]["food_at_home"][product] = {
                                    "amount": amount,
                                    "unit": unit
                                }

            elif field == "liked_dishes":

                if isinstance(value, list):

                    for item in value:

                        if (
                            item
                            not in memory_data["shared"]["liked_dishes"]
                        ):

                            memory_data["shared"]["liked_dishes"].append(item)

            elif field == "disliked_dishes":

                if isinstance(value, list):

                    for item in value:

                        if (
                            item
                            not in memory_data["shared"]["disliked_dishes"]
                        ):

                            memory_data["shared"]["disliked_dishes"].append(item)

            elif field == "dish_rating":

                if isinstance(value, dict):

                    memory_data["shared"]["dish_ratings"].append(value)

                    # Не даём истории оценок разрастаться бесконечно
                    memory_data["shared"]["dish_ratings"] = (
                        memory_data["shared"]["dish_ratings"][-50:]
                    )

            elif field == "current_menu":

                memory_data["shared"]["current_menu"] = value

            elif field == "menu_history":

                if isinstance(value, list):

                    memory_data["shared"]["menu_history"].extend(value)

                    memory_data["shared"]["menu_history"] = (
                        memory_data["shared"]["menu_history"][-5:]
                    )

    return memory_data


# ============================================================
# УМЕНЬШЕНИЕ ПРОДУКТОВ
# ============================================================

def process_food_usage(user_message, memory_data):

    """
    Отдельно обрабатываем простые команды:
    «использовали 500 г курицы»
    «курица закончилась»

    Это позволяет надёжнее работать с остатками.
    """

    text = user_message.lower()

    if "законч" in text:

        food = memory_data["shared"]["food_at_home"]

        for product in list(food.keys()):

            if product.lower() in text:

                del food[product]

                print("FOOD REMOVED:", product)

    # Уменьшение количества оставляем GPT-модулю,
    # потому что естественный язык может быть разным.


# ============================================================
# КОМПАКТНАЯ ПАМЯТЬ
# ============================================================

def compact_memory_for_prompt(memory_data):

    data = {
        "marianna": memory_data.get("marianna", {}),
        "pavel": memory_data.get("pavel", {}),
        "shared": {
            "food_at_home": (
                memory_data
                .get("shared", {})
                .get("food_at_home", {})
            ),
            "liked_dishes": (
                memory_data
                .get("shared", {})
                .get("liked_dishes", [])
            ),
            "disliked_dishes": (
                memory_data
                .get("shared", {})
                .get("disliked_dishes", [])
            ),
            "dish_ratings": (
                memory_data
                .get("shared", {})
                .get("dish_ratings", [])[-30:]
            ),
            "current_menu": (
                memory_data
                .get("shared", {})
                .get("current_menu")
            ),
            "menu_history": (
                memory_data
                .get("shared", {})
                .get("menu_history", [])[-3:]
            )
        }
    }

    return json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":")
    )


# ============================================================
# ОПРЕДЕЛЕНИЕ КОМАНД
# ============================================================

def is_new_menu_request(text):

    text = text.lower()

    phrases = [
        "новое меню",
        "составь новое меню",
        "давай новое меню",
        "сделай новое меню",
        "приготовь новое меню",
        "следующее меню",
    ]

    return any(phrase in text for phrase in phrases)


def is_home_food_request(text):

    text = text.lower()

    phrases = [
        "что есть дома",
        "что у нас дома",
        "какие продукты дома",
        "что осталось дома",
    ]

    return any(phrase in text for phrase in phrases)


def is_memory_request(text):

    text = text.lower()

    phrases = [
        "что ты помнишь",
        "что ты обо мне помнишь",
        "что помнишь обо мне",
        "что помнишь о павле",
        "что помнишь о марианне",
        "какие у нас предпочтения",
    ]

    return any(phrase in text for phrase in phrases)


# ============================================================
# ПРОДУКТЫ ДОМА — ПОНЯТНЫЙ ВЫВОД
# ============================================================

def format_food_at_home(memory_data):

    food = memory_data["shared"]["food_at_home"]

    if not food:

        return "Сейчас в памяти нет сохранённых продуктов дома."

    lines = ["🛒 Сейчас дома известно:"]

    for product, data in food.items():

        if isinstance(data, dict):

            amount = data.get("amount", "")
            unit = data.get("unit", "")

            if isinstance(amount, float) and amount.is_integer():
                amount = int(amount)

            lines.append(
                f"• {product} — {amount} {unit}".strip()
            )

    return "\n".join(lines)


# ============================================================
# ПАМЯТЬ — ПОНЯТНЫЙ ВЫВОД
# ============================================================

def format_memory(memory_data):

    marianna = memory_data["marianna"]
    pavel = memory_data["pavel"]
    shared = memory_data["shared"]

    lines = [
        "🧠 Что сейчас сохранено:",
        "",
        "👩 Марианна:"
    ]

    if marianna.get("height_cm"):
        lines.append(f"• Рост: {marianna['height_cm']} см")

    if marianna.get("weight_kg"):
        lines.append(f"• Вес: {marianna['weight_kg']} кг")

    if marianna.get("goal"):
        lines.append(f"• Цель: {marianna['goal']}")

    if marianna.get("other"):
        for key, value in marianna["other"].items():

            if key != "user_name":
                lines.append(f"• {key}: {value}")

    lines.append("")
    lines.append("👨 Павел:")

    if pavel.get("height_cm"):
        lines.append(f"• Рост: {pavel['height_cm']} см")

    if pavel.get("weight_kg"):
        lines.append(f"• Вес: {pavel['weight_kg']} кг")

    if pavel.get("goal"):
        lines.append(f"• Цель: {pavel['goal']}")

    if pavel.get("other"):

        for key, value in pavel["other"].items():
            lines.append(f"• {key}: {value}")

    lines.append("")
    lines.append("❤️ Любимые блюда:")

    if shared["liked_dishes"]:
        for dish in shared["liked_dishes"]:
            lines.append(f"• {dish}")
    else:
        lines.append("• пока нет")

    lines.append("")
    lines.append("🚫 Нелюбимые блюда:")

    if shared["disliked_dishes"]:
        for dish in shared["disliked_dishes"]:
            lines.append(f"• {dish}")
    else:
        lines.append("• пока нет")

    lines.append("")
    lines.append(format_food_at_home(memory_data))

    return "\n".join(lines)


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
        "Я запоминаю:\n"
        "• ваши данные;\n"
        "• продукты дома;\n"
        "• предпочтения;\n"
        "• оценки блюд;\n"
        "• текущие и прошлые меню.\n\n"
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

    # --------------------------------------------------------
    # Загружаем память
    # --------------------------------------------------------

    memory_data = load_user_memory(
        user_id,
        update.effective_user.first_name
    )

    # --------------------------------------------------------
    # Специальные простые запросы
    # --------------------------------------------------------

    if is_home_food_request(user_message):

        await send_long_message(
            update.message,
            format_food_at_home(memory_data)
        )

        return

    if is_memory_request(user_message):

        await send_long_message(
            update.message,
            format_memory(memory_data)
        )

        return

    # --------------------------------------------------------
    # Извлекаем новую память
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

        process_food_usage(
            user_message,
            memory_data
        )

        save_user_memory(
            user_id,
            memory_data
        )

    # --------------------------------------------------------
    # Компактная память
    # --------------------------------------------------------

    memory_context = compact_memory_for_prompt(
        memory_data
    )

    # --------------------------------------------------------
    # Основной запрос GPT
    # --------------------------------------------------------

    prompt = f"""
ПОСТОЯННАЯ ПАМЯТЬ:

{memory_context}

СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ:

{user_message}

Используй память как источник фактов.

ВАЖНО:

1. Не спрашивай повторно информацию, которая уже есть в памяти.

2. Данные Марианны и Павла не смешивай.

3. Жёсткие ограничения Марианны имеют приоритет над
   обычными предпочтениями.

4. Если пользователь просит новое меню — сразу создавай
   полный новый 3-дневный цикл.

5. Если пользователь сообщает продукты дома —
   учитывай их.

6. Если пользователь сообщает оценку блюда —
   учитывай сохранённую оценку.

7. Если блюдо имеет оценку 🚫 — не предлагай его снова,
   кроме прямой просьбы пользователя.

8. Если пользователь просит заменить блюдо или продукт —
   пересчитай весь цикл.

9. При создании меню используй историю прошлых меню,
   чтобы не повторять блюда слишком часто.

10. Не придумывай отсутствующие факты.

11. Отвечай на русском.

Если пользователь просит новое меню, формат должен начинаться:

🍽️ МЕНЮ НА 3 ДНЯ — ЦИКЛ

Затем обязательно укажи:

- завтрак Павла;
- основное блюдо;
- гарнир/дополнение;
- овощное дополнение Павла;
- хрустящее дополнение Марианны;
- приготовление;
- хранение;
- список покупок;
- КБЖУ Марианны;
- КБЖУ Павла.

Для каждого блюда укажи реальные количества ингредиентов,
сколько приготовить всего и сколько получает каждый человек
в день.

КБЖУ рассчитывай арифметически по ингредиентам.
"""

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
    # Если создано новое меню — сохраняем цикл
    # --------------------------------------------------------

    if is_new_menu_request(user_message):

        history = memory_data["shared"]["menu_history"]

        old_current = memory_data["shared"].get("current_menu")

        if old_current:

            history.append(old_current)

        # Храним только последние 5 циклов
        history = history[-5:]

        memory_data["shared"]["menu_history"] = history

        memory_data["shared"]["current_menu"] = answer

        save_user_memory(
            user_id,
            memory_data
        )

        print("MENU SAVED")

    # --------------------------------------------------------
    # Отправляем ответ
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
# TELEGRAM
# ============================================================

async def run_bot():

    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
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

    asyncio.create_task(
        run_bot()
    )

    from hypercorn.asyncio import serve
    from hypercorn.config import Config

    config = Config()

    config.bind = [
        f"0.0.0.0:{os.environ.get('PORT', '10000')}"
    ]

    await serve(
        app,
        config
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    asyncio.run(main())
