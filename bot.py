import os
import asyncio
import json
import re
import time

from flask import Flask
from openai import OpenAI
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

client = OpenAI(
    api_key=OPENAI_API_KEY,
    timeout=60.0
)

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


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

Всё необходимое по возможности готовится один раз в первый день.

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

Это очень важно.

Если пользователь просит заменить ОДНО блюдо в текущем меню,
НЕ создавай полностью новый цикл с другими блюдами.

Нужно:
1. взять текущее меню из памяти;
2. определить конкретный элемент, который пользователь хочет заменить;
3. заменить только этот элемент;
4. сохранить все остальные блюда без изменений;
5. пересчитать порции, КБЖУ и список покупок;
6. сохранить обновлённое меню как текущий цикл.

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
остальные элементы цикла сохранить.

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

создай полный новый 3-дневный цикл.

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
скажи, что текущего цикла пока нет, и предложи создать новое.

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
5. 📦 ЧТО ПРИГОТОВИТЬ В ДЕНЬ 1

============================================================
TELEGRAM HTML
============================================================

Меню будет отображаться в Telegram.

ОБЯЗАТЕЛЬНО используй HTML-форматирование Telegram.

Разрешены:
<b>жирный</b>
<i>курсив</i>
<u>подчёркивание</u>

Не используй Markdown для жирного текста.

НЕ пиши:
**жирный текст**

Пиши:
<b>жирный текст</b>

Заголовки разделов всегда выделяй жирным:

<b>🍽️ МЕНЮ НА 3 ДНЯ</b>
<b>🛒 ПОКУПКИ НА 3 ДНЯ</b>
<b>👨‍🍳 ПРИГОТОВЛЕНИЕ</b>
<b>⚖️ ПОРЦИИ И КБЖУ</b>
<b>📦 ЧТО ПРИГОТОВИТЬ В ДЕНЬ 1</b>

Имена людей:

🧑🏾‍🦱 <b>Марианна</b>
👨 <b>Павел</b>

Названия блюд можно выделять <b>жирным</b>.

Для важных итогов используй <b>жирный</b>.

Не используй Markdown-таблицы.

Не используй тройные обратные кавычки.

Не используй другие HTML-теги, кроме b, i и u.

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

Используй формат:

<b>🛒 ПОКУПКИ НА 3 ДНЯ</b>

🥩 <b>Мясо и рыба</b>
• ...

🥛 <b>Молочное и яйца</b>
• ...

🥔 <b>Овощи и корнеплоды</b>
• ...

🥖 <b>Хлеб и выпечка</b>
• ...

🥣 <b>Крупы и бакалея</b>
• ...

🥫 <b>Масла, специи и соусы</b>
• ...

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

Это необходимо для того, чтобы было понятно, сколько именно приготовить
на весь цикл.

Каждое блюдо оформляй как отдельный компактный блок.

Используй формат:

<b>👨‍🍳 ПРИГОТОВЛЕНИЕ</b>

🍳 <b>Завтрак Павла</b>

<b>Ингредиенты:</b>
• ...
• ...

<b>Как готовить:</b>
1. ...
2. ...
3. ...

🍗 <b>Основное</b>

<b>Ингредиенты:</b>
• ...
• ...

<b>Как готовить:</b>
1. ...
2. ...
3. ...

🥔 <b>Гарнир</b>

<b>Ингредиенты:</b>
• ...
• ...

<b>Как готовить:</b>
1. ...
2. ...
3. ...

🥨 <b>Закуска Марианны</b>

<b>Ингредиенты:</b>
• ...
• ...

<b>Как готовить:</b>
1. ...
2. ...

🥦 <b>Овощи Павла</b>

<b>Ингредиенты:</b>
• ...
• ...

<b>Как готовить:</b>
1. ...
2. ...

Для каждого блюда указывай количество ингредиентов,
необходимое для приготовления ВСЕГО объёма на 3 дня.

Не описывай приготовление отдельно для каждого дня.

Всё необходимое по возможности готовится в День 1.

НЕ добавляй:
- контейнеры;
- раскладывание по контейнерам;
- разложить по порциям;
- упаковку еды;
- инструкции по хранению;
- инструкции по разогреву;
- температуру и время разогрева в следующие дни.


============================================================
4. ⚖️ ПОРЦИИ И КБЖУ
============================================================

Раздел обязательно разделяй отдельно для Марианны и Павла.

Для каждого человека указывай только те блюда, которые он действительно ест.

Используй формат:

<b>⚖️ ПОРЦИИ И КБЖУ</b>

🧑🏾‍🦱 <b>Марианна</b>

🍗 <b>Основное</b>
[размер порции] — [ккал]
Б [г] / Ж [г] / У [г]

🥔 <b>Гарнир</b>
[размер порции] — [ккал]
Б [г] / Ж [г] / У [г]

🥨 <b>Закуска</b>
[размер порции] — [ккал]
Б [г] / Ж [г] / У [г]

<b>🔥 Итого за день</b>
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

<b>🔥 Итого за день</b>
[ккал]
Б [г] / Ж [г] / У [г]

КБЖУ рассчитывай арифметически по фактическому количеству ингредиентов.

Не придумывай произвольные КБЖУ.

Размер порции должен соответствовать рассчитанному количеству продукта.

Если блюдо разделяется между Марианной и Павлом,
учитывай фактическую долю каждого человека.


============================================================
5. 📦 ЧТО ПРИГОТОВИТЬ В ДЕНЬ 1
============================================================

В конце каждого полного меню обязательно добавляй:

<b>📦 ЧТО ПРИГОТОВИТЬ В ДЕНЬ 1</b>

Коротко перечисли ВСЁ, что необходимо приготовить или подготовить заранее
на все 3 дня.

Например:

<b>📦 ЧТО ПРИГОТОВИТЬ В ДЕНЬ 1</b>

• Курица — 900 г готового блюда
• Картофель — 750 г готового
• Брокколи — 450 г
• Сырники — 3 порции
• Закуска Марианны — 3 порции

Если какой-либо элемент не требует приготовления,
всё равно укажи его.

Например:

• Хлебцы — 3 дневные порции
• Творожный сыр — 3 дневные порции

НЕ пиши:
- контейнеры;
- разложить по контейнерам;
- разложить по порциям;
- хранение;
- разогрев;
- «В Дни 2–3 только достать и разогреть».


============================================================
ОБЩИЕ ПРАВИЛА ФОРМАТА
============================================================

Если создаётся полное меню, ВСЕГДА используй именно этот порядок:

🍽️ МЕНЮ НА 3 ДНЯ

🛒 ПОКУПКИ НА 3 ДНЯ

👨‍🍳 ПРИГОТОВЛЕНИЕ

⚖️ ПОРЦИИ И КБЖУ

📦 ЧТО ПРИГОТОВИТЬ В ДЕНЬ 1

Не меняй порядок разделов.

Не добавляй перед меню длинные вступления.

Не добавляй после меню заключения вроде:
«Приятного аппетита!»
«Если хочешь, могу...»
«Вот готовое меню...»

Если пользователь просит именно меню — сразу начинай с:

<b>🍽️ МЕНЮ НА 3 ДНЯ</b>

Каждый раздел должен быть компактным и легко читаемым в Telegram.

Не используй Markdown-таблицы.

Не заключай весь ответ в тройные обратные кавычки.

Не используй отдельные блоки кода для разделов.

Используй обычный текст и списки.

При замене одного блюда сохраняй эту же структуру полного меню,
но изменяй ТОЛЬКО запрошенный элемент.


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
# КЛАВИАТУРЫ
# ============================================================

def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🆕  Новый цикл на 3 дня",
                callback_data="new_cycle"
            )
        ],
        [
            InlineKeyboardButton(
                "🔄  Заменить блюдо",
                callback_data="replace_menu"
            )
        ],
        [
            InlineKeyboardButton(
                "🛒  Продукты",
                callback_data="products"
            )
        ],
        [
            InlineKeyboardButton(
                "❤️  Предпочтения",
                callback_data="preferences"
            ),
        ],
    ])


def replace_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🍳  Завтрак",
                callback_data="replace_breakfast"
            )
        ],
        [
            InlineKeyboardButton(
                "🍗  Основное",
                callback_data="replace_main"
            )
        ],
        [
            InlineKeyboardButton(
                "🥨  Закуска",
                callback_data="replace_snack"
            )
        ],
        [
            InlineKeyboardButton(
                "🥦  Овощи",
                callback_data="replace_vegetables"
            )
        ],
        [
            InlineKeyboardButton(
                "↩️  Назад",
                callback_data="main_menu"
            )
        ],
    ])


def products_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🏠  Что есть дома",
                callback_data="food_home"
            )
        ],
        [
            InlineKeyboardButton(
                "✏️  Изменить продукты",
                callback_data="edit_food"
            )
        ],
        [
            InlineKeyboardButton(
                "↩️  Назад",
                callback_data="main_menu"
            )
        ],
    ])


def preferences_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🧑🏾‍🦱  Марианна",
                callback_data="pref_marianna"
            )
        ],
        [
            InlineKeyboardButton(
                "👨  Павел",
                callback_data="pref_pavel"
            )
        ],
        [
            InlineKeyboardButton(
                "⭐  Оценить блюдо",
                callback_data="rate_dish"
            )
        ],
        [
            InlineKeyboardButton(
                "↩️  Назад",
                callback_data="main_menu"
            )
        ],
    ])


def back_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "↩️  Назад",
                callback_data="main_menu"
            )
        ]
    ])


# ============================================================
# РАЗДЕЛЫ МЕНЮ
# ============================================================

MENU_SECTIONS = {
    "shopping": {
        "title": "🛒 Покупки на 3 дня",
        "heading": "🛒 ПОКУПКИ НА 3 ДНЯ",
        "button": "🛒 Покупки на 3 дня"
    },
    "cooking": {
        "title": "👨‍🍳 Приготовление",
        "heading": "👨‍🍳 ПРИГОТОВЛЕНИЕ",
        "button": "👨‍🍳 Приготовление"
    },
    "nutrition": {
        "title": "⚖️ Порции и КБЖУ",
        "heading": "⚖️ ПОРЦИИ И КБЖУ",
        "button": "⚖️ Порции и КБЖУ"
    },
    "day1": {
        "title": "📦 Что приготовить в День 1",
        "heading": "📦 ЧТО ПРИГОТОВИТЬ В ДЕНЬ 1",
        "button": "📦 Что приготовить в День 1"
    }
}


def extract_menu_sections(text):

    headings = [
        "🍽️ МЕНЮ НА 3 ДНЯ",
        "🛒 ПОКУПКИ НА 3 ДНЯ",
        "👨‍🍳 ПРИГОТОВЛЕНИЕ",
        "⚖️ ПОРЦИИ И КБЖУ",
        "📦 ЧТО ПРИГОТОВИТЬ В ДЕНЬ 1"
    ]

    positions = []

    for heading in headings:

        patterns = [
            heading,
            f"<b>{heading}</b>"
        ]

        found = None

        for pattern in patterns:

            index = text.find(pattern)

            if index != -1:
                found = index
                break

        if found is not None:
            positions.append(
                (found, heading)
            )

    positions.sort(key=lambda x: x[0])

    sections = {}

    for i, (start, heading) in enumerate(positions):

        end = (
            positions[i + 1][0]
            if i + 1 < len(positions)
            else len(text)
        )

        section_text = text[start:end].strip()

        if heading == "🍽️ МЕНЮ НА 3 ДНЯ":
            sections["menu"] = section_text

        elif heading == "🛒 ПОКУПКИ НА 3 ДНЯ":
            sections["shopping"] = section_text

        elif heading == "👨‍🍳 ПРИГОТОВЛЕНИЕ":
            sections["cooking"] = section_text

        elif heading == "⚖️ ПОРЦИИ И КБЖУ":
            sections["nutrition"] = section_text

        elif heading == "📦 ЧТО ПРИГОТОВИТЬ В ДЕНЬ 1":
            sections["day1"] = section_text

    return sections


def collapsed_section_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "▶️ Показать покупки",
                callback_data="expand_shopping"
            )
        ],
        [
            InlineKeyboardButton(
                "▶️ Показать приготовление",
                callback_data="expand_cooking"
            )
        ],
        [
            InlineKeyboardButton(
                "▶️ Показать порции и КБЖУ",
                callback_data="expand_nutrition"
            )
        ],
        [
            InlineKeyboardButton(
                "▶️ Показать День 1",
                callback_data="expand_day1"
            )
        ]
    ])


def section_keyboard(section_key):

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔼 Свернуть",
                callback_data=f"collapse_{section_key}"
            )
        ]
    ])


async def send_menu(message, text):

    sections = extract_menu_sections(text)

    if "menu" not in sections:

        await send_long_message(
            message,
            text,
            reply_markup=main_keyboard()
        )

        return

    await message.reply_text(
        sections["menu"],
        parse_mode="HTML"
    )

    collapsed_text = (
        "📋 <b>Подробности меню</b>\n\n"
        "Нажми на нужный раздел, чтобы раскрыть его."
    )

    await message.reply_text(
        collapsed_text,
        parse_mode="HTML",
        reply_markup=collapsed_section_keyboard()
    )

    await message.reply_text(
        "Что будем делать дальше?",
        reply_markup=main_keyboard()
    )


# ============================================================
# SUPABASE — ЗАГРУЗКА
# ============================================================

def load_user_memory_sync(user_id, first_name):

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

        print(
            "SUPABASE LOAD ERROR:",
            repr(e)
        )

    data = empty_memory()

    data["marianna"]["other"]["user_name"] = first_name

    return data


async def load_user_memory(user_id, first_name):

    started = time.monotonic()

    result = await asyncio.to_thread(
        load_user_memory_sync,
        user_id,
        first_name
    )

    print(
        f"SUPABASE LOAD: {time.monotonic() - started:.2f}s"
    )

    return result


# ============================================================
# МИГРАЦИЯ
# ============================================================

def migrate_memory(old_memory):

    new_memory = empty_memory()

    if "marianna" in old_memory or "pavel" in old_memory:

        for key in new_memory:

            if key in old_memory and isinstance(
                old_memory[key],
                dict
            ):

                new_memory[key].update(
                    old_memory[key]
                )

        return new_memory

    profile = old_memory.get("profile", {})

    if "height_cm" in profile:
        new_memory["marianna"]["height_cm"] = profile["height_cm"]

    if "weight_kg" in profile:
        new_memory["marianna"]["weight_kg"] = profile["weight_kg"]

    if "goal" in profile:
        new_memory["marianna"]["goal"] = profile["goal"]

    if "food_at_home" in old_memory:
        new_memory["shared"]["food_at_home"] = (
            old_memory["food_at_home"]
        )

    if "liked_dishes" in old_memory:
        new_memory["shared"]["liked_dishes"] = (
            old_memory["liked_dishes"]
        )

    if "disliked_dishes" in old_memory:
        new_memory["shared"]["disliked_dishes"] = (
            old_memory["disliked_dishes"]
        )

    if "dish_ratings" in old_memory:
        new_memory["shared"]["dish_ratings"] = (
            old_memory["dish_ratings"]
        )

    if "current_menu" in old_memory:
        new_memory["shared"]["current_menu"] = (
            old_memory["current_menu"]
        )

    if "menu_history" in old_memory:
        new_memory["shared"]["menu_history"] = (
            old_memory["menu_history"]
        )

    return new_memory


# ============================================================
# SUPABASE — СОХРАНЕНИЕ
# ============================================================

def save_user_memory_sync(user_id, memory_data):

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

        print(
            "SUPABASE SAVE ERROR:",
            repr(e)
        )


async def save_user_memory(user_id, memory_data):

    started = time.monotonic()

    await asyncio.to_thread(
        save_user_memory_sync,
        user_id,
        memory_data
    )

    print(
        f"SUPABASE SAVE: {time.monotonic() - started:.2f}s"
    )


# ============================================================
# НОРМАЛИЗАЦИЯ
# ============================================================

def normalize_text(value):

    if value is None:
        return ""

    value = str(value).lower().strip()

    value = value.replace("ё", "е")

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value


# ============================================================
# СОВПАДЕНИЕ
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
# УДАЛЕНИЕ БЛЮДА ИЗ СПИСКА
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

                if (
                    key in item
                    and text_matches(
                        item[key],
                        dish
                    )
                ):

                    should_remove = True
                    break

        if not should_remove:
            result.append(item)

    return result


# ============================================================
# РЕКУРСИВНОЕ УДАЛЕНИЕ
# ============================================================

def remove_dish_recursive(value, dish):

    if isinstance(value, list):

        result = []

        for item in value:

            if isinstance(item, str):

                if text_matches(item, dish):
                    continue

            elif isinstance(item, dict):

                object_matches = False

                for key in [
                    "dish",
                    "name",
                    "title",
                    "meal",
                    "recipe"
                ]:

                    if (
                        key in item
                        and text_matches(
                            item[key],
                            dish
                        )
                    ):

                        object_matches = True
                        break

                if object_matches:
                    continue

                item = remove_dish_recursive(
                    item,
                    dish
                )

            else:

                item = remove_dish_recursive(
                    item,
                    dish
                )

            result.append(item)

        return result

    if isinstance(value, dict):

        result = {}

        for key, item in value.items():

            if text_matches(key, dish):
                continue

            result[key] = remove_dish_recursive(
                item,
                dish
            )

        return result

    return value


# ============================================================
# ПОЛНОЕ УДАЛЕНИЕ БЛЮДА
# ============================================================

def delete_all_about_dish(
    memory_data,
    dish
):

    shared = memory_data.get(
        "shared",
        {}
    )

    shared["liked_dishes"] = (
        remove_dish_from_list(
            shared.get(
                "liked_dishes",
                []
            ),
            dish
        )
    )

    shared["disliked_dishes"] = (
        remove_dish_from_list(
            shared.get(
                "disliked_dishes",
                []
            ),
            dish
        )
    )

    shared["dish_ratings"] = (
        remove_dish_from_list(
            shared.get(
                "dish_ratings",
                []
            ),
            dish
        )
    )

    if shared.get("current_menu") is not None:

        shared["current_menu"] = (
            remove_dish_recursive(
                shared["current_menu"],
                dish
            )
        )

    shared["menu_history"] = (
        remove_dish_recursive(
            shared.get(
                "menu_history",
                []
            ),
            dish
        )
    )

    for key in list(shared.keys()):

        if key in [
            "liked_dishes",
            "disliked_dishes",
            "dish_ratings",
            "current_menu",
            "menu_history"
        ]:

            continue

        shared[key] = (
            remove_dish_recursive(
                shared[key],
                dish
            )
        )

    memory_data["shared"] = shared

    return memory_data


# ============================================================
# ОЦЕНКА БЛЮДА
# ============================================================

def update_dish_rating(
    memory_data,
    dish,
    person,
    rating
):

    ratings = memory_data[
        "shared"
    ].get(
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
            text_matches(
                item_dish,
                dish
            )
            and item_person == person
        ):

            continue

        new_ratings.append(item)

    new_ratings.append({
        "dish": dish,
        "person": person,
        "rating": rating
    })

    memory_data[
        "shared"
    ][
        "dish_ratings"
    ] = new_ratings

    return memory_data


# ============================================================
# ПРИМЕНЕНИЕ ОПЕРАЦИЙ ПАМЯТИ
# ============================================================

def apply_memory_updates(
    memory_data,
    operations
):

    for operation in operations:

        if not isinstance(
            operation,
            dict
        ):
            continue

        action = operation.get("action")

        if action in [
            "add",
            "update"
        ]:

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

            if person in [
                "marianna",
                "pavel"
            ]:

                if field in [
                    "height_cm",
                    "weight_kg",
                    "goal"
                ]:

                    memory_data[
                        person
                    ][field] = value

                else:

                    memory_data[
                        person
                    ][
                        "other"
                    ][field] = value

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
                            ][
                                "liked_dishes"
                            ]:

                                memory_data[
                                    "shared"
                                ][
                                    "liked_dishes"
                                ].append(item)

                elif field == "disliked_dishes":

                    if isinstance(value, list):

                        for item in value:

                            if item not in memory_data[
                                "shared"
                            ][
                                "disliked_dishes"
                            ]:

                                memory_data[
                                    "shared"
                                ][
                                    "disliked_dishes"
                                ].append(item)

                elif field == "dish_rating":

                    if isinstance(value, dict):

                        dish = value.get("dish")
                        person_value = value.get("person")
                        rating = value.get("rating")

                        if (
                            dish
                            and person_value
                            and rating
                        ):

                            memory_data = (
                                update_dish_rating(
                                    memory_data,
                                    dish,
                                    person_value,
                                    rating
                                )
                            )

                elif field == "current_menu":

                    memory_data[
                        "shared"
                    ][
                        "current_menu"
                    ] = value

                elif field == "menu_history":

                    if isinstance(value, list):

                        memory_data[
                            "shared"
                        ][
                            "menu_history"
                        ].extend(value)

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

            if person in [
                "marianna",
                "pavel"
            ]:

                if field in [
                    "height_cm",
                    "weight_kg",
                    "goal"
                ]:

                    if (
                        value is None
                        or memory_data[
                            person
                        ].get(field) == value
                    ):

                        memory_data[
                            person
                        ][field] = None

                else:

                    memory_data[
                        person
                    ][
                        "other"
                    ].pop(
                        field,
                        None
                    )

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
                                and text_matches(
                                    key,
                                    value
                                )
                            ):

                                keys_to_delete.append(key)

                        for key in keys_to_delete:
                            del food[key]

                elif field == "liked_dishes":

                    memory_data[
                        "shared"
                    ][
                        "liked_dishes"
                    ] = (
                        remove_dish_from_list(
                            memory_data[
                                "shared"
                            ].get(
                                "liked_dishes",
                                []
                            ),
                            value
                        )
                    )

                elif field == "disliked_dishes":

                    memory_data[
                        "shared"
                    ][
                        "disliked_dishes"
                    ] = (
                        remove_dish_from_list(
                            memory_data[
                                "shared"
                            ].get(
                                "disliked_dishes",
                                []
                            ),
                            value
                        )
                    )

                elif field == "dish_rating":

                    memory_data[
                        "shared"
                    ][
                        "dish_ratings"
                    ] = (
                        remove_dish_from_list(
                            memory_data[
                                "shared"
                            ].get(
                                "dish_ratings",
                                []
                            ),
                            value
                        )
                    )

        elif action == "delete_all_dish":

            dish = operation.get("dish")

            if dish:

                memory_data = (
                    delete_all_about_dish(
                        memory_data,
                        dish
                    )
                )

        elif action == "clear_food":

            memory_data[
                "shared"
            ][
                "food_at_home"
            ] = {}

    return memory_data


# ============================================================
# OPENAI — ПАМЯТЬ
# ============================================================

async def extract_memory_operations(
    user_message,
    current_memory
):

    started = time.monotonic()

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
    {{
      "action": "update",
      "person": "pavel",
      "field": "weight_kg",
      "value": 68
    }}
  ]
}}

Пользователь:
Вес Павла теперь 70 кг.

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

Пользователь:
Купили 2 кг куриного филе.

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

Пользователь:
Куриное филе закончилось.

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

Пользователь:
Удали филе из продуктов.

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

Пользователь:
Марианне понравилась запеканка.

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

Пользователь:
Марианне не понравилась запеканка.

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

Пользователь:
Запеканку больше никогда не готовить.

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

Пользователь:
Удали всю информацию о запеканке.

{{
  "operations": [
    {{
      "action": "delete_all_dish",
      "dish": "запеканка"
    }}
  ]
}}

ВАЖНО:

Если пользователь использует:
- удали;
- удалить;
- забудь;
- убери;
- сотри;
- очисти;
- больше не храни;

это команда изменения памяти.

Не сохраняй удаляемую информацию обратно.

Если пользователь говорит:
«Удали всю информацию о запеканке»

используй delete_all_dish.

Если пользователь даёт новую оценку тому же блюду и человеку,
последняя оценка должна заменить предыдущую.

Не придумывай данные.

Если изменений нет:

{{
  "operations": []
}}
"""

    try:

        response = await asyncio.to_thread(
            client.responses.create,
            model="gpt-5-mini",
            instructions="""
Ты — модуль управления памятью.

Возвращай только валидный JSON.
Без Markdown.
Без пояснений.
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

        print(
            f"OPENAI MEMORY: {time.monotonic() - started:.2f}s"
        )

        return operations

    except Exception as e:

        print(
            "MEMORY EXTRACTION ERROR:",
            repr(e)
        )

        print(
            f"OPENAI MEMORY ERROR AFTER: "
            f"{time.monotonic() - started:.2f}s"
        )

        return []


# ============================================================
# ОПРЕДЕЛЕНИЕ ЗАМЕНЫ
# ============================================================

def detect_replacement_request(user_message):

    text = normalize_text(
        user_message
    )

    replacement_words = [
        "замени",
        "заменить",
        "поменяй",
        "поменять",
        "другой",
        "другое",
        "надоел",
        "надоела",
        "надоело"
    ]

    if not any(
        word in text
        for word in replacement_words
    ):
        return None

    if (
        "завтрак" in text
        or "завтрака" in text
    ):
        return "breakfast"

    if (
        "основное блюдо" in text
        or "основное" in text
        or "обед" in text
    ):
        return "main"

    if (
        "закуск" in text
        or "хрустящ" in text
    ):
        return "marianna_snack"

    if (
        "овощ" in text
        or "овощное дополнение" in text
    ):
        return "pavel_vegetables"

    return None


# ============================================================
# ПРОВЕРКА НОВОГО МЕНЮ
# ============================================================

def is_new_menu_request(user_message):

    text = normalize_text(
        user_message
    )

    phrases = [
        "новое меню",
        "составь новое меню",
        "давай новое меню",
        "сделай новое меню",
        "придумай новое меню",
        "меню на 3 дня",
        "новый цикл"
    ]

    return any(
        phrase in text
        for phrase in phrases
    )


# ============================================================
# ПРОВЕРКА ТЕКУЩЕГО МЕНЮ
# ============================================================

def is_current_menu_request(user_message):

    text = normalize_text(
        user_message
    )

    phrases = [
        "что есть сегодня",
        "что у нас сегодня",
        "какое меню сегодня",
        "что кушать сегодня",
        "что покушать сегодня",
        "текущее меню"
    ]

    return any(
        phrase in text
        for phrase in phrases
    )


# ============================================================
# ЗАМЕНА ОДНОГО ЭЛЕМЕНТА
# ============================================================

async def replace_single_menu_item(
    current_menu,
    user_message,
    replacement_type,
    memory_data
):

    if not current_menu:
        return None

    memory_context = json.dumps(
        memory_data,
        ensure_ascii=False,
        separators=(",", ":")
    )

    if len(memory_context) > 30000:
        memory_context = memory_context[:30000]

    type_names = {
        "breakfast": "ЗАВТРАК ПАВЛА",
        "main": "ОСНОВНОЕ БЛЮДО",
        "marianna_snack": "ХРУСТЯЩАЯ ЗАКУСКА МАРИАННЫ",
        "pavel_vegetables": "ОВОЩНОЕ ДОПОЛНЕНИЕ ПАВЛА"
    }

    target_name = type_names[
        replacement_type
    ]

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

НЕ создавай новый цикл с нуля.

Сохрани без изменений:
- остальные блюда;
- остальные элементы меню;
- количество дней;
- общую структуру цикла.

Замени ТОЛЬКО указанный элемент.

Если пользователь предложил конкретное блюдо,
используй именно его.

Если конкретное блюдо не указано,
сам выбери подходящую замену с учётом памяти.

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

Покажи полный обновлённый цикл,
чтобы пользователь видел итоговое меню целиком.

Сохрани все остальные элементы текущего меню.

Отвечай на русском языке.
"""

    started = time.monotonic()

    try:

        response = await asyncio.to_thread(
            client.responses.create,
            model="gpt-5-mini",
            instructions=SYSTEM_PROMPT,
            input=prompt
        )

        answer = response.output_text.strip()

        print(
            f"OPENAI REPLACEMENT: "
            f"{time.monotonic() - started:.2f}s"
        )

        if not answer:
            return None

        return answer

    except Exception as e:

        print(
            "MENU REPLACEMENT ERROR:",
            repr(e)
        )

        print(
            f"OPENAI REPLACEMENT ERROR AFTER: "
            f"{time.monotonic() - started:.2f}s"
        )

        return None


# ============================================================
# ДЛИННЫЕ TELEGRAM СООБЩЕНИЯ
# ============================================================

async def send_long_message(
    message,
    text,
    reply_markup=None,
    parse_mode="HTML"
):

    max_length = 3900

    if len(text) <= max_length:

        await message.reply_text(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )

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

        await message.reply_text(
            part,
            parse_mode=parse_mode
        )

        text = text[cut:].lstrip()

    if text:

        await message.reply_text(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )


# ============================================================
# ФОРМАТ ПРОДУКТОВ
# ============================================================

def format_food_at_home(food):

    if not food:

        return (
            "🏠 Сейчас в списке продуктов дома ничего нет."
        )

    lines = [
        "🏠 <b>Что есть дома:</b>",
        ""
    ]

    for name, amount in food.items():

        lines.append(
            f"• {name}: {amount}"
        )

    return "\n".join(lines)


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data.pop(
        "replacement_type",
        None
    )

    context.user_data.pop(
        "awaiting_input",
        None
    )

    await update.message.reply_text(
        "Привет! 🍽️\n\n"
        "Я помощник Марианны и Павла по меню.\n\n"
        "Выбирай нужное действие:",
        reply_markup=main_keyboard()
    )


# ============================================================
# НОВЫЙ ЦИКЛ
# ============================================================

async def generate_new_cycle(
    message,
    user_id,
    memory_data
):

    await message.reply_text(
        "Готовлю новый цикл на 3 дня 🍽️\n"
        "Учитываю продукты дома, ваши предпочтения "
        "и предыдущие меню..."
    )

    memory_context = json.dumps(
        memory_data,
        ensure_ascii=False,
        separators=(",", ":")
    )

    if len(memory_context) > 30000:

        print(
            "WARNING: MEMORY TOO LARGE:",
            len(memory_context)
        )

        memory_context = memory_context[:30000]

    prompt = f"""
ПОСТОЯННАЯ ПАМЯТЬ ПОЛЬЗОВАТЕЛЯ:

{memory_context}

ПОЛЬЗОВАТЕЛЬ ПРОСИТ СОСТАВИТЬ НОВЫЙ ЦИКЛ
НА 3 ДНЯ.

Составь полный новый цикл на 3 дня.

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

    started = time.monotonic()

    try:

        response = await asyncio.to_thread(
            client.responses.create,
            model="gpt-5-mini",
            instructions=SYSTEM_PROMPT,
            input=prompt
        )

        answer = response.output_text.strip()

        print(
            f"OPENAI NEW MENU: "
            f"{time.monotonic() - started:.2f}s"
        )

    except Exception as e:

        print(
            "OPENAI NEW MENU ERROR:",
            repr(e)
        )

        print(
            f"OPENAI NEW MENU ERROR AFTER: "
            f"{time.monotonic() - started:.2f}s"
        )

        await message.reply_text(
            "Произошла ошибка при создании меню 😔",
            reply_markup=main_keyboard()
        )

        return

    old_menu = memory_data[
        "shared"
    ].get(
        "current_menu"
    )

    if old_menu:

        memory_data[
            "shared"
        ][
            "menu_history"
        ].append(
            old_menu
        )

    memory_data[
        "shared"
    ][
        "current_menu"
    ] = answer

    await save_user_memory(
        user_id,
        memory_data
    )

    print(
        "NEW MENU SAVED AS CURRENT MENU"
    )

    await send_menu(
        message,
        answer
    )


# ============================================================
# CALLBACK — КНОПКИ
# ============================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    data = query.data

    # ========================================================
    # РАСКРЫТИЕ РАЗДЕЛА МЕНЮ
    # ========================================================

    if data.startswith("expand_"):

        section_key = data.replace(
            "expand_",
            "",
            1
        )

        if section_key not in MENU_SECTIONS:
            return

        user_id = str(
            update.effective_user.id
        )

        memory_data = await load_user_memory(
            user_id,
            update.effective_user.first_name
        )

        current_menu = memory_data[
            "shared"
        ].get(
            "current_menu"
        )

        if not current_menu:

            await query.edit_message_text(
                "Текущее меню больше не найдено 😔",
                reply_markup=main_keyboard()
            )

            return

        sections = extract_menu_sections(
            current_menu
        )

        section_text = sections.get(
            section_key
        )

        if not section_text:

            await query.edit_message_text(
                "Не удалось найти этот раздел 😔",
                reply_markup=main_keyboard()
            )

            return

        await query.edit_message_text(
            section_text,
            parse_mode="HTML",
            reply_markup=section_keyboard(
                section_key
            )
        )

        return


    # ========================================================
    # СВОРАЧИВАНИЕ РАЗДЕЛА
    # ========================================================

    if data.startswith("collapse_"):

        section_key = data.replace(
            "collapse_",
            "",
            1
        )

        if section_key not in MENU_SECTIONS:
            return

        collapsed_text = (
            "📋 <b>Раздел свёрнут</b>\n\n"
            f"{MENU_SECTIONS[section_key]['title']}\n\n"
            "Нажми ниже, чтобы снова раскрыть."
        )

        await query.edit_message_text(
            collapsed_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "▶️ Показать",
                        callback_data=f"expand_{section_key}"
                    )
                ]
            ])
        )

        return


    # ========================================================
    # ГЛАВНОЕ МЕНЮ
    # ========================================================

    if data == "main_menu":

        context.user_data.pop(
            "replacement_type",
            None
        )

        context.user_data.pop(
            "awaiting_input",
            None
        )

        await query.edit_message_text(
            "🍽️ <b>Главное меню</b>\n\n"
            "Что будем делать?",
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )

        return


    # ========================================================
    # НОВЫЙ ЦИКЛ
    # ========================================================

    if data == "new_cycle":

        context.user_data.pop(
            "replacement_type",
            None
        )

        context.user_data.pop(
            "awaiting_input",
            None
        )

        user_id = str(
            update.effective_user.id
        )

        started = time.monotonic()

        memory_data = await load_user_memory(
            user_id,
            update.effective_user.first_name
        )

        print(
            f"NEW CYCLE PREP: "
            f"{time.monotonic() - started:.2f}s"
        )

        await query.edit_message_text(
            "🆕 <b>Новый цикл на 3 дня</b>\n\n"
            "Составляю меню...",
            parse_mode="HTML"
        )

        await generate_new_cycle(
            query.message,
            user_id,
            memory_data
        )

        return


    # ========================================================
    # ЗАМЕНА БЛЮДА — МЕНЮ
    # ========================================================

    if data == "replace_menu":

        await query.edit_message_text(
            "🔄 <b>Что заменить?</b>\n\n"
            "Выбери только один элемент текущего цикла:",
            parse_mode="HTML",
            reply_markup=replace_keyboard()
        )

        return


    # ========================================================
    # КОНКРЕТНЫЙ ТИП ЗАМЕНЫ
    # ========================================================

    replacement_map = {
        "replace_breakfast": (
            "breakfast",
            "🍳 Завтрак Павла"
        ),
        "replace_main": (
            "main",
            "🍗 Основное блюдо"
        ),
        "replace_snack": (
            "marianna_snack",
            "🥨 Закуска Марианны"
        ),
        "replace_vegetables": (
            "pavel_vegetables",
            "🥦 Овощи Павла"
        )
    }

    if data in replacement_map:

        replacement_type, title = replacement_map[data]

        user_id = str(
            update.effective_user.id
        )

        memory_data = await load_user_memory(
            user_id,
            update.effective_user.first_name
        )

        current_menu = memory_data[
            "shared"
        ].get(
            "current_menu"
        )

        if not current_menu:

            await query.edit_message_text(
                "У нас сейчас нет сохранённого "
                "текущего меню 😔\n\n"
                "Сначала создай новый цикл.",
                reply_markup=main_keyboard()
            )

            return

        context.user_data[
            "replacement_type"
        ] = replacement_type

        context.user_data[
            "awaiting_input"
        ] = "replacement"

        await query.edit_message_text(
            f"{title}\n\n"
            "Напиши, на что заменить.\n\n"
            "Например:\n"
            "• «на сырники»\n"
            "• «на куриные котлеты»\n"
            "• «давай другой»\n\n"
            "Если конкретное блюдо не укажешь — "
            "я сама выберу подходящее.",
            reply_markup=back_keyboard()
        )

        return


    # ========================================================
    # ПРОДУКТЫ
    # ========================================================

    if data == "products":

        await query.edit_message_text(
            "🛒 <b>Продукты</b>\n\n"
            "Что хочешь сделать?",
            parse_mode="HTML",
            reply_markup=products_keyboard()
        )

        return


    # ========================================================
    # ЧТО ЕСТЬ ДОМА
    # ========================================================

    if data == "food_home":

        user_id = str(
            update.effective_user.id
        )

        memory_data = await load_user_memory(
            user_id,
            update.effective_user.first_name
        )

        food = memory_data[
            "shared"
        ].get(
            "food_at_home",
            {}
        )

        await query.edit_message_text(
            format_food_at_home(food),
            parse_mode="HTML",
            reply_markup=products_keyboard()
        )

        return


    # ========================================================
    # ИЗМЕНИТЬ ПРОДУКТЫ
    # ========================================================

    if data == "edit_food":

        context.user_data[
            "awaiting_input"
        ] = "food"

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


    # ========================================================
    # ПРЕДПОЧТЕНИЯ
    # ========================================================

    if data == "preferences":

        await query.edit_message_text(
            "❤️ <b>Предпочтения</b>\n\n"
            "Чьи предпочтения хочешь изменить?",
            parse_mode="HTML",
            reply_markup=preferences_keyboard()
        )

        return


    # ========================================================
    # МАРИАННА
    # ========================================================

    if data == "pref_marianna":

        context.user_data[
            "awaiting_input"
        ] = "marianna_preferences"

        await query.edit_message_text(
            "🧑🏾‍🦱 <b>Предпочтения Марианны</b>\n\n"
            "Напиши, что хочешь добавить, изменить "
            "или удалить.\n\n"
            "Например:\n"
            "• «Марианне нравится лазанья»\n"
            "• «Марианна больше не хочет есть сырники»\n"
            "• «Марианна любит курицу»\n"
            "• «Забудь, что Марианне нравится лазанья»",
            parse_mode="HTML",
            reply_markup=back_keyboard()
        )

        return


    # ========================================================
    # ПАВЕЛ
    # ========================================================

    if data == "pref_pavel":

        context.user_data[
            "awaiting_input"
        ] = "pavel_preferences"

        await query.edit_message_text(
            "👨 <b>Предпочтения Павла</b>\n\n"
            "Напиши, что хочешь добавить, изменить "
            "или удалить.\n\n"
            "Например:\n"
            "• «Павлу нравится паста»\n"
            "• «Павел не любит жирные соусы»\n"
            "• «Павлу надоели котлеты»\n"
            "• «Забудь, что Павел любит рис»",
            parse_mode="HTML",
            reply_markup=back_keyboard()
        )

        return


    # ========================================================
    # ОЦЕНКА БЛЮДА
    # ========================================================

    if data == "rate_dish":

        context.user_data[
            "awaiting_input"
        ] = "rating"

        await query.edit_message_text(
            "⭐ <b>Оценить блюдо</b>\n\n"
            "Напиши, кто и как оценил блюдо.\n\n"
            "Например:\n"
            "❤️ «Марианне очень понравились сырники»\n"
            "🙂 «Павлу нормально»\n"
            "😐 «Марианне не понравились котлеты»\n"
            "🚫 «Павлу больше никогда не готовить пасту»\n\n"
            "Последняя оценка будет заменять предыдущую.",
            parse_mode="HTML",
            reply_markup=back_keyboard()
        )

        return


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

    total_started = time.monotonic()

    user_id = str(
        update.effective_user.id
    )

    user_message = (
        update.message.text.strip()
    )

    print(
        "========================================"
    )

    print(
        "MESSAGE:",
        user_message
    )

    print(
        "USER ID:",
        user_id
    )

    # ========================================================
    # Состояние после кнопки
    # ========================================================

    replacement_type_from_button = (
        context.user_data.get(
            "replacement_type"
        )
    )

    # ========================================================
    # Загружаем память
    # ========================================================

    memory_data = await load_user_memory(
        user_id,
        update.effective_user.first_name
    )

    # ========================================================
    # БЫСТРЫЕ КОМАНДЫ
    #
    # ВАЖНО:
    # Здесь намеренно НЕ вызываем GPT для анализа памяти.
    # ========================================================

    # --------------------------------------------------------
    # Текущее меню
    # --------------------------------------------------------

    if is_current_menu_request(
        user_message
    ):

        current_menu = memory_data[
            "shared"
        ].get(
            "current_menu"
        )

        if current_menu:

            print(
                "FAST ROUTE: CURRENT MENU"
            )

            await send_menu(
                update.message,
                current_menu
            )

            print(
                f"TOTAL: "
                f"{time.monotonic() - total_started:.2f}s"
            )

            return

        else:

            await update.message.reply_text(
                "Сейчас сохранённого меню нет 🍽️\n\n"
                "Нажми «🆕 Новый цикл на 3 дня», "
                "и я составлю новый цикл.",
                reply_markup=main_keyboard()
            )

            print(
                f"TOTAL: "
                f"{time.monotonic() - total_started:.2f}s"
            )

            return

    # --------------------------------------------------------
    # Новое меню
    # --------------------------------------------------------

    if is_new_menu_request(
        user_message
    ):

        print(
            "FAST ROUTE: NEW MENU"
        )

        await generate_new_cycle(
            update.message,
            user_id,
            memory_data
        )

        print(
            f"TOTAL: "
            f"{time.monotonic() - total_started:.2f}s"
        )

        return

    # ========================================================
    # Если после кнопки выбран тип замены
    # ========================================================

    if replacement_type_from_button:

        current_menu = memory_data[
            "shared"
        ].get(
            "current_menu"
        )

        if not current_menu:

            context.user_data.pop(
                "replacement_type",
                None
            )

            context.user_data.pop(
                "awaiting_input",
                None
            )

            await update.message.reply_text(
                "У нас сейчас нет сохранённого "
                "текущего меню 😔\n\n"
                "Сначала создай новый цикл.",
                reply_markup=main_keyboard()
            )

            return

        await update.message.reply_text(
            "🔄 Хорошо, заменяю только это блюдо..."
        )

        updated_menu = await replace_single_menu_item(
            current_menu,
            user_message,
            replacement_type_from_button,
            memory_data
        )

        context.user_data.pop(
            "replacement_type",
            None
        )

        context.user_data.pop(
            "awaiting_input",
            None
        )

        if updated_menu:

            old_menu = memory_data[
                "shared"
            ].get(
                "current_menu"
            )

            if old_menu:

                memory_data[
                    "shared"
                ][
                    "menu_history"
                ].append(
                    old_menu
                )

            memory_data[
                "shared"
            ][
                "current_menu"
            ] = updated_menu

            await save_user_memory(
                user_id,
                memory_data
            )

            print(
                "CURRENT MENU UPDATED"
            )

            await send_menu(
                update.message,
                updated_menu
            )

            print(
                f"TOTAL: "
                f"{time.monotonic() - total_started:.2f}s"
            )

            return

        else:

            await update.message.reply_text(
                "Не получилось заменить блюдо 😔\n\n"
                "Попробуй ещё раз.",
                reply_markup=main_keyboard()
            )

            return

    # ========================================================
    # Обычная текстовая замена
    # ========================================================

    replacement_type = (
        detect_replacement_request(
            user_message
        )
    )

    if replacement_type:

        current_menu = memory_data[
            "shared"
        ].get(
            "current_menu"
        )

        if not current_menu:

            await update.message.reply_text(
                "У нас сейчас нет сохранённого "
                "текущего меню, поэтому мне нечего заменять 😔\n\n"
                "Нажми «🆕 Новый цикл на 3 дня».",
                reply_markup=main_keyboard()
            )

            return

        await update.message.reply_text(
            "🔄 Хорошо, заменяю только это блюдо "
            "и сохраняю остальные элементы цикла..."
        )

        updated_menu = await replace_single_menu_item(
            current_menu,
            user_message,
            replacement_type,
            memory_data
        )

        if updated_menu:

            old_menu = memory_data[
                "shared"
            ].get(
                "current_menu"
            )

            if old_menu:

                memory_data[
                    "shared"
                ][
                    "menu_history"
                ].append(
                    old_menu
                )

            memory_data[
                "shared"
            ][
                "current_menu"
            ] = updated_menu

            await save_user_memory(
                user_id,
                memory_data
            )

            print(
                "CURRENT MENU UPDATED"
            )

            await send_menu(
                update.message,
                updated_menu
            )

            print(
                f"TOTAL: "
                f"{time.monotonic() - total_started:.2f}s"
            )

            return

        else:

            await update.message.reply_text(
                "Не получилось заменить блюдо 😔\n"
                "Попробуй написать, например: "
                "«Замени завтрак на сырники».",
                reply_markup=main_keyboard()
            )

            return

    # ========================================================
    # ПАМЯТЬ
    #
    # Только теперь вызываем отдельный GPT для определения,
    # нужно ли что-то сохранить.
    # ========================================================

    memory_started = time.monotonic()

    operations = await extract_memory_operations(
        user_message,
        memory_data
    )

    print(
        "MEMORY OPERATIONS:",
        operations
    )

    print(
        f"MEMORY STEP TOTAL: "
        f"{time.monotonic() - memory_started:.2f}s"
    )

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

        if old_memory != new_memory:

            await save_user_memory(
                user_id,
                memory_data
            )

    # ========================================================
    # Контекст памяти
    # ========================================================

    memory_context = json.dumps(
        memory_data,
        ensure_ascii=False,
        separators=(",", ":")
    )

    if len(memory_context) > 30000:

        print(
            "WARNING: MEMORY TOO LARGE:",
            len(memory_context)
        )

        memory_context = memory_context[:30000]

    # ========================================================
    # Основной запрос
    # ========================================================

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

Если пользователь просит новое меню,
после создания полного меню оно должно считаться
новым текущим меню.

Если информации действительно не хватает для выполнения задачи,
задай только необходимый вопрос.
"""

    # ========================================================
    # Основной GPT
    # ========================================================

    started = time.monotonic()

    try:

        response = await asyncio.to_thread(
            client.responses.create,
            model="gpt-5-mini",
            instructions=SYSTEM_PROMPT,
            input=prompt
        )

        answer = response.output_text.strip()

        print(
            f"OPENAI MAIN: "
            f"{time.monotonic() - started:.2f}s"
        )

    except Exception as e:

        print(
            "OPENAI ERROR:",
            repr(e)
        )

        print(
            f"OPENAI MAIN ERROR AFTER: "
            f"{time.monotonic() - started:.2f}s"
        )

        await update.message.reply_text(
            "Произошла ошибка при обращении к ИИ 😔",
            reply_markup=main_keyboard()
        )

        return

    # ========================================================
    # Если это новое меню — сохраняем его
    # ========================================================

    if is_new_menu_request(
        user_message
    ):

        old_menu = memory_data[
            "shared"
        ].get(
            "current_menu"
        )

        if old_menu:

            memory_data[
                "shared"
            ][
                "menu_history"
            ].append(
                old_menu
            )

        memory_data[
            "shared"
        ][
            "current_menu"
        ] = answer

        await save_user_memory(
            user_id,
            memory_data
        )

        print(
            "NEW MENU SAVED AS CURRENT MENU"
        )

    # ========================================================
    # Сбрасываем режим ввода
    # ========================================================

    context.user_data.pop(
        "awaiting_input",
        None
    )

    # ========================================================
    # Отправляем ответ
    # ========================================================

    try:

        await send_long_message(
            update.message,
            answer,
            reply_markup=main_keyboard()
        )

        print(
            "TELEGRAM RESPONSE SENT"
        )

    except Exception as e:

        print(
            "TELEGRAM ERROR:",
            repr(e)
        )

    print(
        f"TOTAL REQUEST TIME: "
        f"{time.monotonic() - total_started:.2f}s"
    )

    print(
        "========================================"
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
        CallbackQueryHandler(
            button_handler
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            chat
        )
    )

    try:

        print(
            "Starting Telegram application..."
        )

        await application.initialize()

        print(
            "Telegram application initialized."
        )

        await application.start()

        print(
            "Telegram application started."
        )

        await application.updater.start_polling()

        print(
            "Telegram bot started!"
        )

        # Держим Telegram-приложение живым.
        await asyncio.Event().wait()

    except asyncio.CancelledError:

        print(
            "Telegram bot task cancelled."
        )

        raise

    except Exception as e:

        print(
            "TELEGRAM RUN ERROR:",
            repr(e)
        )

        raise

    finally:

        print(
            "Stopping Telegram bot..."
        )

        try:

            if application.updater.running:

                await application.updater.stop()

        except Exception as e:

            print(
                "UPDATER STOP ERROR:",
                repr(e)
            )

        try:

            if application.running:

                await application.stop()

        except Exception as e:

            print(
                "APPLICATION STOP ERROR:",
                repr(e)
            )

        try:

            await application.shutdown()

        except Exception as e:

            print(
                "APPLICATION SHUTDOWN ERROR:",
                repr(e)
            )

        print(
            "Telegram bot stopped."
        )


# ============================================================
# MAIN
# ============================================================

async def main():

    bot_task = asyncio.create_task(
        run_bot()
    )

    from hypercorn.asyncio import serve
    from hypercorn.config import Config

    config = Config()

    config.bind = [
        f"0.0.0.0:{os.environ.get('PORT', '10000')}"
    ]

    try:

        print(
            "Starting Flask/Hypercorn server..."
        )

        await serve(
            app,
            config
        )

    finally:

        print(
            "Web server stopped. "
            "Stopping Telegram task..."
        )

        if not bot_task.done():

            bot_task.cancel()

        try:

            await bot_task

        except asyncio.CancelledError:

            pass

        except Exception as e:

            print(
                "BOT TASK FINAL ERROR:",
                repr(e)
            )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )
