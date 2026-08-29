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

Твоя главная задача — создавать практичные меню на 3 дня, рецепты
и списки покупок с минимальным количеством готовки.

ВАЖНО:
Постоянная память пользователя передаётся тебе отдельно.
Информация из памяти является фактом.

Если информация уже есть в памяти — НЕ спрашивай её повторно.

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

Никогда не предлагай Марианне запрещённые продукты,
в том числе в соусах, заправках или украшениях.

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

Не увеличивай калорийность Павла просто за счёт масла,
сливок и других жирных продуктов.

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

Павлу добавляй простое овощное дополнение,
рассчитанное сразу на 3 дня.

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

Если пользователь сообщает, что продукт уже есть дома,
учитывай его и вычитай из списка покупок.

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

Если блюдо отмечено как:
«больше не готовить»
или
«больше никогда»
— не предлагай его снова без прямой просьбы.

Последняя оценка блюда является актуальной.

============================================================
НОВОЕ МЕНЮ
============================================================

Когда пользователь пишет:
- «Новое меню»
- «Составь новое меню»
- «Давай новое меню»
- или аналогичную команду

сразу создавай полный 3-дневный цикл.

Не спрашивай повторно рост, вес, цели или ограничения,
если они уже есть в памяти.

============================================================
СЕГОДНЯ
============================================================

Если пользователь спрашивает, что есть сегодня,
показывай текущее меню.

============================================================
ПАМЯТЬ
============================================================

Память разделена между Марианной и Павлом.

Никогда не смешивай их данные.

Если пользователь сообщает новую информацию,
она должна быть сохранена.

Если пользователь изменяет существующую информацию,
старое значение должно быть заменено.

Если пользователь просит что-то удалить,
это действительно должно быть удалено из памяти.

Если пользователь просит удалить всю информацию о блюде,
необходимо считать это запросом на полное удаление этого блюда
из пользовательской памяти.

============================================================
ЯЗЫК
============================================================

Отвечай на русском языке.
"""


# ============================================================
# ПУСТАЯ ПАМЯТЬ
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
                return migrate_memory(data)

    except Exception as e:

        print("SUPABASE LOAD ERROR:", repr(e))

    data = empty_memory()

    data["marianna"]["other"]["user_name"] = first_name

    return data


# ============================================================
# МИГРАЦИЯ ПАМЯТИ
# ============================================================

def migrate_memory(old_memory):

    new_memory = empty_memory()

    # Уже новая структура
    if "marianna" in old_memory or "pavel" in old_memory:

        for key in new_memory:

            if key in old_memory and isinstance(old_memory[key], dict):

                new_memory[key].update(old_memory[key])

        return new_memory

    # Старая структура
    profile = old_memory.get("profile", {})

    if "height_cm" in profile:
        new_memory["marianna"]["height_cm"] = profile["height_cm"]

    if "weight_kg" in profile:
        new_memory["marianna"]["weight_kg"] = profile["weight_kg"]

    if "goal" in profile:
        new_memory["marianna"]["goal"] = profile["goal"]

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
# НОРМАЛИЗАЦИЯ ТЕКСТА
# ============================================================

def normalize_text(value):

    if value is None:
        return ""

    value = str(value).lower().strip()

    value = value.replace("ё", "е")

    value = re.sub(r"\s+", " ", value)

    return value


# ============================================================
# ПРОВЕРКА СОВПАДЕНИЯ НАЗВАНИЯ
# ============================================================

def text_matches(target, query):

    target = normalize_text(target)
    query = normalize_text(query)

    if not target or not query:
        return False

    if target == query:
        return True

    if query in target:
        return True

    if target in query:
        return True

    return False


# ============================================================
# ПОЛНОЕ УДАЛЕНИЕ БЛЮДА ИЗ ЛЮБЫХ СПИСКОВ
# ============================================================

def remove_dish_from_list(items, dish):

    if not isinstance(items, list):
        return items

    result = []

    for item in items:

        should_remove = False

        if isinstance(item, str):

            if text_matches(item, dish):
                should_remove = True

        elif isinstance(item, dict):

            for key in [
                "dish",
                "name",
                "title",
                "meal",
                "recipe",
                "value"
            ]:

                if key in item and text_matches(item[key], dish):
                    should_remove = True
                    break

        if not should_remove:
            result.append(item)

    return result


# ============================================================
# УДАЛЕНИЕ БЛЮДА ИЗ ПРОИЗВОЛЬНОГО JSON
# ============================================================

def remove_dish_recursive(value, dish):

    if isinstance(value, list):

        result = []

        for item in value:

            if isinstance(item, str):

                if text_matches(item, dish):
                    continue

            elif isinstance(item, dict):

                # Если сам объект явно относится к блюду
                object_matches = False

                for key in [
                    "dish",
                    "name",
                    "title",
                    "meal",
                    "recipe"
                ]:

                    if key in item and text_matches(item[key], dish):
                        object_matches = True
                        break

                if object_matches:
                    continue

                item = remove_dish_recursive(item, dish)

            else:

                item = remove_dish_recursive(item, dish)

            result.append(item)

        return result

    if isinstance(value, dict):

        result = {}

        for key, item in value.items():

            # Если ключ сам является названием блюда
            if text_matches(key, dish):
                continue

            result[key] = remove_dish_recursive(item, dish)

        return result

    return value


# ============================================================
# УДАЛЕНИЕ ВСЕЙ ИНФОРМАЦИИ О БЛЮДЕ
# ============================================================

def delete_all_about_dish(memory_data, dish):

    shared = memory_data.get("shared", {})

    # Любимые
    shared["liked_dishes"] = remove_dish_from_list(
        shared.get("liked_dishes", []),
        dish
    )

    # Нелюбимые
    shared["disliked_dishes"] = remove_dish_from_list(
        shared.get("disliked_dishes", []),
        dish
    )

    # Оценки
    shared["dish_ratings"] = remove_dish_from_list(
        shared.get("dish_ratings", []),
        dish
    )

    # Текущее меню
    if shared.get("current_menu") is not None:

        shared["current_menu"] = remove_dish_recursive(
            shared["current_menu"],
            dish
        )

    # История меню
    shared["menu_history"] = remove_dish_recursive(
        shared.get("menu_history", []),
        dish
    )

    # Остальные данные shared
    for key in list(shared.keys()):

        if key in [
            "liked_dishes",
            "disliked_dishes",
            "dish_ratings",
            "current_menu",
            "menu_history"
        ]:
            continue

        shared[key] = remove_dish_recursive(
            shared[key],
            dish
        )

    memory_data["shared"] = shared

    return memory_data


# ============================================================
# ОЦЕНКА БЛЮДА — ПОСЛЕДНЯЯ ЗАМЕНЯЕТ СТАРУЮ
# ============================================================

def update_dish_rating(memory_data, dish, person, rating):

    ratings = memory_data["shared"].get(
        "dish_ratings",
        []
    )

    new_ratings = []

    for item in ratings:

        if not isinstance(item, dict):
            new_ratings.append(item)
            continue

        item_dish = (
            item.get("dish")
            or item.get("name")
            or item.get("meal")
            or ""
        )

        item_person = item.get("person")

        if (
            text_matches(item_dish, dish)
            and item_person == person
        ):
            continue

        new_ratings.append(item)

    new_ratings.append({
        "dish": dish,
        "person": person,
        "rating": rating
    })

    memory_data["shared"]["dish_ratings"] = new_ratings

    return memory_data


# ============================================================
# ДОБАВЛЕНИЕ / ИЗМЕНЕНИЕ / УДАЛЕНИЕ ПАМЯТИ
# ============================================================

def apply_memory_updates(memory_data, operations):

    for operation in operations:

        if not isinstance(operation, dict):
            continue

        action = operation.get("action")

        # ====================================================
        # ADD / UPDATE
        # ====================================================

        if action in ["add", "update"]:

            person = operation.get("person")
            field = operation.get("field")
            value = operation.get("value")

            if person not in [
                "marianna",
                "pavel",
                "shared"
            ]:
                continue

            if not field:
                continue

            if person in ["marianna", "pavel"]:

                if field in [
                    "height_cm",
                    "weight_kg",
                    "goal"
                ]:

                    memory_data[person][field] = value

                else:

                    memory_data[person]["other"][field] = value

            else:

                if field == "food_at_home":

                    if isinstance(value, dict):

                        memory_data[
                            "shared"
                        ][
                            "food_at_home"
                        ].update(value)

                elif field == "liked_dishes":

                    if isinstance(value, list):

                        for item in value:

                            if item not in memory_data[
                                "shared"
                            ]["liked_dishes"]:

                                memory_data[
                                    "shared"
                                ]["liked_dishes"].append(item)

                elif field == "disliked_dishes":

                    if isinstance(value, list):

                        for item in value:

                            if item not in memory_data[
                                "shared"
                            ]["disliked_dishes"]:

                                memory_data[
                                    "shared"
                                ]["disliked_dishes"].append(item)

                elif field == "dish_rating":

                    if isinstance(value, dict):

                        dish = value.get("dish")
                        person_value = value.get("person")
                        rating = value.get("rating")

                        if dish and person_value and rating:

                            memory_data = update_dish_rating(
                                memory_data,
                                dish,
                                person_value,
                                rating
                            )

                elif field == "current_menu":

                    memory_data[
                        "shared"
                    ]["current_menu"] = value

                elif field == "menu_history":

                    if isinstance(value, list):

                        memory_data[
                            "shared"
                        ]["menu_history"].extend(value)

        # ====================================================
        # DELETE конкретного значения
        # ====================================================

        elif action == "delete":

            person = operation.get("person")
            field = operation.get("field")
            value = operation.get("value")

            if person not in [
                "marianna",
                "pavel",
                "shared"
            ]:
                continue

            # Удаление поля у человека
            if person in ["marianna", "pavel"]:

                if field in [
                    "height_cm",
                    "weight_kg",
                    "goal"
                ]:

                    if value is None or memory_data[
                        person
                    ].get(field) == value:

                        memory_data[
                            person
                        ][field] = None

                else:

                    memory_data[
                        person
                    ]["other"].pop(field, None)

            # Удаление shared
            else:

                if field == "food_at_home":

                    food = memory_data[
                        "shared"
                    ].get(
                        "food_at_home",
                        {}
                    )

                    if isinstance(food, dict):

                        keys_to_delete = []

                        for key in food.keys():

                            if (
                                value
                                and text_matches(key, value)
                            ):
                                keys_to_delete.append(key)

                        for key in keys_to_delete:
                            del food[key]

                elif field == "liked_dishes":

                    memory_data[
                        "shared"
                    ]["liked_dishes"] = remove_dish_from_list(
                        memory_data[
                            "shared"
                        ].get("liked_dishes", []),
                        value
                    )

                elif field == "disliked_dishes":

                    memory_data[
                        "shared"
                    ]["disliked_dishes"] = remove_dish_from_list(
                        memory_data[
                            "shared"
                        ].get("disliked_dishes", []),
                        value
                    )

                elif field == "dish_rating":

                    memory_data[
                        "shared"
                    ]["dish_ratings"] = remove_dish_from_list(
                        memory_data[
                            "shared"
                        ].get("dish_ratings", []),
                        value
                    )

        # ====================================================
        # ПОЛНОЕ УДАЛЕНИЕ БЛЮДА
        # ====================================================

        elif action == "delete_all_dish":

            dish = operation.get("dish")

            if dish:

                memory_data = delete_all_about_dish(
                    memory_data,
                    dish
                )

        # ====================================================
        # ПОЛНАЯ ОЧИСТКА ПРОДУКТОВ
        # ====================================================

        elif action == "clear_food":

            memory_data[
                "shared"
            ]["food_at_home"] = {}

    return memory_data


# ============================================================
# OPENAI — ИЗВЛЕЧЕНИЕ ОПЕРАЦИЙ ПАМЯТИ
# ============================================================

def extract_memory_operations(
    user_message,
    current_memory
):

    compact_memory = json.dumps(
        current_memory,
        ensure_ascii=False,
        separators=(",", ":")
    )

    prompt = f"""
Ты — модуль управления постоянной памятью.

ТЕКУЩАЯ ПАМЯТЬ:
{compact_memory}

НОВОЕ СООБЩЕНИЕ:
{user_message}

Твоя задача — определить, нужно ли изменить постоянную память.

Верни ТОЛЬКО JSON.

Никакого Markdown.
Никаких ```json.
Никаких пояснений.

============================================================
ДОПУСТИМЫЕ ACTION
============================================================

1. add

Добавить новую информацию.

2. update

Изменить существующую информацию.

3. delete

Удалить конкретную информацию.

4. delete_all_dish

Полностью удалить всю информацию о конкретном блюде.

5. clear_food

Полностью очистить список продуктов дома.

============================================================
ПРИМЕРЫ
============================================================

Пользователь:
Вес Павла 68 кг. Запомни.

Ответ:

{{
  "operations": [
    {{
      "action": "update",
      "person": "pavel",
      "field": "weight_kg",
      "value": 68
    }}
  ]
}}

------------------------------------------------------------

Пользователь:
Вес Павла теперь 70 кг.

Ответ:

{{
  "operations": [
    {{
      "action": "update",
      "person": "pavel",
      "field": "weight_kg",
      "value": 70
    }}
  ]
}}

------------------------------------------------------------

Пользователь:
Купили 2 кг куриного филе.

Ответ:

{{
  "operations": [
    {{
      "action": "add",
      "person": "shared",
      "field": "food_at_home",
      "value": {{
        "куриное филе": "2 кг"
      }}
    }}
  ]
}}

------------------------------------------------------------

Пользователь:
Куриное филе закончилось.

Ответ:

{{
  "operations": [
    {{
      "action": "delete",
      "person": "shared",
      "field": "food_at_home",
      "value": "куриное филе"
    }}
  ]
}}

------------------------------------------------------------

Пользователь:
Удали филе из продуктов.

Ответ:

{{
  "operations": [
    {{
      "action": "delete",
      "person": "shared",
      "field": "food_at_home",
      "value": "филе"
    }}
  ]
}}

------------------------------------------------------------

Пользователь:
Марианне понравилась запеканка.

Ответ:

{{
  "operations": [
    {{
      "action": "add",
      "person": "shared",
      "field": "dish_rating",
      "value": {{
        "dish": "запеканка",
        "person": "marianna",
        "rating": "like"
      }}
    }}
  ]
}}

------------------------------------------------------------

Пользователь:
Марианне не понравилась запеканка.

Ответ:

{{
  "operations": [
    {{
      "action": "update",
      "person": "shared",
      "field": "dish_rating",
      "value": {{
        "dish": "запеканка",
        "person": "marianna",
        "rating": "dislike"
      }}
    }}
  ]
}}

------------------------------------------------------------

Пользователь:
Запеканку больше никогда не готовить.

Ответ:

{{
  "operations": [
    {{
      "action": "add",
      "person": "shared",
      "field": "disliked_dishes",
      "value": ["запеканка"]
    }}
  ]
}}

------------------------------------------------------------

Пользователь:
Удали всю информацию о запеканке.

Ответ:

{{
  "operations": [
    {{
      "action": "delete_all_dish",
      "dish": "запеканка"
    }}
  ]
}}

============================================================
ОСОБО ВАЖНО
============================================================

Если пользователь использует слова:

- удали;
- удалить;
- забудь;
- забудь это;
- убери;
- больше не храни;
- сотри;
- очисти;

это является командой на ИЗМЕНЕНИЕ ПАМЯТИ.

Не сохраняй такую информацию как новое предпочтение.

Если пользователь говорит:
«Удали всю информацию о запеканке»

используй delete_all_dish.

Если пользователь говорит:
«Удали филе из продуктов»

используй delete для food_at_home.

Если пользователь даёт новую оценку тому же блюду и тому же человеку,
используй dish_rating.
Последняя оценка должна заменить предыдущую.

Никогда не придумывай данные.

Если ничего сохранять или удалять не нужно:

{{
  "operations": []
}}

"""


    try:

        response = client.responses.create(
            model="gpt-5-mini",
            instructions="""
Ты — модуль управления памятью.

Возвращай только валидный JSON.
Не используй Markdown.
Не добавляй пояснений.
Не придумывай данные.
""",
            input=prompt
        )

        text = response.output_text.strip()

        text = text.replace(
            "```json",
            ""
        ).replace(
            "```",
            ""
        ).strip()

        data = json.loads(text)

        if not isinstance(data, dict):
            return []

        operations = data.get(
            "operations",
            []
        )

        if not isinstance(operations, list):
            return []

        return operations

    except Exception as e:

        print(
            "MEMORY EXTRACTION ERROR:",
            repr(e)
        )

        return []


# ============================================================
# ДЛИННЫЕ TELEGRAM СООБЩЕНИЯ
# ============================================================

async def send_long_message(
    message,
    text
):

    max_length = 3900

    if len(text) <= max_length:

        await message.reply_text(text)

        return

    while len(text) > max_length:

        cut = text.rfind(
            "\n",
            0,
            max_length
        )

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

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "Привет! 🍽️\n\n"
        "Я помощник Марианны и Павла по меню.\n\n"
        "Я запоминаю ваши данные, продукты дома, "
        "предпочтения, оценки и историю меню.\n\n"
        "Напиши мне что-нибудь!"
    )


# ============================================================
# ОСНОВНОЙ ЧАТ
# ============================================================

async def chat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    if not update.message.text:
        return

    user_id = str(
        update.effective_user.id
    )

    user_message = (
        update.message.text.strip()
    )

    print(
        "MESSAGE:",
        user_message
    )

    # --------------------------------------------------------
    # 1. Загружаем память
    # --------------------------------------------------------

    memory_data = load_user_memory(
        user_id,
        update.effective_user.first_name
    )

    # --------------------------------------------------------
    # 2. Определяем операции памяти
    # --------------------------------------------------------

    operations = extract_memory_operations(
        user_message,
        memory_data
    )

    print(
        "MEMORY OPERATIONS:",
        operations
    )

    # --------------------------------------------------------
    # 3. Применяем операции
    # --------------------------------------------------------

    if operations:

        old_memory = json.dumps(
            memory_data,
            ensure_ascii=False,
            sort_keys=True
        )

        memory_data = apply_memory_updates(
            memory_data,
            operations
        )

        new_memory = json.dumps(
            memory_data,
            ensure_ascii=False,
            sort_keys=True
        )

        # Сохраняем только если память реально изменилась
        if old_memory != new_memory:

            save_user_memory(
                user_id,
                memory_data
            )

    # --------------------------------------------------------
    # 4. Формируем контекст для основного GPT
    # --------------------------------------------------------

    memory_context = json.dumps(
        memory_data,
        ensure_ascii=False,
        separators=(",", ":")
    )

    # Безопасность от чрезмерного размера
    if len(memory_context) > 30000:

        print(
            "WARNING: MEMORY TOO LARGE:",
            len(memory_context)
        )

        memory_context = memory_context[:30000]

    prompt = f"""
ПОСТОЯННАЯ ПАМЯТЬ ПОЛЬЗОВАТЕЛЯ:

{memory_context}

СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ:

{user_message}

============================================================

Используй память как источник фактов.

ВАЖНО:

- не спрашивай повторно то, что уже известно;
- данные Марианны и Павла не смешивай;
- если пользователь спрашивает конкретное сохранённое значение,
  ответь непосредственно;
- если пользователь просит новое меню — сразу составляй его;
- учитывай продукты дома;
- учитывай предпочтения;
- учитывай оценки;
- учитывай историю меню;
- не придумывай отсутствующие данные.

Если пользователь только что попросил удалить информацию,
не утверждай, что она всё ещё существует в памяти.

Если информации действительно не хватает для выполнения задачи,
задай только необходимый вопрос.
"""


    # --------------------------------------------------------
    # 5. Основной GPT
    # --------------------------------------------------------

    try:

        response = client.responses.create(
            model="gpt-5-mini",
            instructions=SYSTEM_PROMPT,
            input=prompt
        )

        answer = response.output_text.strip()

        print("OPENAI OK")

    except Exception as e:

        print(
            "OPENAI ERROR:",
            repr(e)
        )

        await update.message.reply_text(
            "Произошла ошибка при обращении к ИИ 😔"
        )

        return

    # --------------------------------------------------------
    # 6. Отправляем ответ
    # --------------------------------------------------------

    try:

        await send_long_message(
            update.message,
            answer
        )

        print(
            "TELEGRAM RESPONSE SENT"
        )

    except Exception as e:

        print(
            "TELEGRAM ERROR:",
            repr(e)
        )


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

    print(
        "Telegram bot started!"
    )

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
# RUN
# ============================================================

if __name__ == "__main__":

    asyncio.run(main())
