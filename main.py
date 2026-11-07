# ============================================================
#                    PLAYFUN PAY BOT
#              Telegram Bot | Python | Aiogram 3
# ============================================================
#
# Функции проекта:
# 1. Бесплатное меню
# 2. Платный приват
# 3. Административная панель
# 4. Редактирование всех кнопок
# 5. Ежедневные способы заработка
# 6. Несколько способов оплаты
# 7. Реферальная система
# 8. Промокоды
# 9. Рассылки
# 10. Поддержка
# 11. Статистика
#
# ============================================================

import asyncio
import logging
import os
from datetime import datetime, timedelta
from html import escape

import aiosqlite

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from dotenv import load_dotenv


# ============================================================
#                       НАСТРОЙКИ
# ============================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

ADMIN_IDS = [
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
]

DATABASE = "playfunpay.db"

if not BOT_TOKEN:
    raise RuntimeError("Укажи BOT_TOKEN в файле .env")

logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher()


# ============================================================
#                  ВРЕМЕННЫЕ СОСТОЯНИЯ
# ============================================================

USER_STATES = {}


def set_state(user_id: int, state: str):
    USER_STATES[user_id] = state


def get_state(user_id: int):
    return USER_STATES.get(user_id)


def clear_state(user_id: int):
    USER_STATES.pop(user_id, None)


# ============================================================
#                    БАЗА ДАННЫХ
# ============================================================

async def init_database():

    async with aiosqlite.connect(DATABASE) as db:

        await db.executescript("""

        CREATE TABLE IF NOT EXISTS users (

            user_id INTEGER PRIMARY KEY,

            username TEXT,

            first_name TEXT,

            referrer INTEGER DEFAULT NULL,

            joined_at TEXT,

            paid_until TEXT DEFAULT NULL,

            banned INTEGER DEFAULT 0

        );


        CREATE TABLE IF NOT EXISTS buttons (

            button_id TEXT PRIMARY KEY,

            title TEXT,

            url TEXT DEFAULT ''

        );


        CREATE TABLE IF NOT EXISTS payments (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            title TEXT,

            description TEXT,

            url TEXT DEFAULT ''

        );


        CREATE TABLE IF NOT EXISTS promos (

            code TEXT PRIMARY KEY,

            days INTEGER,

            uses_left INTEGER

        );


        CREATE TABLE IF NOT EXISTS promo_uses (

            user_id INTEGER,

            code TEXT,

            PRIMARY KEY(user_id, code)

        );


        CREATE TABLE IF NOT EXISTS daily_posts (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            title TEXT,

            content TEXT,

            created_at TEXT

        );


        CREATE TABLE IF NOT EXISTS settings (

            key TEXT PRIMARY KEY,

            value TEXT

        );


        CREATE TABLE IF NOT EXISTS support_messages (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER,

            message TEXT,

            created_at TEXT

        );


        CREATE TABLE IF NOT EXISTS payment_requests (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER,

            method TEXT,

            comment TEXT,

            status TEXT DEFAULT 'pending',

            created_at TEXT

        );

        """)

        await db.commit()

    await install_default_buttons()


# ============================================================
#                  СТАНДАРТНЫЕ КНОПКИ
# ============================================================

DEFAULT_BUTTONS = {

    "free": "🆓 Бесплатное меню",

    "paid": "🔐 Платный приват",

    "daily": "💰 Ежедневный заработок",

    "games": "🎮 Игры и гайды",

    "referral": "👥 Реферальная система",

    "promo": "🎟 Ввести промокод",

    "payments": "💳 Способы оплаты",

    "support": "🆘 Поддержка",

    "back": "⬅️ Назад",

}


async def install_default_buttons():

    async with aiosqlite.connect(DATABASE) as db:

        for key, title in DEFAULT_BUTTONS.items():

            await db.execute(

                """
                INSERT OR IGNORE INTO buttons
                (button_id, title, url)
                VALUES (?, ?, '')
                """,

                (key, title)

            )

        await db.commit()


async def get_button(button_id):

    async with aiosqlite.connect(DATABASE) as db:

        cursor = await db.execute(

            """
            SELECT title, url
            FROM buttons
            WHERE button_id=?
            """,

            (button_id,)

        )

        result = await cursor.fetchone()

    if result:
        return result

    return DEFAULT_BUTTONS.get(button_id, button_id), ""


async def make_button(button_id):

    title, url = await get_button(button_id)

    if url:

        return InlineKeyboardButton(
            text=title,
            url=url
        )

    return InlineKeyboardButton(
        text=title,
        callback_data=f"menu:{button_id}"
    )


# ============================================================
#                   ГЛАВНОЕ МЕНЮ
# ============================================================

async def main_keyboard():

    keyboard = [

        [await make_button("free")],

        [await make_button("paid")],

        [await make_button("daily")],

        [await make_button("games")],

        [await make_button("referral")],

        [await make_button("promo")],

        [await make_button("payments")],

        [await make_button("support")],

    ]

    return InlineKeyboardMarkup(
        inline_keyboard=keyboard
    )


async def back_keyboard():

    return InlineKeyboardMarkup(

        inline_keyboard=[

            [await make_button("back")]

        ]

    )


# ============================================================
#                   ПРОВЕРКА АДМИНА
# ============================================================

def is_admin(user_id):

    return user_id in ADMIN_IDS


# ============================================================
#                   РЕГИСТРАЦИЯ
# ============================================================

async def register_user(message: Message, referrer=None):

    user = message.from_user

    async with aiosqlite.connect(DATABASE) as db:

        cursor = await db.execute(

            "SELECT user_id FROM users WHERE user_id=?",

            (user.id,)

        )

        exists = await cursor.fetchone()

        if not exists:

            if referrer == user.id:
                referrer = None

            await db.execute(

                """
                INSERT INTO users
                (
                    user_id,
                    username,
                    first_name,
                    referrer,
                    joined_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,

                (
                    user.id,
                    user.username or "",
                    user.first_name or "",
                    referrer,
                    datetime.now().isoformat()
                )

            )

        else:

            await db.execute(

                """
                UPDATE users
                SET username=?, first_name=?
                WHERE user_id=?
                """,

                (
                    user.username or "",
                    user.first_name or "",
                    user.id
                )

            )

        await db.commit()


# ============================================================
#                    ПРОВЕРКА ДОСТУПА
# ============================================================

async def check_paid_access(user_id):

    async with aiosqlite.connect(DATABASE) as db:

        cursor = await db.execute(

            "SELECT paid_until FROM users WHERE user_id=?",

            (user_id,)

        )

        result = await cursor.fetchone()

    if not result or not result[0]:
        return False

    try:

        expiration = datetime.fromisoformat(result[0])

        return expiration > datetime.now()

    except ValueError:

        return False


async def give_paid_access(user_id, days):

    async with aiosqlite.connect(DATABASE) as db:

        cursor = await db.execute(

            "SELECT paid_until FROM users WHERE user_id=?",

            (user_id,)

        )

        result = await cursor.fetchone()

        now = datetime.now()

        if result and result[0]:

            try:

                old_date = datetime.fromisoformat(result[0])

                if old_date > now:
                    now = old_date

            except ValueError:
                pass

        new_date = now + timedelta(days=days)

        await db.execute(

            """
            UPDATE users
            SET paid_until=?
            WHERE user_id=?
            """,

            (new_date.isoformat(), user_id)

        )

        await db.commit()

    return new_date


# ============================================================
#                    СТАРТОВАЯ КОМАНДА
# ============================================================

@dp.message(CommandStart())
async def command_start(message: Message):

    args = message.text.split(maxsplit=1)

    referrer = None

    if len(args) > 1:

        payload = args[1]

        if payload.startswith("ref_"):

            try:
                referrer = int(payload.replace("ref_", ""))
            except ValueError:
                referrer = None

    await register_user(message, referrer)

    await message.answer(

        "✨ <b>Добро пожаловать!</b>\n\n"

        "Рады видеть тебя в нашем боте.\n"

        "Здесь ты найдёшь полезные материалы, "
        "игровые разделы и закрытый приват.\n\n"

        "👇 <b>Выбирай нужный раздел:</b>",

        reply_markup=await main_keyboard()

    )


# ============================================================
#                    МОЙ ID
# ============================================================

@dp.message(Command("id"))
async def command_id(message: Message):

    await message.answer(

        f"🆔 Твой ID:\n"
        f"<code>{message.from_user.id}</code>"

    )


# ============================================================
#                    ОБРАБОТКА КНОПОК
# ============================================================

@dp.callback_query(F.data == "menu:back")
async def go_back(call: CallbackQuery):

    await call.message.answer(

        "🏠 <b>Главное меню</b>",

        reply_markup=await main_keyboard()

    )

    await call.answer()


# ============================================================
#                    БЕСПЛАТНОЕ МЕНЮ
# ============================================================

@dp.callback_query(F.data == "menu:free")
async def free_menu(call: CallbackQuery):

    keyboard = InlineKeyboardMarkup(

        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="🎮 Игры и гайды",
                    callback_data="menu:games"
                )
            ],

            [
                InlineKeyboardButton(
                    text="💰 Способы заработка",
                    callback_data="menu:daily"
                )
            ],

            [
                await make_button("back")
            ]

        ]

    )

    await call.message.answer(

        "🆓 <b>БЕСПЛАТНОЕ МЕНЮ</b>\n\n"

        "Добро пожаловать в бесплатный раздел!\n\n"

        "Здесь находятся открытые материалы "
        "и полезная информация.",

        reply_markup=keyboard

    )

    await call.answer()


# ============================================================
#                    ПЛАТНЫЙ ПРИВАТ
# ============================================================

@dp.callback_query(F.data == "menu:paid")
async def paid_menu(call: CallbackQuery):

    user_id = call.from_user.id

    if await check_paid_access(user_id):

        await call.message.answer(

            "🔐 <b>ПЛАТНЫЙ ПРИВАТ</b>\n\n"

            "✅ Твой доступ активен!\n\n"

            "Добро пожаловать в закрытый раздел."

        )

    else:

        keyboard = InlineKeyboardMarkup(

            inline_keyboard=[

                [
                    await make_button("payments")
                ],

                [
                    await make_button("support")
                ],

                [
                    await make_button("back")
                ]

            ]

        )

        await call.message.answer(

            "🔒 <b>ДОСТУП ЗАКРЫТ</b>\n\n"

            "Чтобы попасть в приват, необходимо "
            "приобрести доступ.\n\n"

            "Выбери способ оплаты ниже.",

            reply_markup=keyboard

        )

    await call.answer()


# ============================================================
#                    ЗАПУСК
# ============================================================

async def main():

    await init_database()

    print("================================")
    print("       PLAYFUNPAY BOT")
    print("================================")
    print("Бот успешно запущен!")

    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())
