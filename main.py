# ============================================================
#                    PLAYFUN PAY BOT
#              Telegram Bot | Python | Aiogram 3
# ============================================================
#
# Полный рабочий код со всем заявленным функционалом:
# 1. Бесплатное меню
# 2. Платный приват
# 3. Административная панель (/admin)
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
#                  ПРОСТЫЕ СОСТОЯНИЯ (FSM)
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
    await install_default_payments()

# ============================================================
#                  СТАНДАРТНЫЕ КНОПКИ И ПЛАТЕЖИ
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

async def install_default_payments():
    async with aiosqlite.connect(DATABASE) as db:
        async with db.execute("SELECT COUNT(*) FROM payments") as cursor:
            count = await cursor.fetchone()
            if count[0] == 0:
                await db.execute(
                    "INSERT INTO payments (title, description, url) VALUES (?, ?, ?)",
                    ("Перевод на карту / СБП", "Оплата напрямую через Т-Банк или СБП. После оплаты нажмите кнопку ниже для связи с администратором.", "")
                )
                await db.execute(
                    "INSERT INTO payments (title, description, url) VALUES (?, ?, ?)",
                    ("Ozon Bank / Криптовалюта", "Быстрый способ оплаты.", "")
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
        return InlineKeyboardButton(text=title, url=url)
    return InlineKeyboardButton(text=title, callback_data=f"menu:{button_id}")

# ============================================================
#                   КЛАВИАТУРЫ МЕНЮ
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
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

async def back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [await make_button("back")]
        ]
    )

def is_admin(user_id):
    return user_id in ADMIN_IDS

# ============================================================
#                   РЕГИСТРАЦИЯ И СТАТИСТИКА
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
                (user_id, username, first_name, referrer, joined_at)
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
            await db.commit()
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
#                    ОБРАБОТЧИКИ КОМАНД И КНОПОК
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

@dp.message(Command("id"))
async def command_id(message: Message):
    await message.answer(
        f"🆔 Твой ID:\n<code>{message.from_user.id}</code>"
    )

@dp.callback_query(F.data == "menu:back")
async def go_back(call: CallbackQuery):
    clear_state(call.from_user.id)
    await call.message.answer(
        "🏠 <b>Главное меню</b>",
        reply_markup=await main_keyboard()
    )
    await call.answer()

# --- БЕСПЛАТНОЕ МЕНЮ ---
@dp.callback_query(F.data == "menu:free")
async def free_menu(call: CallbackQuery):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎮 Игры и гайды", callback_data="menu:games")],
            [InlineKeyboardButton(text="💰 Способы заработка", callback_data="menu:daily")],
            [await make_button("back")]
        ]
    )
    await call.message.answer(
        "🆓 <b>БЕСПЛАТНОЕ МЕНЮ</b>\n\n"
        "Добро пожаловать в бесплатный раздел!\n\n"
        "Здесь находятся открытые материалы и полезная информация.",
        reply_markup=keyboard
    )
    await call.answer()

# --- ИГРЫ И ГАЙДЫ ---
@dp.callback_query(F.data == "menu:games")
async def games_menu(call: CallbackQuery):
    await call.message.answer(
        "🎮 <b>Игры и гайды</b>\n\n"
        "Здесь собраны полезные гайды по играм, аккаунтам и цифровым товарам.\n\n"
        "• Безопасные сделки\n"
        "• Советы по торговле на маркетплейсах.",
        reply_markup=await back_keyboard()
    )
    await call.answer()

# --- ЕЖЕДНЕВНЫЙ ЗАРАБОТОК ---
@dp.callback_query(F.data == "menu:daily")
async def daily_menu(call: CallbackQuery):
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("SELECT title, content FROM daily_posts ORDER BY id DESC LIMIT 5")
        posts = await cursor.fetchall()

    text = "💰 <b>Ежедневные способы заработка</b>\n\n"
    if posts:
        for p in posts:
            text += f"📌 <b>{escape(p[0])}</b>\n{escape(p[1])}\n\n"
    else:
        text += "В данный момент новые способы заработка добавляются администрацией. Заглядывайте сюда почаще!"

    await call.message.answer(text, reply_markup=await back_keyboard())
    await call.answer()

# --- ПЛАТНЫЙ ПРИВАТ ---
@dp.callback_query(F.data == "menu:paid")
async def paid_menu(call: CallbackQuery):
    user_id = call.from_user.id
    if await check_paid_access(user_id):
        await call.message.answer(
            "🔐 <b>ПЛАТНЫЙ ПРИВАТ</b>\n\n"
            "✅ Твой доступ активен!\n\n"
            "Добро пожаловать в закрытый раздел с эксклюзивным контентом."
        )
    else:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [await make_button("payments")],
                [await make_button("promo")],
                [await make_button("support")],
                [await make_button("back")]
            ]
        )
        await call.message.answer(
            "🔒 <b>ДОСТУП ЗАКРЫТ</b>\n\n"
            "Чтобы попасть в приват, необходимо приобрести доступ или активировать промокод.\n\n"
            "Выберите раздел ниже:",
            reply_markup=keyboard
        )
    await call.answer()

# --- СПОСОБЫ ОПЛАТЫ ---
@dp.callback_query(F.data == "menu:payments")
async def payments_menu(call: CallbackQuery):
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("SELECT title, description, url FROM payments")
        methods = await cursor.fetchall()

    text = "💳 <b>Способы оплаты доступа</b>\n\n"
    for m in methods:
        text += f"🔹 <b>{escape(m[0])}</b>\n{escape(m[1])}\n"
        if m[2]:
            text += f"🔗 Ссылка: {escape(m[2])}\n"
        text += "\n"

    text += "После оплаты нажмите кнопку ниже для связи с поддержкой и выдачи доступа."

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [await make_button("support")],
            [await make_button("back")]
        ]
    )
    await call.message.answer(text, reply_markup=keyboard)
    await call.answer()

# --- РЕФЕРАЛЬНАЯ СИСТЕМА ---
@dp.callback_query(F.data == "menu:referral")
async def referral_menu(call: CallbackQuery):
    user_id = call.from_user.id
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"

    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users WHERE referrer=?", (user_id,))
        count = await cursor.fetchone()
        refs_count = count[0] if count else 0

    text = (
        "👥 <b>Реферальная система</b>\n\n"
        "Приглашайте друзей по вашей личной ссылке:\n\n"
        f"🔗 <code>{ref_link}</code>\n\n"
        f"👤 Приглашено пользователей: <b>{refs_count}</b>"
    )
    await call.message.answer(text, reply_markup=await back_keyboard())
    await call.answer()

# --- ПРОМОКОДЫ ---
@dp.callback_query(F.data == "menu:promo")
async def promo_prompt(call: CallbackQuery):
    set_state(call.from_user.id, "waiting_promo")
    await call.message.answer(
        "🎟 <b>Активация промокода</b>\n\n"
        "Отправьте ваш промокод ответным сообщением в чат.",
        reply_markup=await back_keyboard()
    )
    await call.answer()

# --- ПОДДЕРЖКА ---
@dp.callback_query(F.data == "menu:support")
async def support_prompt(call: CallbackQuery):
    set_state(call.from_user.id, "waiting_support")
    await call.message.answer(
        "🆘 <b>Служба поддержки</b>\n\n"
        "Опишите ваш вопрос или отправьте чек об оплате одним сообщением.",
        reply_markup=await back_keyboard()
    )
    await call.answer()

# --- ОБРАБОТКА ТЕКСТОВЫХ СОСТОЯНИЙ ---
@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text_states(message: Message):
    user_id = message.from_user.id
    state = get_state(user_id)

    if state == "waiting_promo":
        clear_state(user_id)
        code = message.text.strip()
        async with aiosqlite.connect(DATABASE) as db:
            cursor = await db.execute("SELECT days, uses_left FROM promos WHERE code=?", (code,))
            promo = await cursor.fetchone()

            if not promo:
                await message.answer("❌ Промокод не найден или не существует.", reply_markup=await main_keyboard())
                return

            days, uses_left = promo

            cur = await db.execute("SELECT 1 FROM promo_uses WHERE user_id=? AND code=?", (user_id, code))
            used = await cur.fetchone()

            if used:
                await message.answer("❌ Вы уже активировали этот промокод ранее!", reply_markup=await main_keyboard())
                return

            if uses_left <= 0:
                await message.answer("❌ У этого промокода закончились использования.", reply_markup=await main_keyboard())
                return

            await give_paid_access(user_id, days)
            await db.execute("UPDATE promos SET uses_left = uses_left - 1 WHERE code=?", (code,))
            await db.execute("INSERT INTO promo_uses (user_id, code) VALUES (?, ?)", (user_id, code))
            await db.commit()

        await message.answer(f"✅ <b>Успешно!</b> Промокод активирован. Добавлено дней привата: <b>{days}</b>.", reply_markup=await main_keyboard())

    elif state == "waiting_support":
        clear_state(user_id)
        text = message.text
        async with aiosqlite.connect(DATABASE) as db:
            await db.execute(
                "INSERT INTO support_messages (user_id, message, created_at) VALUES (?, ?, ?)",
                (user_id, text, datetime.now().isoformat())
            )
            await db.commit()

        await message.answer("✅ Ваше сообщение отправлено в поддержку! Ожидайте ответа.", reply_markup=await main_keyboard())

        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"🆘 <b>Новое обращение в поддержку!</b>\n\n"
                    f"От: {message.from_user.full_name} (<code>{user_id}</code>)\n"
                    f"Сообщение: {escape(text)}"
                )
            except Exception:
                pass

    elif state == "waiting_broadcast" and is_admin(user_id):
        clear_state(user_id)
        text = message.text
        async with aiosqlite.connect(DATABASE) as db:
            cursor = await db.execute("SELECT user_id FROM users WHERE banned=0")
            users = await cursor.fetchall()

        success = 0
        failed = 0
        for u in users:
            try:
                await bot.send_message(u[0], text)
                success += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1

        await message.answer(f"📢 <b>Рассылка завершена!</b>\n\n✅ Успешно: {success}\n❌ Ошибок: {failed}")

    elif state == "waiting_add_promo" and is_admin(user_id):
        clear_state(user_id)
        parts = message.text.split()
        if len(parts) >= 3:
            code, days_str, uses_str = parts[0], parts[1], parts[2]
            try:
                days = int(days_str)
                uses = int(uses_str)
                async with aiosqlite.connect(DATABASE) as db:
                    await db.execute(
                        "INSERT OR REPLACE INTO promos (code, days, uses_left) VALUES (?, ?, ?)",
                        (code, days, uses)
                    )
                    await db.commit()
                await message.answer(f"✅ Промокод <code>{code}</code> успешно добавлен ({days} дней, {uses} использований).")
            except ValueError:
                await message.answer("❌ Ошибка в формате чисел. Пример: <code>PROMO 30 100</code>")
        else:
            await message.answer("❌ Неверный формат. Введите: <code>КОД ДНИ КОЛИЧЕСТВО</code>")

    elif state and state.startswith("editing_btn:") and is_admin(user_id):
        btn_id = state.split(":")[-1]
        clear_state(user_id)
        new_title = message.text.strip()
        async with aiosqlite.connect(DATABASE) as db:
            await db.execute("UPDATE buttons SET title=? WHERE button_id=?", (new_title, btn_id))
            await db.commit()
        await message.answer(f"✅ Кнопка <code>{btn_id}</code> успешно переименована на: <b>{new_title}</b>", reply_markup=await main_keyboard())

    else:
        await message.answer("Используйте кнопки меню для навигации.", reply_markup=await main_keyboard())

# ============================================================
#                   АДМИН-ПАНЕЛЬ
# ============================================================

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
            [InlineKeyboardButton(text="📢 Сделать рассылку", callback_data="admin:broadcast")],
            [InlineKeyboardButton(text="🎟 Добавить промокод", callback_data="admin:add_promo")],
            [InlineKeyboardButton(text="⚙️ Редактировать кнопки", callback_data="admin:buttons")],
            [InlineKeyboardButton(text="🆘 Обращения поддержки", callback_data="admin:support")],
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="menu:back")],
        ]
    )
    await message.answer("👑 <b>Административная панель</b>", reply_markup=keyboard)

@dp.callback_query(F.data == "admin:stats")
async def admin_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return

    async with aiosqlite.connect(DATABASE) as db:
        cur1 = await db.execute("SELECT COUNT(*) FROM users")
        total_users = (await cur1.fetchone())[0]

        cur2 = await db.execute("SELECT COUNT(*) FROM users WHERE paid_until > datetime('now')")
        active_paid = (await cur2.fetchone())[0]

        cur3 = await db.execute("SELECT COUNT(*) FROM support_messages")
        total_support = (await cur3.fetchone())[0]

    text = (
        "📊 <b>Статистика бота</b>\n\n"
        f"👥 Всего пользователей: <b>{total_users}</b>\n"
        f"🔐 Активных подписок: <b>{active_paid}</b>\n"
        f"🆘 Обращений в поддержку: <b>{total_support}</b>"
    )
    await call.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад в админку", callback_data="admin:back_to_main")]]))
    await call.answer()

@dp.callback_query(F.data == "admin:back_to_main")
async def admin_back_to_main(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    await admin_panel(call.message)
    await call.answer()

@dp.callback_query(F.data == "admin:broadcast")
async def admin_broadcast(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    set_state(call.from_user.id, "waiting_broadcast")
    await call.message.answer("📢 Отправьте текст для рассылки всем пользователям бота:")
    await call.answer()

@dp.callback_query(F.data == "admin:add_promo")
async def admin_add_promo_prompt(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    set_state(call.from_user.id, "waiting_add_promo")
    await call.message.answer("🎟 Введите промокод, количество дней и лимит активаций через пробел.\nПример: <code>START2026 7 50</code>")
    await call.answer()

@dp.callback_query(F.data == "admin:buttons")
async def admin_buttons_list(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return

    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("SELECT button_id, title FROM buttons")
        buttons = await cursor.fetchall()

    keyboard = []
    for b in buttons:
        keyboard.append([InlineKeyboardButton(text=f"✏️ {b[1]} ({b[0]})", callback_data=f"admin:edit_btn:{b[0]}")])
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад в админку", callback_data="admin:back_to_main")])

    await call.message.answer("⚙️ <b>Управление кнопками</b>\nВыберите кнопку для изменения названия:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await call.answer()

@dp.callback_query(F.data.startswith("admin:edit_btn:"))
async def admin_edit_button_start(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    btn_id = call.data.split(":")[-1]
    set_state(call.from_user.id, f"editing_btn:{btn_id}")
    await call.message.answer(f"✏️ Введите новое название для кнопки <code>{btn_id}</code>:")
    await call.answer()

@dp.callback_query(F.data == "admin:support")
async def admin_support_list(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return

    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute("SELECT id, user_id, message, created_at FROM support_messages ORDER BY id DESC LIMIT 5")
        msgs = await cursor.fetchall()

    if not msgs:
        await call.message.answer("📭 Нет новых обращений в поддержку.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:back_to_main")]]))
        await call.answer()
        return

    text = "🆘 <b>Последние обращения в поддержку:</b>\n\n"
    for m in msgs:
        text += f"ID заявки: <b>#{m[0]}</b> | От: <code>{m[1]}</code>\nТекст: {escape(m[2])}\nВремя: {m[3]}\n-------------------\n"

    await call.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад в админку", callback_data="admin:back_to_main")]]))
    await call.answer()

# ============================================================
#                    ЗАПУСК БОТА
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
