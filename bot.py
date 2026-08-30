import os
import asyncio
import json
import re
import time
import traceback

from flask import Flask
from openai import AsyncOpenAI
from supabase import create_client

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
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

client = AsyncOpenAI(api_key=OPENAI_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Безопасный потолок на размер памяти, которую мы кладём в промпт.
# После перехода на компактную историю меню (только названия блюд,
# а не весь HTML) реальный размер должен быть в разы меньше этого лимита.
MEMORY_CHAR_LIMIT = 12000

# Сколько последних меню храним в компактной истории (только названия блюд)
MENU_HISTORY_LIMIT = 7


def log(*args):
    """
    Обычный print() на Render может буферизоваться и не долетать до логов
    вовремя (или теряться при рестарте контейнера). flush=True гарантирует,
    что строка реально попадёт в лог сразу.
    """
    print(*args, flush=True)


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
МЕНЮ НА 3 ДНЯ
============================================================

Одно меню действует 3 дня.

Во все три дня одинаковыми остаются:
- завтрак Павла;
- основное блюдо;
- гарнир/дополнение;
- овощное дополнение Павла;
- хрустящая низкокалорийная закуска Марианны.

Всё необходимое готовится один раз в первый день.

В следующие два дня — только использовать уже приготовленное.

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

Список продуктов на весь 3-дневный период.

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

Это очень важно.

Если пользователь просит заменить ОДНО блюдо в текущем меню,
НЕ создавай полностью новое меню с другими блюдами.

Нужно:
1. взять текущее меню из памяти;
2. определить конкретный элемент, который пользователь хочет заменить;
3. заменить только этот элемент;
4. сохранить все остальные блюда без изменений;
5. пересчитать порции, КБЖУ и список покупок;
6. сохранить обновлённое меню как текущее.

Например:

«Замени завтрак»
→ заменить только завтрак Павла.

«Замени основное блюдо»
→ заменить только основное блюдо.

«Замени закуску Марианны»
→ заменить только закуску Марианны.

«Замени овощи Павла»
→ заменить только овощное дополнение Павла.

Если пользователь предлагает конкретную замену,
используй именно её.

Например:

«Замени завтрак на сырники»
→ новый завтрак должен быть сырниками,
остальные элементы меню сохранить.

Если пользователь говорит:
«Мне надоел этот завтрак, давай другой»
→ понять, что речь идёт о завтраке,
и заменить только его.

При замене обязательно учитывай:
- ограничения Марианны;
- цели Павла;
- продукты, которые уже есть дома;
- предпочтения;
- оценки;
- блюда, которые запрещено повторять.

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

создай полное новое меню на 3 дня.

Учитывай:
- память;
- продукты дома;
- предпочтения;
- оценки;
- историю меню.

Не спрашивай повторно рост, вес, цели или ограничения,
если они уже есть в памяти.

============================================================
СЕГОДНЯ
============================================================

Если пользователь спрашивает:
- «Что есть сегодня?»
- «Что у нас сегодня?»
- «Какое меню сегодня?»

показывай текущее сохранённое меню.

Если текущего меню нет,
скажи, что текущего меню пока нет, и предложи создать новое.

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
ФОРМАТ ВЫВОДА МЕНЮ
============================================================

Если пользователь просит:
- новое меню;
- меню на 3 дня;
- рецепт меню;
- заменить блюдо в текущем меню;
- показать обновлённое меню;
- или любой другой запрос, результатом которого является меню,

ОБЯЗАТЕЛЬНО используй следующую структуру:

1. 🍽️ МЕНЮ НА 3 ДНЯ
2. 🛒 ПОКУПКИ НА 3 ДНЯ
3. 👨‍🍳 ПРИГОТОВЛЕНИЕ
4. ⚖️ ПОРЦИИ И КБЖУ

Ответ всегда в HTML для Telegram (parse_mode HTML).
Разрешены только теги: <b>, <i>, <u>, <s>, <code>, <pre>, <a>, <blockquote expandable>.
Не используй Markdown (**жирный**, # заголовки, ```код```).
Не экранируй эмодзи. Символы < и > в обычном тексте заменяй на &lt; и &gt;.

============================================================
1. 🍽️ МЕНЮ НА 3 ДНЯ
============================================================

Это должен быть самый короткий раздел.

Здесь НЕЛЬЗЯ писать:
- калории;
- КБЖУ;
- ингредиенты;
- количество продуктов;
- способ приготовления;
- граммы порций;
- дополнительные пояснения.

Только названия блюд.

В этом разделе должно быть РОВНО пять пунктов — ни больше, ни меньше:
завтрак Павла, основное блюдо, гарнир, закуска Марианны, овощи Павла.

КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО добавлять любые дополнительные блюда,
перекусы, десерты или другие пункты сверх этих пяти.
Не придумывай отдельный «перекус» — единственный перекус/закуска
во всём меню — это закуска Марианны, указанная ниже.

Используй формат:

<b>🍽️ МЕНЮ НА 3 ДНЯ</b>

🍳 <b>Завтрак Павла</b>
[название блюда]

🍗 <b>Основное</b>
[название блюда]

🥔 <b>Гарнир</b>
[название блюда]

🥨 <b>Закуска Марианны</b>
[название блюда]

🥦 <b>Овощи Павла</b>
[название блюда]

Не добавляй сюда ничего лишнего.

============================================================
2. 🛒 ПОКУПКИ НА 3 ДНЯ
============================================================

Здесь показывай ТОЛЬКО продукты, которые реально нужно купить.

Если продукт уже есть дома, вычти имеющееся количество из необходимого количества.

Например:

Нужно картофеля — 1,5 кг.
Дома есть картофель — 500 г.

В покупках должно быть:

• Картофель — 1 кг

НЕ пиши отдельный список или раздел «Продукты дома».

НЕ показывай продукты, которые уже полностью есть дома.

Группируй покупки по категориям.

Весь список покупок ОБЯЗАТЕЛЬНО помещай внутрь разворачивающегося блока:

<b>🛒 ПОКУПКИ НА 3 ДНЯ</b>
<blockquote expandable>
🥩 <b>Мясо / рыба</b>
• ...

🥛 <b>Молочное и яйца</b>
• ...

🥔 <b>Овощи и корнеплоды</b>
• ...

🥫 <b>Бакалея</b>
• ...
</blockquote>

При необходимости используй дополнительные категории.

Количество продуктов должно соответствовать реальным потребностям двух человек на все 3 дня.

============================================================
3. 👨‍🍳 ПРИГОТОВЛЕНИЕ
============================================================

Здесь давай подробное приготовление.

КАЖДОЕ блюдо из меню обязательно должно быть включено сюда:

- завтрак Павла;
- основное блюдо;
- гарнир;
- закуска Марианны;
- овощное дополнение Павла.

Даже если блюдо очень простое.

Это необходимо для того, чтобы было понятно, сколько именно приготовить на весь период.

Каждое блюдо — отдельный блок: заголовок снаружи, детали внутри <blockquote expandable>.

Используй формат:

<b>👨‍🍳 ПРИГОТОВЛЕНИЕ</b>

🍳 <b>Завтрак Павла</b> — [название] (на 3 дня)
<blockquote expandable>
<b>Ингредиенты</b> (на весь объём, 3 дня):
• ...
• ...

<b>Как готовить:</b>
1. ...
2. ...
3. ...
</blockquote>

🍗 <b>Основное</b> — [название] (на 3 дня)
<blockquote expandable>
<b>Ингредиенты</b> (на весь объём, 3 дня):
• ...
• ...

<b>Как готовить:</b>
1. ...
2. ...
3. ...
</blockquote>

🥔 <b>Гарнир</b> — [название] (на 3 дня)
<blockquote expandable>
<b>Ингредиенты</b> (на весь объём, 3 дня):
• ...
• ...

<b>Как готовить:</b>
1. ...
2. ...
3. ...
</blockquote>

🥨 <b>Закуска Марианны</b> — [название]
<blockquote expandable>
<b>Ингредиенты</b> (на весь объём, 3 дня):
• ...
• ...

<b>Как готовить:</b>
1. ...
</blockquote>

🥦 <b>Овощи Павла</b> — [название] (на 3 дня)
<blockquote expandable>
<b>Ингредиенты</b> (на весь объём, 3 дня):
• ...
• ...

<b>Как готовить:</b>
1. ...
2. ...
</blockquote>

Для каждого блюда указывай количество ингредиентов, необходимое для приготовления ВСЕГО объёма на 3 дня.

Не описывай приготовление отдельно для каждого дня.

Всё необходимое по возможности готовится в День 1.

НЕ пиши про:
- разогрев в дни 2–3;
- хранение в контейнерах;
- «разложить по порциям / контейнерам»;
- отдельный блок «Хранение и разогрев»;
- отдельный список того, что приготовить в День 1 — такого раздела в ответе быть не должно.

Только приготовление: ингредиенты и шаги готовки.

============================================================
4. ⚖️ ПОРЦИИ И КБЖУ
============================================================

Раздел обязательно разделяй отдельно для Марианны и Павла.

Для каждого человека указывай только те блюда, которые он действительно ест.

Используй формат:

<b>⚖️ ПОРЦИИ И КБЖУ</b>

🧑 <b>Марианна</b>

🍗 <b>Основное</b>
[размер порции] — [ккал]
Б [г] / Ж [г] / У [г]

🥔 <b>Гарнир</b>
[размер порции] — [ккал]
Б [г] / Ж [г] / У [г]

🥨 <b>Закуска</b>
[размер порции] — [ккал]
Б [г] / Ж [г] / У [г]

🔥 <b>Итого за день</b>
[ккал]
Б [г] / Ж [г] / У [г]


👨 <b>Павел</b>

🍳 <b>Завтрак</b>
[размер порции] — [ккал]
Б [г] / Ж [г] / У [г]

🍗 <b>Основное</b>
[размер порции] — [ккал]
Б [г] / Ж [г] / У [г]

🥔 <b>Гарнир</b>
[размер порции] — [ккал]
Б [г] / Ж [г] / У [г]

🥦 <b>Овощи</b>
[размер порции] — [ккал]
Б [г] / Ж [г] / У [г]

🔥 <b>Итого за день</b>
[ккал]
Б [г] / Ж [г] / У [г]

КБЖУ рассчитывай арифметически по фактическому количеству ингредиентов.

Не придумывай произвольные КБЖУ.

Размер порции должен соответствовать рассчитанному количеству готового блюда.

Если блюдо разделяется между Марианной и Павлом, учитывай фактическую долю каждого человека.

Для Марианны всегда используй эмодзи 🧑 (не 👩).

============================================================
ОБЩИЕ ПРАВИЛА ФОРМАТА
============================================================

Если создаётся полное меню, ВСЕГДА используй именно этот порядок:

🍽️ МЕНЮ НА 3 ДНЯ

🛒 ПОКУПКИ НА 3 ДНЯ

👨‍🍳 ПРИГОТОВЛЕНИЕ

⚖️ ПОРЦИИ И КБЖУ

Не меняй порядок разделов.

Не добавляй перед меню длинные вступления.

Не добавляй после меню заключения вроде:
«Приятного аппетита!»
«Если хочешь, могу...»
«Вот готовое меню...»

Если пользователь просит именно меню — сразу начинай с:

<b>🍽️ МЕНЮ НА 3 ДНЯ</b>

Каждый раздел должен быть компактным и легко читаемым в Telegram.

Заголовки разделов и названия блюд/категорий — в <b>...</b>.
Список покупок и детали каждого рецепта — в <blockquote expandable>...</blockquote>.

Не используй Markdown-таблицы.

Не заключай весь ответ в тройные обратные кавычки.

Не используй отдельные блоки кода для разделов.

При замене одного блюда сохраняй эту же структуру полного меню, но изменяй ТОЛЬКО запрошенный элемент.

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
            # Компактная история: список коротких словарей с названиями
            # блюд прошлых меню (НЕ полный текст), чтобы не раздувать память.
            "menu_history": []
        }
    }


# ============================================================
# OPENAI — ОБЩАЯ ФУНКЦИЯ
# ============================================================

async def ask_openai(instructions, input_text, timeout=90, label="call"):
    started = time.monotonic()

    try:
        response = await asyncio.wait_for(
            client.responses.create(
                model="gpt-5-mini",
                instructions=instructions,
                input=input_text
            ),
            timeout=timeout
        )

        elapsed = time.monotonic() - started
        log(f"OPENAI OK [{label}] in {elapsed:.1f}s")

        text = response.output_text.strip()

        if not text:
            log(f"OPENAI EMPTY RESPONSE [{label}]")
            return None

        return text

    except asyncio.TimeoutError:
        elapsed = time.monotonic() - started
        log(f"OPENAI TIMEOUT [{label}] AFTER {elapsed:.1f}s (limit {timeout}s)")
        return None

    except Exception as e:
        elapsed = time.monotonic() - started
        log(f"OPENAI ERROR [{label}] after {elapsed:.1f}s:", repr(e))
        return None


# ============================================================
# КЛАВИАТУРЫ
# ============================================================

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆕  Новое меню на 3 дня", callback_data="new_menu")],
        [InlineKeyboardButton("🔄  Заменить блюдо", callback_data="replace_menu")],
        [InlineKeyboardButton("🛒  Продукты", callback_data="products")],
        [InlineKeyboardButton("❤️  Предпочтения", callback_data="preferences")],
    ])


def replace_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🍳  Завтрак", callback_data="replace_breakfast")],
        [InlineKeyboardButton("🍗  Основное", callback_data="replace_main")],
        [InlineKeyboardButton("🥨  Закуска", callback_data="replace_snack")],
        [InlineKeyboardButton("🥦  Овощи", callback_data="replace_vegetables")],
        [InlineKeyboardButton("↩️  Назад", callback_data="main_menu")],
    ])


def products_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠  Что есть дома", callback_data="food_home")],
        [InlineKeyboardButton("✏️  Изменить продукты", callback_data="edit_food")],
        [InlineKeyboardButton("🧹  Очистить продукты дома", callback_data="clear_food_home")],
        [InlineKeyboardButton("↩️  Назад", callback_data="main_menu")],
    ])


def preferences_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧑  Марианна: изменить", callback_data="pref_marianna")],
        [InlineKeyboardButton("👨  Павел: изменить", callback_data="pref_pavel")],
        [InlineKeyboardButton("ℹ️  Информация о Марианне", callback_data="info_marianna")],
        [InlineKeyboardButton("ℹ️  Информация о Павле", callback_data="info_pavel")],
        [InlineKeyboardButton("⭐  Оценить блюдо", callback_data="rate_dish")],
        [InlineKeyboardButton("↩️  Назад", callback_data="main_menu")],
    ])


def back_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("↩️  Назад", callback_data="main_menu")]
    ])


# ============================================================
# SUPABASE — ЗАГРУЗКА / СОХРАНЕНИЕ
# ============================================================

def load_user_memory_sync(user_id, first_name):
    try:
        result = (
            supabase.table("bot_memory")
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
        log("SUPABASE LOAD ERROR:", repr(e))

    data = empty_memory()
    data["marianna"]["other"]["user_name"] = first_name
    return data


async def load_user_memory(user_id, first_name):
    return await asyncio.to_thread(load_user_memory_sync, user_id, first_name)


def save_user_memory_sync(user_id, memory_data):
    try:
        existing = (
            supabase.table("bot_memory")
            .select("id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )

        if existing.data:
            supabase.table("bot_memory").update(
                {"memory": memory_data}
            ).eq("user_id", user_id).execute()
        else:
            supabase.table("bot_memory").insert(
                {"user_id": user_id, "memory": memory_data}
            ).execute()

        log("MEMORY SAVED")

    except Exception as e:
        log("SUPABASE SAVE ERROR:", repr(e))


async def save_user_memory(user_id, memory_data):
    await asyncio.to_thread(save_user_memory_sync, user_id, memory_data)


# ============================================================
# МИГРАЦИЯ
# ============================================================

def migrate_memory(old_memory):
    new_memory = empty_memory()

    if "marianna" in old_memory or "pavel" in old_memory:
        for key in new_memory:
            if key in old_memory and isinstance(old_memory[key], dict):
                new_memory[key].update(old_memory[key])

        # Старые версии могли хранить menu_history как список полных
        # HTML-меню — это раздувало память. Если так, обнуляем историю
        # (сама она наберётся заново в компактном виде), но current_menu
        # сохраняем как есть.
        shared = new_memory.get("shared", {})
        history = shared.get("menu_history", [])
        if history and any(isinstance(item, str) for item in history):
            shared["menu_history"] = []
            new_memory["shared"] = shared

        return new_memory

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

    # Старую полную menu_history не переносим (могла быть огромной) —
    # она наберётся заново в компактном виде.

    return new_memory


# ============================================================
# НОРМАЛИЗАЦИЯ / СОВПАДЕНИЕ ТЕКСТА
# ============================================================

def normalize_text(value):
    if value is None:
        return ""
    value = str(value).lower().strip()
    value = value.replace("ё", "е")
    value = re.sub(r"\s+", " ", value)
    return value


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
# ПРОВЕРКА — НУЖНО ЛИ ОБРАЩАТЬСЯ К ПАМЯТИ
# ============================================================

MEMORY_WORDS = [
    "запомни", "запиши", "сохрани",
    "забудь", "удали", "удалить", "убери", "сотри", "очисти", "больше не храни",
    "купили", "купила", "купил", "покупаем",
    "есть дома", "дома есть", "осталось", "остался", "осталась", "остались",
    "закончился", "закончилась", "закончились", "закончилось",
    "понравилось", "понравился", "понравилась", "понравились",
    "не понравилось", "не понравился", "не понравилась", "не понравились",
    "люблю", "любит", "любим",
    "не люблю", "не любит", "не любим",
    "надоел", "надоела", "надоело", "надоели",
    "больше не хочу", "больше не хочет", "больше не хотим",
    "никогда не готовить", "больше никогда"
]


def should_check_memory(user_message):
    text = normalize_text(user_message)
    return any(word in text for word in MEMORY_WORDS)


# ============================================================
# УДАЛЕНИЕ БЛЮДА ИЗ СПИСКА / РЕКУРСИВНОЕ УДАЛЕНИЕ
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
            for key in ["dish", "name", "title", "meal", "recipe", "value"]:
                if key in item and text_matches(item[key], dish):
                    should_remove = True
                    break

        if not should_remove:
            result.append(item)

    return result


def remove_dish_recursive(value, dish):
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, str):
                if text_matches(item, dish):
                    continue
            elif isinstance(item, dict):
                object_matches = False
                for key in ["dish", "name", "title", "meal", "recipe"]:
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
            if text_matches(key, dish):
                continue
            result[key] = remove_dish_recursive(item, dish)
        return result

    return value


def delete_all_about_dish(memory_data, dish):
    shared = memory_data.get("shared", {})

    shared["liked_dishes"] = remove_dish_from_list(shared.get("liked_dishes", []), dish)
    shared["disliked_dishes"] = remove_dish_from_list(shared.get("disliked_dishes", []), dish)
    shared["dish_ratings"] = remove_dish_from_list(shared.get("dish_ratings", []), dish)

    if shared.get("current_menu") is not None:
        shared["current_menu"] = remove_dish_recursive(shared["current_menu"], dish)

    shared["menu_history"] = remove_dish_recursive(shared.get("menu_history", []), dish)

    for key in list(shared.keys()):
        if key in ["liked_dishes", "disliked_dishes", "dish_ratings", "current_menu", "menu_history"]:
            continue
        shared[key] = remove_dish_recursive(shared[key], dish)

    memory_data["shared"] = shared
    return memory_data


def update_dish_rating(memory_data, dish, person, rating):
    ratings = memory_data["shared"].get("dish_ratings", [])
    new_ratings = []

    for item in ratings:
        if not isinstance(item, dict):
            new_ratings.append(item)
            continue

        item_dish = item.get("dish") or item.get("name") or item.get("meal") or ""
        item_person = item.get("person")

        if text_matches(item_dish, dish) and item_person == person:
            continue

        new_ratings.append(item)

    new_ratings.append({"dish": dish, "person": person, "rating": rating})
    memory_data["shared"]["dish_ratings"] = new_ratings
    return memory_data


# ============================================================
# ПРИМЕНЕНИЕ ОПЕРАЦИЙ ПАМЯТИ
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

            if person not in ["marianna", "pavel", "shared"]:
                continue
            if not field:
                continue

            if person in ["marianna", "pavel"]:
                if field in ["height_cm", "weight_kg", "goal"]:
                    memory_data[person][field] = value
                else:
                    memory_data[person]["other"][field] = value

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
                    if isinstance(value, dict):
                        dish = value.get("dish")
                        person_value = value.get("person")
                        rating = value.get("rating")
                        if dish and person_value and rating:
                            memory_data = update_dish_rating(memory_data, dish, person_value, rating)

                elif field == "current_menu":
                    memory_data["shared"]["current_menu"] = value

                elif field == "menu_history":
                    # "add" — дополняем компактную историю.
                    # "update" — полностью заменяем (в т.ч. очистка value=[]).
                    if action == "update":
                        if isinstance(value, list):
                            memory_data["shared"]["menu_history"] = value[-MENU_HISTORY_LIMIT:]
                    else:
                        if isinstance(value, list):
                            history = memory_data["shared"].get("menu_history", [])
                            history.extend(value)
                            memory_data["shared"]["menu_history"] = history[-MENU_HISTORY_LIMIT:]

        # ====================================================
        # DELETE
        # ====================================================
        elif action == "delete":
            person = operation.get("person")
            field = operation.get("field")
            value = operation.get("value")

            if person not in ["marianna", "pavel", "shared"]:
                continue

            if person in ["marianna", "pavel"]:
                if field in ["height_cm", "weight_kg", "goal"]:
                    if value is None or memory_data[person].get(field) == value:
                        memory_data[person][field] = None
                else:
                    memory_data[person]["other"].pop(field, None)

            else:
                if field == "food_at_home":
                    food = memory_data["shared"].get("food_at_home", {})
                    if isinstance(food, dict):
                        keys_to_delete = [
                            key for key in food.keys()
                            if value and text_matches(key, value)
                        ]
                        for key in keys_to_delete:
                            del food[key]

                elif field == "liked_dishes":
                    memory_data["shared"]["liked_dishes"] = remove_dish_from_list(
                        memory_data["shared"].get("liked_dishes", []), value
                    )

                elif field == "disliked_dishes":
                    memory_data["shared"]["disliked_dishes"] = remove_dish_from_list(
                        memory_data["shared"].get("disliked_dishes", []), value
                    )

                elif field == "dish_rating":
                    memory_data["shared"]["dish_ratings"] = remove_dish_from_list(
                        memory_data["shared"].get("dish_ratings", []), value
                    )

                elif field == "menu_history":
                    memory_data["shared"]["menu_history"] = []

        # ====================================================
        # DELETE ALL DISH
        # ====================================================
        elif action == "delete_all_dish":
            dish = operation.get("dish")
            if dish:
                memory_data = delete_all_about_dish(memory_data, dish)

        # ====================================================
        # CLEAR FOOD
        # ====================================================
        elif action == "clear_food":
            memory_data["shared"]["food_at_home"] = {}

    return memory_data


# ============================================================
# OPENAI — ПАМЯТЬ
# ============================================================

def serialize_memory(memory_data):
    text = json.dumps(memory_data, ensure_ascii=False, separators=(",", ":"))
    if len(text) > MEMORY_CHAR_LIMIT:
        log("WARNING: MEMORY TOO LARGE:", len(text))
        text = text[:MEMORY_CHAR_LIMIT]
    return text


async def extract_memory_operations(user_message, current_memory):
    compact_memory = serialize_memory(current_memory)

    prompt = f"""
Ты — модуль управления постоянной памятью.

ТЕКУЩАЯ ПАМЯТЬ:
{compact_memory}

НОВОЕ СООБЩЕНИЕ:
{user_message}

Определи, нужно ли изменить постоянную память.

Верни ТОЛЬКО JSON.

Никакого Markdown.
Никаких пояснений.

Допустимые action:

add
update
delete
delete_all_dish
clear_food

Примеры:

Пользователь:
Вес Павла 68 кг. Запомни.

{{
  "operations": [
    {{"action": "update", "person": "pavel", "field": "weight_kg", "value": 68}}
  ]
}}

Пользователь:
Купили 2 кг куриного филе.

{{
  "operations": [
    {{"action": "add", "person": "shared", "field": "food_at_home", "value": {{"куриное филе": "2 кг"}}}}
  ]
}}

Пользователь:
Куриное филе закончилось.

{{
  "operations": [
    {{"action": "delete", "person": "shared", "field": "food_at_home", "value": "куриное филе"}}
  ]
}}

Пользователь:
Марианне понравилась запеканка.

{{
  "operations": [
    {{"action": "add", "person": "shared", "field": "dish_rating", "value": {{"dish": "запеканка", "person": "marianna", "rating": "like"}}}}
  ]
}}

Пользователь:
Запеканку больше никогда не готовить.

{{
  "operations": [
    {{"action": "add", "person": "shared", "field": "disliked_dishes", "value": ["запеканка"]}}
  ]
}}

Пользователь:
Удали всю информацию о запеканке.

{{
  "operations": [
    {{"action": "delete_all_dish", "dish": "запеканка"}}
  ]
}}

ВАЖНО:

Если пользователь использует:
- удали; удалить; забудь; убери; сотри; очисти; больше не храни;

это команда изменения памяти. Не сохраняй удаляемую информацию обратно.

Если пользователь просит очистить продукты дома — используй action "clear_food".

Если пользователь даёт новую оценку тому же блюду и человеку,
последняя оценка должна заменить предыдущую.

Не придумывай данные.

Если изменений нет:

{{"operations": []}}
"""

    text = await ask_openai(
        instructions="""
Ты — модуль управления памятью.

Возвращай только валидный JSON.
Без Markdown.
Без пояснений.
Не придумывай данные.
""",
        input_text=prompt,
        timeout=20,
        label="memory_extract"
    )

    if not text:
        return []

    try:
        text = text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)

        if not isinstance(data, dict):
            return []

        operations = data.get("operations", [])
        if not isinstance(operations, list):
            return []

        return operations

    except Exception as e:
        log("MEMORY JSON ERROR:", repr(e))
        return []


# ============================================================
# КОМПАКТНАЯ ИСТОРИЯ МЕНЮ (без хранения полного HTML)
# ============================================================

MENU_ITEM_LABELS = {
    "breakfast": "Завтрак Павла",
    "main": "Основное",
    "side": "Гарнир",
    "snack": "Закуска Марианны",
    "vegetables": "Овощи Павла",
}


def extract_menu_summary(html_text):
    """
    Достаёт только названия блюд из раздела "МЕНЮ НА 3 ДНЯ",
    не сохраняя весь HTML-текст меню. Используется для истории,
    чтобы блюда не повторялись, но память не раздувалась.
    """
    if not html_text:
        return {}

    summary = {}
    for key, label in MENU_ITEM_LABELS.items():
        pattern = re.escape(label) + r"</b>\s*\n+\s*([^\n<]+)"
        match = re.search(pattern, html_text)
        if match:
            dish = match.group(1).strip()
            if dish:
                summary[key] = dish

    return summary


def push_menu_to_history(memory_data, old_menu_html):
    """Сворачивает предыдущее меню в компактную запись истории."""
    if not old_menu_html:
        return

    summary = extract_menu_summary(old_menu_html)
    if not summary:
        return

    history = memory_data["shared"].get("menu_history", [])
    history.append(summary)
    memory_data["shared"]["menu_history"] = history[-MENU_HISTORY_LIMIT:]


# ============================================================
# ОПРЕДЕЛЕНИЕ ЗАМЕНЫ / НОВОГО МЕНЮ / ТЕКУЩЕГО МЕНЮ
# ============================================================

def detect_replacement_request(user_message):
    text = normalize_text(user_message)

    replacement_words = [
        "замени", "заменить", "поменяй", "поменять",
        "другой", "другое", "надоел", "надоела", "надоело"
    ]

    if not any(word in text for word in replacement_words):
        return None

    if "завтрак" in text or "завтрака" in text:
        return "breakfast"
    if "основное блюдо" in text or "основное" in text or "обед" in text:
        return "main"
    if "закуск" in text or "хрустящ" in text:
        return "marianna_snack"
    if "овощ" in text or "овощное дополнение" in text:
        return "pavel_vegetables"

    return None


def is_new_menu_request(user_message):
    text = normalize_text(user_message)

    phrases = [
        "новое меню", "составь новое меню", "давай новое меню",
        "сделай новое меню", "придумай новое меню", "меню на 3 дня",
        "новый цикл"
    ]

    return any(phrase in text for phrase in phrases)


def is_current_menu_request(user_message):
    text = normalize_text(user_message)

    phrases = [
        "что есть сегодня", "что у нас сегодня", "какое меню сегодня",
        "что кушать сегодня", "что покушать сегодня", "текущее меню"
    ]

    return any(phrase in text for phrase in phrases)


# ============================================================
# ГЕНЕРАЦИЯ НОВОГО МЕНЮ
# ============================================================

async def generate_new_menu(message, user_id, memory_data):
    """
    Общая функция создания нового меню на 3 дня.
    Используется и из команды в чате, и из кнопки — без дублирования кода.
    """

    memory_context = serialize_memory(memory_data)

    prompt = f"""
ПОСТОЯННАЯ ПАМЯТЬ ПОЛЬЗОВАТЕЛЯ:

{memory_context}

ПОЛЬЗОВАТЕЛЬ ПРОСИТ СОСТАВИТЬ НОВОЕ МЕНЮ НА 3 ДНЯ.

Составь полное новое меню на 3 дня.

Обязательно:
- учитывай память;
- учитывай продукты дома;
- учитывай предпочтения;
- учитывай оценки;
- учитывай историю меню;
- не повторяй недавно использованные основные блюда без необходимости;
- соблюдай все ограничения Марианны;
- учитывай цель Павла;
- минимизируй количество готовки.

После создания меню оно станет текущим меню.

Отвечай сразу готовым меню на русском языке.
"""

    answer = await ask_openai(instructions=SYSTEM_PROMPT, input_text=prompt, timeout=75, label="new_menu")

    if not answer:
        await message.reply_text(
            "ИИ слишком долго отвечает 😔\n"
            "Попробуй ещё раз через несколько секунд.",
            reply_markup=main_keyboard()
        )
        return

    old_menu = memory_data["shared"].get("current_menu")
    push_menu_to_history(memory_data, old_menu)
    memory_data["shared"]["current_menu"] = answer

    await save_user_memory(user_id, memory_data)
    log("NEW MENU SAVED AS CURRENT MENU")

    await send_long_message(message, answer, reply_markup=main_keyboard())


# ============================================================
# ЗАМЕНА ОДНОГО ЭЛЕМЕНТА
# ============================================================

async def replace_single_menu_item(current_menu, user_message, replacement_type, memory_data):
    if not current_menu:
        return None

    memory_context = serialize_memory(memory_data)

    type_names = {
        "breakfast": "ЗАВТРАК ПАВЛА",
        "main": "ОСНОВНОЕ БЛЮДО",
        "marianna_snack": "ХРУСТЯЩАЯ ЗАКУСКА МАРИАННЫ",
        "pavel_vegetables": "ОВОЩНОЕ ДОПОЛНЕНИЕ ПАВЛА"
    }

    target_name = type_names[replacement_type]

    prompt = f"""
У нас уже есть текущее меню на 3 дня.

ТЕКУЩЕЕ МЕНЮ:
{current_menu}

ПАМЯТЬ:
{memory_context}

ЗАПРОС ПОЛЬЗОВАТЕЛЯ:
{user_message}

Пользователь хочет заменить только:

{target_name}

КРИТИЧЕСКИ ВАЖНО:

НЕ создавай новое меню с нуля.

Сохрани без изменений:
- остальные блюда;
- остальные элементы меню;
- количество дней;
- общую структуру.

Замени ТОЛЬКО указанный элемент.

Если пользователь предложил конкретное блюдо, используй именно его.
Если конкретное блюдо не указано, сам выбери подходящую замену с учётом памяти.

При выборе учитывай:
- ограничения Марианны;
- вес и цель Павла;
- продукты дома;
- предпочтения;
- оценки;
- нелюбимые блюда;
- блюда, которые нельзя повторять.

После замены обязательно пересчитай:
- ингредиенты;
- количество приготовления;
- дневные порции;
- КБЖУ;
- список покупок.

Покажи полное обновлённое меню целиком.

Отвечай на русском языке.
"""

    return await ask_openai(instructions=SYSTEM_PROMPT, input_text=prompt, timeout=75, label="replace_item")


# ============================================================
# ДЛИННЫЕ TELEGRAM СООБЩЕНИЯ
# ============================================================

async def send_long_message(message, text, reply_markup=None):
    max_length = 3900
    parse_mode = "HTML"

    if len(text) <= max_length:
        await message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
        return

    while len(text) > max_length:
        cut = text.rfind("</blockquote>", 0, max_length)

        if cut > 500:
            cut = cut + len("</blockquote>")
        else:
            cut = text.rfind("\n\n", 0, max_length)
            if cut < 1000:
                cut = text.rfind("\n", 0, max_length)
            if cut < 1000:
                cut = max_length

        part = text[:cut]
        await message.reply_text(part, parse_mode=parse_mode)
        text = text[cut:].lstrip()

    if text:
        await message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)


# ============================================================
# ЛОКАЛЬНОЕ ФОРМАТИРОВАНИЕ (без обращения к модели)
# ============================================================

def format_food_at_home(food):
    if not food:
        return "🏠 Сейчас в списке продуктов дома ничего нет."

    lines = ["🏠 <b>Что есть дома:</b>", ""]
    for name, amount in food.items():
        lines.append(f"• {name}: {amount}")

    return "\n".join(lines)


RATING_LABELS = {
    "like": "❤️ нравится",
    "dislike": "😐 не нравится",
    "never": "🚫 больше не готовить",
}


def format_person_info(memory_data, person_key, person_label):
    person = memory_data.get(person_key, {})
    shared = memory_data.get("shared", {})

    lines = [f"ℹ️ <b>Информация о {person_label}</b>", ""]

    height = person.get("height_cm")
    weight = person.get("weight_kg")
    goal = person.get("goal")

    lines.append(f"Рост: {height if height is not None else 'не указан'} см")
    lines.append(f"Вес: {weight if weight is not None else 'не указан'} кг")
    lines.append(f"Цель: {goal if goal else 'не указана'}")

    other = person.get("other", {})
    other = {k: v for k, v in other.items() if k != "user_name"}

    if other:
        lines.append("")
        lines.append("<b>Дополнительно:</b>")
        for key, value in other.items():
            lines.append(f"• {key}: {value}")

    ratings = [
        r for r in shared.get("dish_ratings", [])
        if isinstance(r, dict) and r.get("person") == person_key
    ]

    if ratings:
        lines.append("")
        lines.append("<b>Оценки блюд:</b>")
        for r in ratings:
            dish = r.get("dish", "?")
            rating_label = RATING_LABELS.get(r.get("rating"), r.get("rating", ""))
            lines.append(f"• {dish} — {rating_label}")

    liked = shared.get("liked_dishes", [])
    disliked = shared.get("disliked_dishes", [])

    if liked:
        lines.append("")
        lines.append("<b>Понравившиеся блюда (общие):</b>")
        for item in liked:
            name = item if isinstance(item, str) else item.get("dish", item.get("name", str(item)))
            lines.append(f"• {name}")

    if disliked:
        lines.append("")
        lines.append("<b>Блюда, которые нельзя повторять (общие):</b>")
        for item in disliked:
            name = item if isinstance(item, str) else item.get("dish", item.get("name", str(item)))
            lines.append(f"• {name}")

    return "\n".join(lines)


# ============================================================
# START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("replacement_type", None)
    context.user_data.pop("awaiting_input", None)

    await update.message.reply_text(
        "Привет! 🍽️\n\n"
        "Я помощник Марианны и Павла по меню.\n\n"
        "Выбирай нужное действие:",
        reply_markup=main_keyboard()
    )


# ============================================================
# CALLBACK — КНОПКИ
# ============================================================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await _button_handler_impl(update, context)
    except Exception as e:
        log("UNHANDLED BUTTON ERROR:", repr(e))
        log(traceback.format_exc())

        try:
            if update.callback_query and update.callback_query.message:
                await update.callback_query.message.reply_text(
                    "Что-то пошло не так на моей стороне 😔\n\nПопробуй ещё раз.",
                    reply_markup=main_keyboard()
                )
        except Exception as inner_e:
            log("FAILED TO SEND ERROR MESSAGE:", repr(inner_e))


async def _button_handler_impl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = str(update.effective_user.id)

    # ========================================================
    # ГЛАВНОЕ МЕНЮ
    # ========================================================
    if data == "main_menu":
        context.user_data.pop("replacement_type", None)
        context.user_data.pop("awaiting_input", None)

        await query.edit_message_text(
            "🍽️ <b>Главное меню</b>\n\nЧто будем делать?",
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )
        return

    # ========================================================
    # НОВОЕ МЕНЮ
    # ========================================================
    if data == "new_menu":
        context.user_data.pop("replacement_type", None)
        context.user_data.pop("awaiting_input", None)

        memory_data = await load_user_memory(user_id, update.effective_user.first_name)

        await query.edit_message_text("🆕 <b>Новое меню на 3 дня</b>\n\nСоставляю меню...", parse_mode="HTML")

        await generate_new_menu(query.message, user_id, memory_data)
        return

    # ========================================================
    # ЗАМЕНА БЛЮДА — МЕНЮ ВЫБОРА
    # ========================================================
    if data == "replace_menu":
        await query.edit_message_text(
            "🔄 <b>Что заменить?</b>\n\nВыбери только один элемент текущего меню:",
            parse_mode="HTML",
            reply_markup=replace_keyboard()
        )
        return

    replacement_map = {
        "replace_breakfast": ("breakfast", "🍳 Завтрак Павла"),
        "replace_main": ("main", "🍗 Основное блюдо"),
        "replace_snack": ("marianna_snack", "🥨 Закуска Марианны"),
        "replace_vegetables": ("pavel_vegetables", "🥦 Овощи Павла")
    }

    if data in replacement_map:
        replacement_type, title = replacement_map[data]

        memory_data = await load_user_memory(user_id, update.effective_user.first_name)
        current_menu = memory_data["shared"].get("current_menu")

        if not current_menu:
            await query.edit_message_text(
                "У нас сейчас нет сохранённого текущего меню 😔\n\nСначала создай новое меню.",
                reply_markup=main_keyboard()
            )
            return

        context.user_data["replacement_type"] = replacement_type
        context.user_data["awaiting_input"] = "replacement"

        await query.edit_message_text(
            f"{title}\n\n"
            "Напиши, на что заменить.\n\n"
            "Например:\n"
            "• «на сырники»\n"
            "• «на куриные котлеты»\n"
            "• «давай другой»\n\n"
            "Если конкретное блюдо не укажешь — я сама выберу подходящее.",
            reply_markup=back_keyboard()
        )
        return

    # ========================================================
    # ПРОДУКТЫ
    # ========================================================
    if data == "products":
        await query.edit_message_text(
            "🛒 <b>Продукты</b>\n\nЧто хочешь сделать?",
            parse_mode="HTML",
            reply_markup=products_keyboard()
        )
        return

    if data == "food_home":
        memory_data = await load_user_memory(user_id, update.effective_user.first_name)
        food = memory_data["shared"].get("food_at_home", {})

        await query.edit_message_text(
            format_food_at_home(food),
            parse_mode="HTML",
            reply_markup=products_keyboard()
        )
        return

    if data == "edit_food":
        context.user_data["awaiting_input"] = "food"

        await query.edit_message_text(
            "✏️ <b>Изменить продукты</b>\n\n"
            "Просто напиши, что изменилось.\n\n"
            "Например:\n"
            "• «Купили 2 кг куриного филе»\n"
            "• «Купили яйца и сыр»\n"
            "• «Куриное филе закончилось»\n"
            "• «Осталось 500 г сыра»\n\n"
            "Я обновлю продукты в памяти.",
            parse_mode="HTML",
            reply_markup=back_keyboard()
        )
        return

    if data == "clear_food_home":
        memory_data = await load_user_memory(user_id, update.effective_user.first_name)
        memory_data["shared"]["food_at_home"] = {}
        await save_user_memory(user_id, memory_data)

        await query.edit_message_text(
            "🧹 Список продуктов дома очищен.",
            parse_mode="HTML",
            reply_markup=products_keyboard()
        )
        return

    # ========================================================
    # ПРЕДПОЧТЕНИЯ
    # ========================================================
    if data == "preferences":
        await query.edit_message_text(
            "❤️ <b>Предпочтения</b>\n\nЧто хочешь сделать?",
            parse_mode="HTML",
            reply_markup=preferences_keyboard()
        )
        return

    if data == "pref_marianna":
        context.user_data["awaiting_input"] = "marianna_preferences"

        await query.edit_message_text(
            "🧑 <b>Предпочтения Марианны</b>\n\n"
            "Напиши, что хочешь добавить, изменить или удалить.\n\n"
            "Например:\n"
            "• «Марианне нравится лазанья»\n"
            "• «Марианна больше не хочет есть сырники»\n"
            "• «Забудь, что Марианне нравится лазанья»",
            parse_mode="HTML",
            reply_markup=back_keyboard()
        )
        return

    if data == "pref_pavel":
        context.user_data["awaiting_input"] = "pavel_preferences"

        await query.edit_message_text(
            "👨 <b>Предпочтения Павла</b>\n\n"
            "Напиши, что хочешь добавить, изменить или удалить.\n\n"
            "Например:\n"
            "• «Павлу нравится паста»\n"
            "• «Павел не любит жирные соусы»\n"
            "• «Забудь, что Павел любит рис»",
            parse_mode="HTML",
            reply_markup=back_keyboard()
        )
        return

    if data == "info_marianna":
        memory_data = await load_user_memory(user_id, update.effective_user.first_name)

        await query.edit_message_text(
            format_person_info(memory_data, "marianna", "Марианне"),
            parse_mode="HTML",
            reply_markup=preferences_keyboard()
        )
        return

    if data == "info_pavel":
        memory_data = await load_user_memory(user_id, update.effective_user.first_name)

        await query.edit_message_text(
            format_person_info(memory_data, "pavel", "Павле"),
            parse_mode="HTML",
            reply_markup=preferences_keyboard()
        )
        return

    if data == "rate_dish":
        context.user_data["awaiting_input"] = "rating"

        await query.edit_message_text(
            "⭐ <b>Оценить блюдо</b>\n\n"
            "Напиши, кто и как оценил блюдо.\n\n"
            "Например:\n"
            "❤️ «Марианне очень понравились сырники»\n"
            "😐 «Марианне не понравились котлеты»\n"
            "🚫 «Павлу больше никогда не готовить пасту»\n\n"
            "Последняя оценка будет заменять предыдущую.",
            parse_mode="HTML",
            reply_markup=back_keyboard()
        )
        return


# ============================================================
# ЛОКАЛЬНЫЕ ВЕТКИ БЕЗ ВТОРОГО ВЫЗОВА GPT
# (продукты / предпочтения / оценка — быстрый путь)
# ============================================================

QUICK_STATES = {"food", "marianna_preferences", "pavel_preferences", "rating"}


async def handle_quick_memory_state(update, context, user_id, memory_data, state, user_message):
    """
    Для веток "Изменить продукты", "Предпочтения Марианны/Павла", "Оценить блюдо"
    не нужен основной GPT-вызов на генерацию текста — нужно только
    распознать и применить изменение памяти, а затем коротко подтвердить.
    Это убирает один из двух последовательных вызовов модели и ускоряет ответ.
    """

    operations = await extract_memory_operations(user_message, memory_data)
    log("MEMORY OPERATIONS (quick):", operations)

    if operations:
        memory_data = apply_memory_updates(memory_data, operations)
        await save_user_memory(user_id, memory_data)

    context.user_data.pop("awaiting_input", None)

    if state == "food":
        food = memory_data["shared"].get("food_at_home", {})
        text = "✅ Обновила продукты дома.\n\n" + format_food_at_home(food)
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=products_keyboard())
        return

    if state == "marianna_preferences":
        text = "✅ Записала.\n\n" + format_person_info(memory_data, "marianna", "Марианне")
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=preferences_keyboard())
        return

    if state == "pavel_preferences":
        text = "✅ Записала.\n\n" + format_person_info(memory_data, "pavel", "Павле")
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=preferences_keyboard())
        return

    if state == "rating":
        await update.message.reply_text(
            "✅ Записала оценку. Учту её в следующих меню.",
            reply_markup=preferences_keyboard()
        )
        return


# ============================================================
# ОСНОВНОЙ ЧАТ
# ============================================================

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Тонкая обёртка: гарантирует, что ЛЮБАЯ непойманная ошибка внутри
    _chat_impl попадёт в лог (с трейсбеком) и пользователь получит
    понятный ответ вместо бесконечного "висения" без единой строки в логах.
    """
    try:
        await _chat_impl(update, context)
    except Exception as e:
        log("UNHANDLED CHAT ERROR:", repr(e))
        log(traceback.format_exc())

        try:
            if update.message:
                await update.message.reply_text(
                    "Что-то пошло не так на моей стороне 😔\n\nПопробуй ещё раз.",
                    reply_markup=main_keyboard()
                )
        except Exception as inner_e:
            log("FAILED TO SEND ERROR MESSAGE:", repr(inner_e))


async def _chat_impl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = str(update.effective_user.id)
    user_message = update.message.text.strip()

    log("MESSAGE:", user_message)

    replacement_type_from_button = context.user_data.get("replacement_type")
    awaiting_input = context.user_data.get("awaiting_input")

    memory_data = await load_user_memory(user_id, update.effective_user.first_name)

    # ========================================================
    # Быстрый путь: продукты / предпочтения / оценка блюда —
    # без основного GPT-вызова, только извлечение/применение памяти.
    # ========================================================
    if awaiting_input in QUICK_STATES and not replacement_type_from_button:
        await handle_quick_memory_state(update, context, user_id, memory_data, awaiting_input, user_message)
        return

    # ========================================================
    # Замена одного блюда после нажатия кнопки
    # ========================================================
    if replacement_type_from_button:
        current_menu = memory_data["shared"].get("current_menu")

        if not current_menu:
            context.user_data.pop("replacement_type", None)
            context.user_data.pop("awaiting_input", None)

            await update.message.reply_text(
                "У нас сейчас нет сохранённого текущего меню 😔\n\nСначала создай новое меню.",
                reply_markup=main_keyboard()
            )
            return

        await update.message.reply_text("🔄 Хорошо, заменяю только это блюдо...")

        updated_menu = await replace_single_menu_item(
            current_menu, user_message, replacement_type_from_button, memory_data
        )

        context.user_data.pop("replacement_type", None)
        context.user_data.pop("awaiting_input", None)

        if updated_menu:
            push_menu_to_history(memory_data, current_menu)
            memory_data["shared"]["current_menu"] = updated_menu

            await save_user_memory(user_id, memory_data)
            log("CURRENT MENU UPDATED")

            await send_long_message(update.message, updated_menu, reply_markup=main_keyboard())
        else:
            await update.message.reply_text(
                "Не получилось заменить блюдо 😔\n\nПопробуй ещё раз.",
                reply_markup=main_keyboard()
            )
        return

    # ========================================================
    # Заранее определяем, какая ветка сработает дальше.
    # Это нужно, чтобы понять, можно ли безопасно распараллелить
    # вызов "распознать изменение памяти" с основным вызовом,
    # или лучше сделать их строго последовательно (когда branch
    # сам делает отдельный, специализированный вызов к модели).
    # ========================================================
    wants_current_menu = is_current_menu_request(user_message)
    wants_replacement = detect_replacement_request(user_message)
    wants_new_menu = is_new_menu_request(user_message)

    is_generic_branch = not (wants_current_menu or wants_replacement or wants_new_menu)
    needs_memory_check = should_check_memory(user_message)

    # ========================================================
    # ОБЩАЯ ВЕТКА + нужна проверка памяти → распараллеливаем
    # два вызова к модели вместо последовательного (30+90 → ~90 сек).
    # ========================================================
    if is_generic_branch and needs_memory_check:
        memory_context = serialize_memory(memory_data)

        prompt = f"""
ПОСТОЯННАЯ ПАМЯТЬ ПОЛЬЗОВАТЕЛЯ:

{memory_context}

СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ:

{user_message}

============================================================

Используй память как источник фактов.
Учитывай также сам текст сообщения пользователя выше — если в нём
есть новая информация (например, про продукты дома или предпочтения),
она уже актуальна, даже если ещё не зафиксирована в блоке памяти.

ВАЖНО:

- не спрашивай повторно то, что уже известно;
- данные Марианны и Павла не смешивай;
- если пользователь спрашивает конкретное сохранённое значение, ответь непосредственно;
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

        memory_task = asyncio.create_task(extract_memory_operations(user_message, memory_data))
        answer_task = asyncio.create_task(
            ask_openai(instructions=SYSTEM_PROMPT, input_text=prompt, timeout=75, label="generic_parallel")
        )

        operations, answer = await asyncio.gather(memory_task, answer_task)

        log("MEMORY OPERATIONS (parallel):", operations)

        if operations:
            memory_data = apply_memory_updates(memory_data, operations)
            await save_user_memory(user_id, memory_data)

        if not answer:
            await update.message.reply_text(
                "ИИ слишком долго отвечает 😔\n\nПопробуй ещё раз через несколько секунд.",
                reply_markup=main_keyboard()
            )
            return

        context.user_data.pop("awaiting_input", None)

        await send_long_message(update.message, answer, reply_markup=main_keyboard())
        log("TELEGRAM RESPONSE SENT")
        return

    # ========================================================
    # Память (для веток замены/нового меню/текущего меню —
    # применяем последовательно, до их собственного вызова к модели)
    # ========================================================
    if needs_memory_check:
        operations = await extract_memory_operations(user_message, memory_data)
        log("MEMORY OPERATIONS:", operations)

        if operations:
            memory_data = apply_memory_updates(memory_data, operations)
            await save_user_memory(user_id, memory_data)

    # ========================================================
    # Спрашивают текущее меню
    # ========================================================
    if is_current_menu_request(user_message):
        current_menu = memory_data["shared"].get("current_menu")

        if current_menu:
            await send_long_message(update.message, current_menu, reply_markup=main_keyboard())
        else:
            await update.message.reply_text(
                "Сейчас сохранённого меню нет 🍽️\n\n"
                "Нажми «🆕 Новое меню на 3 дня», и я составлю новое.",
                reply_markup=main_keyboard()
            )
        return

    # ========================================================
    # Обычная текстовая замена (без кнопки)
    # ========================================================
    replacement_type = detect_replacement_request(user_message)

    if replacement_type:
        current_menu = memory_data["shared"].get("current_menu")

        if not current_menu:
            await update.message.reply_text(
                "У нас сейчас нет сохранённого текущего меню, поэтому мне нечего заменять 😔\n\n"
                "Нажми «🆕 Новое меню на 3 дня».",
                reply_markup=main_keyboard()
            )
            return

        await update.message.reply_text("🔄 Хорошо, заменяю только это блюдо и сохраняю остальные элементы меню...")

        updated_menu = await replace_single_menu_item(current_menu, user_message, replacement_type, memory_data)

        if updated_menu:
            push_menu_to_history(memory_data, current_menu)
            memory_data["shared"]["current_menu"] = updated_menu

            await save_user_memory(user_id, memory_data)
            log("CURRENT MENU UPDATED")

            await send_long_message(update.message, updated_menu, reply_markup=main_keyboard())
        else:
            await update.message.reply_text(
                "Не получилось заменить блюдо 😔\n"
                "Попробуй написать, например: «Замени завтрак на сырники».",
                reply_markup=main_keyboard()
            )
        return

    # ========================================================
    # Новое меню одной фразой в чате
    # ========================================================
    if is_new_menu_request(user_message):
        await generate_new_menu(update.message, user_id, memory_data)
        context.user_data.pop("awaiting_input", None)
        return

    # ========================================================
    # Обычный запрос — основной GPT
    # ========================================================
    memory_context = serialize_memory(memory_data)

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
- если пользователь спрашивает конкретное сохранённое значение, ответь непосредственно;
- если пользователь просит новое меню — сразу составляй его;
- учитывай продукты дома;
- учитывай предпочтения;
- учитывай оценки;
- учитывай историю меню;
- не придумывай отсутствующие данные.

Если пользователь только что попросил удалить информацию,
не утверждай, что она всё ещё существует в памяти.

Если пользователь просит новое меню,
после создания полного меню оно должно считаться новым текущим меню.

Если информации действительно не хватает для выполнения задачи,
задай только необходимый вопрос.
"""

    answer = await ask_openai(instructions=SYSTEM_PROMPT, input_text=prompt, timeout=75, label="generic_only")

    if not answer:
        await update.message.reply_text(
            "ИИ слишком долго отвечает 😔\n\nПопробуй ещё раз через несколько секунд.",
            reply_markup=main_keyboard()
        )
        return

    context.user_data.pop("awaiting_input", None)

    try:
        await send_long_message(update.message, answer, reply_markup=main_keyboard())
        log("TELEGRAM RESPONSE SENT")
    except Exception as e:
        log("TELEGRAM ERROR:", repr(e))


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

async def global_error_handler(update, context: ContextTypes.DEFAULT_TYPE):
    """
    Ловит любые исключения, не пойманные внутри обработчиков (включая
    button_handler), чтобы они точно попадали в лог, а не терялись молча.
    """
    log("GLOBAL TELEGRAM ERROR:", repr(context.error))
    log("".join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__)))


async def run_bot():
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    application.add_error_handler(global_error_handler)

    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    log("Telegram bot started!")
    await asyncio.Event().wait()


# ============================================================
# MAIN
# ============================================================

async def main():
    asyncio.create_task(run_bot())

    from hypercorn.asyncio import serve
    from hypercorn.config import Config

    config = Config()
    config.bind = [f"0.0.0.0:{os.environ.get('PORT', '10000')}"]

    await serve(app, config)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())
