"""
PLAYFUNPAY BOT — single-file production-oriented starter
Python 3.11+
Dependencies:
    aiogram==3.22.0
    aiosqlite==0.21.0
    python-dotenv==1.1.1

Environment variables:
    BOT_TOKEN=...
    ADMIN_IDS=123456789,987654321
    DATABASE_PATH=playfunpay.db   # optional
    SUPPORT_USERNAME=@your_support # optional
    DEFAULT_CURRENCY=₽            # optional

Important:
- Bank-transfer payments are reviewed manually by an administrator.
- Never put a bot token into GitHub. Set it as a hosting environment variable.
- Back up the SQLite database regularly.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import html
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramNetworkError,
)
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LabeledPrice,
)
from dotenv import load_dotenv


# =============================================================================
# CONFIGURATION
# =============================================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(value.strip())
    for value in os.getenv("ADMIN_IDS", "").split(",")
    if value.strip().isdigit()
}
DATABASE_PATH = os.getenv("DATABASE_PATH", "playfunpay.db")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "").strip()
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "₽").strip() or "₽"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Add it to hosting environment variables.")
if not ADMIN_IDS:
    raise RuntimeError("ADMIN_IDS is missing. Add at least one numeric Telegram user ID.")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("playfunpay")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

# In-memory input states are intentionally temporary. Persistent business data
# (orders, users, settings, content) is stored in SQLite.
USER_STATES: dict[int, dict[str, Any]] = {}

# Callback data is deliberately short to stay below Telegram's 64-byte limit.
MAX_TEXT_LENGTH = 3500
BROADCAST_DELAY = 0.05


# =============================================================================
# DEFAULT CONTENT
# =============================================================================

DEFAULT_BUTTONS: dict[str, str] = {
    "channel": "📢 Наш канал",
    "ads": "💎 Реклама",
    "about": "🛒 Что в ПРИВАТЕ?",
    "buy": "🔐 Купить доступ",
    "free": "🆓 Бесплатное меню",
    "daily": "💰 Способы заработка",
    "games": "🎮 Игры и гайды",
    "referral": "👥 Реферальная система",
    "promo": "🎟 Ввести промокод",
    "support": "🆘 Поддержка",
    "payments": "💳 Способы оплаты",
    "back": "⬅️ Назад в меню",
    "roblox": "🤖 Roblox",
    "standoff": "⚡ Standoff 2",
    "brawl": "🌵 Brawl Stars",
    "pubg": "🔫 PUBG Mobile",
    "clash": "🏰 Clash of Clans",
    "safety": "📜 Инструкция по безопасности",
}

DEFAULT_TEXTS: dict[str, str] = {
    "welcome": (
        "<b>PlayFunpay Team | Официальный бот ⚡</b>\n\n"
        "Привет! Ты в команде. Используй кнопки ниже, чтобы "
        "<b>узнавать о материалах и возможностях проекта.</b> 👇"
    ),
    "about": (
        "🛒 <b>Что входит в ПРИВАТ:</b>\n\n"
        "💸 Способы заработка\n"
        "⭐ Способы фарма отзывов\n"
        "🔎 Приватные гайды\n"
        "📚 Разное (софт и фишки)\n\n"
        "<i>Выбери игру, чтобы узнать подробнее:</i>"
    ),
    "paid_locked": (
        "🔒 <b>Доступ закрыт</b>\n\n"
        "Чтобы открыть закрытый раздел, выбери тариф и оплати доступ."
    ),
    "paid_open": (
        "🔐 <b>ПРИВАТ АКТИВЕН</b>\n\n"
        "Твой доступ активен до: <b>{paid_until}</b>\n\n"
        "Добро пожаловать в закрытый раздел!"
    ),
    "free": (
        "🆓 <b>Бесплатное меню</b>\n\n"
        "Здесь находятся открытые материалы и полезная информация."
    ),
    "daily_empty": (
        "💰 <b>Способы заработка</b>\n\n"
        "Новые публикации появятся здесь позже. Заглядывай!"
    ),
    "games": (
        "🎮 <b>Игры и гайды</b>\n\n"
        "Выбери интересующий раздел ниже."
    ),
    "safety": (
        "📜 <b>Безопасность</b>\n\n"
        "Проверяй ссылки и адресата перед оплатой. Не передавай пароли, "
        "коды подтверждения и данные банковской карты. Используй только "
        "официальные способы связи, указанные администрацией."
    ),
    "support_prompt": (
        "🆘 <b>Поддержка</b>\n\n"
        "Напиши сообщение одним сообщением. Можно приложить фото чека "
        "или скриншот. Администратор получит обращение."
    ),
    "payment_intro": (
        "💳 <b>Оплата доступа</b>\n\n"
        "Выбери подходящий тариф ниже. После оплаты по реквизитам "
        "отправь чек в этот чат."
    ),
    "promo_prompt": (
        "🎟 <b>Активация промокода</b>\n\n"
        "Отправь промокод ответным сообщением."
    ),
    "referral": (
        "👥 <b>Реферальная система</b>\n\n"
        "Твоя ссылка:\n<code>{ref_link}</code>\n\n"
        "Приглашено пользователей: <b>{count}</b>"
    ),
    "payment_instructions": (
        "🔐 <b>Оплата доступа</b>\n\n"
        "Тариф: <b>{tariff}</b>\n"
        "Стоимость: <b>{price} {currency}</b>\n"
        "Срок: <b>{days} дн.</b>\n\n"
        "{details}\n\n"
        "После оплаты отправь сюда скриншот или фото чека. "
        "Заявка будет проверена администратором."
    ),
    "support_received": (
        "✅ Обращение отправлено. Администратор рассмотрит его "
        "и ответит при первой возможности."
    ),
}

DEFAULT_SETTINGS: dict[str, str] = {
    "channel_url": "",
    "ads_url": "",
    "payment_details": (
        "Перевод на карту / СБП.\n"
        "Реквизиты для оплаты добавьте в админ-панели."
    ),
    "support_text": "",
    "referral_bonus_days": "0",
    "referral_min_payment": "0",
    "project_name": "PlayFunpay",
    "currency": DEFAULT_CURRENCY,
    "maintenance": "0",
}

DEFAULT_TARIFFS = [
    ("30 дней", 99, 30, 1),
    ("90 дней", 249, 90, 1),
    ("365 дней", 699, 365, 1),
]


# =============================================================================
# GENERAL HELPERS
# =============================================================================

def now_local() -> datetime:
    """Use UTC internally for consistent expiration comparisons."""
    return datetime.now(timezone.utc)


def dt_to_db(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def parse_db_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def safe_html(value: Any) -> str:
    return html.escape(str(value or ""))


def truncate(value: str, limit: int = MAX_TEXT_LENGTH) -> str:
    value = str(value or "")
    return value if len(value) <= limit else value[: limit - 1] + "…"


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def set_state(user_id: int, state: str, **data: Any) -> None:
    USER_STATES[user_id] = {"state": state, **data}


def get_state(user_id: int) -> Optional[dict[str, Any]]:
    return USER_STATES.get(user_id)


def clear_state(user_id: int) -> None:
    USER_STATES.pop(user_id, None)


def button(text: str, callback: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=truncate(text, 60), callback_data=callback)


def url_button(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=truncate(text, 60), url=url)


async def db_execute(query: str, params: tuple = ()) -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(query, params)
        await db.commit()
        return cursor.lastrowid or 0


async def db_fetchone(query: str, params: tuple = ()) -> Optional[tuple]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(query, params)
        return await cursor.fetchone()


async def db_fetchall(query: str, params: tuple = ()) -> list[tuple]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(query, params)
        return await cursor.fetchall()


async def get_setting(key: str, default: str = "") -> str:
    row = await db_fetchone("SELECT value FROM settings WHERE key=?", (key,))
    return str(row[0]) if row else default


async def set_setting(key: str, value: str) -> None:
    await db_execute(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


async def get_text(key: str) -> str:
    row = await db_fetchone("SELECT body FROM texts WHERE text_key=?", (key,))
    return str(row[0]) if row else DEFAULT_TEXTS.get(key, "")


async def set_text(key: str, body: str) -> None:
    await db_execute(
        "INSERT INTO texts(text_key,body) VALUES(?,?) "
        "ON CONFLICT(text_key) DO UPDATE SET body=excluded.body",
        (key, body),
    )


async def get_button_title(key: str) -> str:
    row = await db_fetchone("SELECT title FROM buttons WHERE button_id=?", (key,))
    return str(row[0]) if row else DEFAULT_BUTTONS.get(key, key)


async def set_button_title(key: str, title: str) -> None:
    await db_execute(
        "INSERT INTO buttons(button_id,title) VALUES(?,?) "
        "ON CONFLICT(button_id) DO UPDATE SET title=excluded.title",
        (key, truncate(title, 60)),
    )


def back_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[button("⬅️ Назад в меню", "nav:home")]])


async def main_markup() -> InlineKeyboardMarkup:
    keys = ["channel", "ads", "about", "buy"]
    rows: list[list[InlineKeyboardButton]] = []
    for key in keys:
        title = await get_button_title(key)
        if key == "channel":
            url = await get_setting("channel_url")
            rows.append([url_button(title, url)] if url else [button(title, "menu:channel")])
        elif key == "ads":
            url = await get_setting("ads_url")
            rows.append([url_button(title, url)] if url else [button(title, "menu:ads")])
        else:
            rows.append([button(title, f"menu:{key}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def games_markup() -> InlineKeyboardMarkup:
    keys = ["roblox", "standoff", "brawl", "pubg", "clash", "safety"]
    rows = [[button(await get_button_title(key), f"game:{key}")] for key in keys]
    rows.append([button(await get_button_title("back"), "nav:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def free_markup() -> InlineKeyboardMarkup:
    rows = [
        [button(await get_button_title("daily"), "menu:daily")],
        [button(await get_button_title("games"), "menu:games")],
        [button(await get_button_title("referral"), "menu:referral")],
        [button(await get_button_title("back"), "nav:home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def admin_markup() -> InlineKeyboardMarkup:
    rows = [
        [button("📊 Статистика", "admin:stats"), button("👥 Пользователи", "admin:users")],
        [button("📝 Тексты разделов", "admin:texts"), button("🔘 Названия кнопок", "admin:buttons")],
        [button("💰 Тарифы и цены", "admin:tariffs"), button("💳 Реквизиты", "admin:payment")],
        [button("📚 Публикации", "admin:posts"), button("🎟 Промокоды", "admin:promos")],
        [button("📢 Рассылка", "admin:broadcast"), button("🆘 Поддержка", "admin:support")],
        [button("⚙️ Настройки", "admin:settings")],
        [button("🏠 Пользовательское меню", "nav:home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# =============================================================================
# DATABASE SCHEMA AND MIGRATIONS
# =============================================================================

async def init_database() -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL DEFAULT '',
                first_name TEXT NOT NULL DEFAULT '',
                referrer INTEGER,
                joined_at TEXT NOT NULL,
                paid_until TEXT,
                banned INTEGER NOT NULL DEFAULT 0,
                last_seen TEXT
            );

            CREATE TABLE IF NOT EXISTS buttons (
                button_id TEXT PRIMARY KEY,
                title TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS texts (
                text_key TEXT PRIMARY KEY,
                body TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tariffs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                price REAL NOT NULL CHECK(price >= 0),
                days INTEGER NOT NULL CHECK(days > 0),
                active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS payment_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tariff_id INTEGER,
                tariff_title TEXT NOT NULL,
                amount REAL NOT NULL,
                days INTEGER NOT NULL,
                receipt_file_id TEXT,
                receipt_type TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                reviewed_by INTEGER,
                admin_comment TEXT
            );

            CREATE TABLE IF NOT EXISTS promos (
                code TEXT PRIMARY KEY,
                days INTEGER NOT NULL CHECK(days > 0),
                uses_left INTEGER NOT NULL CHECK(uses_left >= 0),
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS promo_uses (
                user_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                used_at TEXT NOT NULL,
                PRIMARY KEY(user_id, code)
            );

            CREATE TABLE IF NOT EXISTS daily_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS game_contents (
                game_key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS support_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                file_id TEXT,
                file_type TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                answered_at TEXT
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_users_referrer ON users(referrer);
            CREATE INDEX IF NOT EXISTS idx_payments_status ON payment_requests(status);
            CREATE INDEX IF NOT EXISTS idx_support_status ON support_messages(status);
            """
        )

        for key, title in DEFAULT_BUTTONS.items():
            await db.execute(
                "INSERT OR IGNORE INTO buttons(button_id,title) VALUES(?,?)",
                (key, title),
            )
        for key, body in DEFAULT_TEXTS.items():
            await db.execute(
                "INSERT OR IGNORE INTO texts(text_key,body) VALUES(?,?)",
                (key, body),
            )
        for key, value in DEFAULT_SETTINGS.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
                (key, value),
            )
        count_cursor = await db.execute("SELECT COUNT(*) FROM tariffs")
        count = (await count_cursor.fetchone())[0]
        if count == 0:
            await db.executemany(
                "INSERT INTO tariffs(title,price,days,active) VALUES(?,?,?,?)",
                DEFAULT_TARIFFS,
            )
        await db.commit()

    logger.info("Database initialized")


async def audit(admin_id: int, action: str, details: str = "") -> None:
    await db_execute(
        "INSERT INTO audit_log(admin_id,action,details,created_at) VALUES(?,?,?,?)",
        (admin_id, action, details[:1000], dt_to_db(now_local())),
    )


# =============================================================================
# USERS, ACCESS, REFERRALS
# =============================================================================

async def register_user(message: Message, referrer: Optional[int]) -> None:
    user = message.from_user
    if not user:
        return
    existing = await db_fetchone("SELECT user_id FROM users WHERE user_id=?", (user.id,))
    if not existing:
        if referrer == user.id:
            referrer = None
        if referrer is not None:
            valid = await db_fetchone("SELECT user_id FROM users WHERE user_id=?", (referrer,))
            if not valid:
                referrer = None
        await db_execute(
            """
            INSERT INTO users(user_id,username,first_name,referrer,joined_at,last_seen)
            VALUES(?,?,?,?,?,?)
            """,
            (
                user.id,
                user.username or "",
                user.first_name or "",
                referrer,
                dt_to_db(now_local()),
                dt_to_db(now_local()),
            ),
        )
    else:
        await db_execute(
            "UPDATE users SET username=?,first_name=?,last_seen=? WHERE user_id=?",
            (user.username or "", user.first_name or "", dt_to_db(now_local()), user.id),
        )


async def is_banned(user_id: int) -> bool:
    row = await db_fetchone("SELECT banned FROM users WHERE user_id=?", (user_id,))
    return bool(row and row[0])


async def paid_until(user_id: int) -> Optional[datetime]:
    row = await db_fetchone("SELECT paid_until FROM users WHERE user_id=?", (user_id,))
    return parse_db_datetime(row[0]) if row else None


async def has_paid_access(user_id: int) -> bool:
    expiry = await paid_until(user_id)
    return bool(expiry and expiry > now_local())


async def grant_access(user_id: int, days: int) -> datetime:
    if days <= 0:
        raise ValueError("Access duration must be positive")
    current = await paid_until(user_id)
    start = current if current and current > now_local() else now_local()
    expiry = start + timedelta(days=days)
    await db_execute("UPDATE users SET paid_until=? WHERE user_id=?", (dt_to_db(expiry), user_id))
    return expiry


async def notify_admins(text: str) -> None:
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            logger.exception("Could not notify admin %s", admin_id)


async def send_user(user_id: int, text: str, **kwargs: Any) -> bool:
    try:
        await bot.send_message(user_id, truncate(text), **kwargs)
        return True
    except (TelegramForbiddenError, TelegramBadRequest):
        return False
    except Exception:
        logger.exception("Could not send message to %s", user_id)
        return False


# =============================================================================
# USER MENUS
# =============================================================================

@dp.message(CommandStart())
async def command_start(message: Message) -> None:
    if not message.from_user:
        return
    referrer = None
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1:
        match = re.fullmatch(r"ref_(\d+)", parts[1].strip())
        if match:
            referrer = int(match.group(1))
    await register_user(message, referrer)
    if await is_banned(message.from_user.id):
        await message.answer("⛔ Доступ к боту ограничен.")
        return
    maintenance = await get_setting("maintenance", "0")
    if maintenance == "1" and not is_admin(message.from_user.id):
        await message.answer("🛠 Бот временно находится на техническом обслуживании.")
        return
    await message.answer(await get_text("welcome"), reply_markup=await main_markup())


@dp.message(Command("id"))
async def command_id(message: Message) -> None:
    await message.answer(f"🆔 Твой Telegram ID: <code>{message.from_user.id}</code>")


@dp.message(Command("admin"))
async def command_admin(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    clear_state(message.from_user.id)
    await message.answer("<b>👑 Административная панель</b>", reply_markup=await admin_markup())


@dp.callback_query(F.data == "nav:home")
async def nav_home(call: CallbackQuery) -> None:
    clear_state(call.from_user.id)
    await call.message.answer("<b>🏠 Главное меню</b>", reply_markup=await main_markup())
    await call.answer()


@dp.callback_query(F.data == "menu:channel")
async def menu_channel(call: CallbackQuery) -> None:
    url = await get_setting("channel_url")
    text = "📢 Ссылка на канал пока не настроена."
    markup = back_markup()
    if url:
        text = "📢 Нажми кнопку ниже, чтобы открыть наш канал."
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [url_button("📢 Открыть канал", url)],
            [button(await get_button_title("back"), "nav:home")],
        ])
    await call.message.answer(text, reply_markup=markup)
    await call.answer()


@dp.callback_query(F.data == "menu:ads")
async def menu_ads(call: CallbackQuery) -> None:
    url = await get_setting("ads_url")
    text = "💎 Информация о рекламе пока не добавлена."
    markup = back_markup()
    if url:
        text = "💎 Подробности доступны по ссылке:"
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [url_button("💎 Перейти", url)],
            [button(await get_button_title("back"), "nav:home")],
        ])
    await call.message.answer(text, reply_markup=markup)
    await call.answer()


@dp.callback_query(F.data == "menu:about")
async def menu_about(call: CallbackQuery) -> None:
    await call.message.answer(
        await get_text("about"),
        reply_markup=await games_markup(),
    )
    await call.answer()


@dp.callback_query(F.data == "menu:free")
async def menu_free(call: CallbackQuery) -> None:
    await call.message.answer(await get_text("free"), reply_markup=await free_markup())
    await call.answer()


@dp.callback_query(F.data == "menu:games")
async def menu_games(call: CallbackQuery) -> None:
    await call.message.answer(await get_text("games"), reply_markup=await games_markup())
    await call.answer()


@dp.callback_query(F.data == "menu:daily")
async def menu_daily(call: CallbackQuery) -> None:
    posts = await db_fetchall(
        "SELECT title,content FROM daily_posts WHERE active=1 ORDER BY id DESC LIMIT 10"
    )
    if not posts:
        text = await get_text("daily_empty")
    else:
        chunks = ["💰 <b>Способы заработка</b>\n"]
        for title, content in posts:
            chunks.append(f"📌 <b>{safe_html(title)}</b>\n{safe_html(content)}")
        text = "\n\n".join(chunks)
    await call.message.answer(truncate(text), reply_markup=back_markup())
    await call.answer()


@dp.callback_query(F.data.startswith("game:"))
async def menu_game(call: CallbackQuery) -> None:
    game_key = call.data.split(":", 1)[1]
    if game_key not in {"roblox", "standoff", "brawl", "pubg", "clash", "safety"}:
        await call.answer("Раздел не найден", show_alert=True)
        return
    if game_key == "safety":
        content = await get_text("safety")
        title = await get_button_title("safety")
    else:
        row = await db_fetchone(
            "SELECT title,content FROM game_contents WHERE game_key=?", (game_key,)
        )
        if row:
            title, content = row
        else:
            title = await get_button_title(game_key)
            content = "Материалы для этого раздела пока не добавлены."
    await call.message.answer(
        f"<b>{safe_html(title)}</b>\n\n{safe_html(content)}",
        reply_markup=back_markup(),
    )
    await call.answer()


@dp.callback_query(F.data == "menu:buy")
async def menu_buy(call: CallbackQuery) -> None:
    if await has_paid_access(call.from_user.id):
        expiry = await paid_until(call.from_user.id)
        await call.message.answer(
            await get_text("paid_open").format(
                paid_until=expiry.strftime("%d.%m.%Y %H:%M UTC") if expiry else "—"
            ),
            reply_markup=back_markup(),
        )
        await call.answer()
        return
    tariffs = await db_fetchall(
        "SELECT id,title,price,days FROM tariffs WHERE active=1 ORDER BY days"
    )
    if not tariffs:
        await call.message.answer("Сейчас нет доступных тарифов. Обратись в поддержку.")
        await call.answer()
        return
    rows = [
        [button(f"🔐 {title} — {price:g} {await get_setting('currency', DEFAULT_CURRENCY)}",
                f"tariff:{tariff_id}")]
        for tariff_id, title, price, days in tariffs
    ]
    rows.append([button(await get_button_title("back"), "nav:home")])
    await call.message.answer(await get_text("payment_intro"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@dp.callback_query(F.data.startswith("tariff:"))
async def choose_tariff(call: CallbackQuery) -> None:
    try:
        tariff_id = int(call.data.split(":", 1)[1])
    except ValueError:
        await call.answer("Некорректный тариф", show_alert=True)
        return
    tariff = await db_fetchone(
        "SELECT id,title,price,days FROM tariffs WHERE id=? AND active=1", (tariff_id,)
    )
    if not tariff:
        await call.answer("Тариф больше недоступен", show_alert=True)
        return
    _, title, price, days = tariff
    details = await get_setting("payment_details", "")
    currency = await get_setting("currency", DEFAULT_CURRENCY)
    text = await get_text("payment_instructions")
    text = text.format(
        tariff=safe_html(title),
        price=f"{price:g}",
        currency=safe_html(currency),
        days=days,
        details=safe_html(details),
    )
    request_id = await db_execute(
        """
        INSERT INTO payment_requests(
            user_id,tariff_id,tariff_title,amount,days,status,created_at
        ) VALUES(?,?,?,?,?,'awaiting_receipt',?)
        """,
        (
            call.from_user.id, tariff_id, title, price, days, dt_to_db(now_local())
        ),
    )
    set_state(call.from_user.id, "waiting_receipt", request_id=request_id)
    await call.message.answer(text + "\n\n📎 Отправь фото или файл чека.", reply_markup=back_markup())
    await call.answer()


@dp.callback_query(F.data == "menu:referral")
async def menu_referral(call: CallbackQuery) -> None:
    me = await bot.get_me()
    count_row = await db_fetchone(
        "SELECT COUNT(*) FROM users WHERE referrer=?", (call.from_user.id,)
    )
    count = count_row[0] if count_row else 0
    ref_link = f"https://t.me/{me.username}?start=ref_{call.from_user.id}"
    text = await get_text("referral")
    await call.message.answer(
        text.format(ref_link=ref_link, count=count),
        reply_markup=back_markup(),
    )
    await call.answer()


@dp.callback_query(F.data == "menu:promo")
async def menu_promo(call: CallbackQuery) -> None:
    set_state(call.from_user.id, "waiting_promo")
    await call.message.answer(await get_text("promo_prompt"), reply_markup=back_markup())
    await call.answer()


@dp.callback_query(F.data == "menu:support")
async def menu_support(call: CallbackQuery) -> None:
    set_state(call.from_user.id, "waiting_support")
    extra = await get_setting("support_text", "")
    text = await get_text("support_prompt")
    if extra:
        text += "\n\n" + safe_html(extra)
    if SUPPORT_USERNAME:
        text += f"\n\nКонтакт: {safe_html(SUPPORT_USERNAME)}"
    await call.message.answer(text, reply_markup=back_markup())
    await call.answer()


@dp.callback_query(F.data == "menu:payments")
async def menu_payments(call: CallbackQuery) -> None:
    await call.message.answer(
        await get_text("payment_intro"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [button("🔐 Выбрать тариф", "menu:buy")],
            [button(await get_button_title("back"), "nav:home")],
        ]),
    )
    await call.answer()


# =============================================================================
# USER INPUTS: RECEIPTS, PROMOS, SUPPORT
# =============================================================================

@dp.message(F.photo | F.document)
async def handle_media(message: Message) -> None:
    if not message.from_user:
        return
    state = get_state(message.from_user.id)
    if not state:
        return
    user_id = message.from_user.id

    if state["state"] == "waiting_receipt":
        file_id = message.photo[-1].file_id if message.photo else message.document.file_id
        file_type = "photo" if message.photo else "document"
        request_id = int(state["request_id"])
        await db_execute(
            """
            UPDATE payment_requests
            SET receipt_file_id=?,receipt_type=?,status='pending'
            WHERE id=? AND user_id=? AND status='awaiting_receipt'
            """,
            (file_id, file_type, request_id, user_id),
        )
        clear_state(user_id)
        await message.answer(
            "✅ Чек получен. Заявка отправлена на проверку. "
            "Доступ будет выдан после подтверждения оплаты.",
            reply_markup=await main_markup(),
        )
        user = message.from_user
        caption = (
            f"💳 <b>Новая заявка на оплату #{request_id}</b>\n"
            f"Пользователь: {safe_html(user.full_name)} "
            f"(<code>{user_id}</code>)\n"
            f"Тариф: <b>{safe_html(str((await db_fetchone('SELECT tariff_title FROM payment_requests WHERE id=?',(request_id,)) or ['—'])[0]))}</b>\n"
            "Проверь оплату и подтверди или отклони заявку."
        )
        admin_kb = InlineKeyboardMarkup(inline_keyboard=[
            [button("✅ Подтвердить", f"pay:approve:{request_id}"),
             button("❌ Отклонить", f"pay:reject:{request_id}")],
        ])
        for admin_id in ADMIN_IDS:
            try:
                if file_type == "photo":
                    await bot.send_photo(admin_id, file_id, caption=caption, reply_markup=admin_kb)
                else:
                    await bot.send_document(admin_id, file_id, caption=caption, reply_markup=admin_kb)
            except Exception:
                logger.exception("Failed to forward receipt to admin %s", admin_id)
        return

    if state["state"] == "waiting_support":
        file_id = message.photo[-1].file_id if message.photo else message.document.file_id
        file_type = "photo" if message.photo else "document"
        support_id = await db_execute(
            """
            INSERT INTO support_messages(user_id,message,file_id,file_type,created_at)
            VALUES(?,?,?,?,?)
            """,
            (user_id, message.caption or "[Вложение]", file_id, file_type, dt_to_db(now_local())),
        )
        clear_state(user_id)
        await message.answer(await get_text("support_received"), reply_markup=await main_markup())
        for admin_id in ADMIN_IDS:
            try:
                caption = (
                    f"🆘 <b>Обращение #{support_id}</b>\n"
                    f"От: {safe_html(message.from_user.full_name)} "
                    f"(<code>{user_id}</code>)\n"
                    f"{safe_html(message.caption or '[Вложение]')}"
                )
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [button("✉️ Ответить", f"support:reply:{support_id}")]
                ])
                if file_type == "photo":
                    await bot.send_photo(admin_id, file_id, caption=caption, reply_markup=kb)
                else:
                    await bot.send_document(admin_id, file_id, caption=caption, reply_markup=kb)
            except Exception:
                logger.exception("Could not forward support attachment")
        return


@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    state = get_state(user_id)
    if not state:
        await message.answer("Используй кнопки меню для навигации.", reply_markup=await main_markup())
        return
    text = (message.text or "").strip()
    kind = state["state"]

    if kind == "waiting_promo":
        clear_state(user_id)
        code = text.upper()
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute(
                "SELECT days,uses_left,active FROM promos WHERE code=?", (code,)
            )
            promo = await cur.fetchone()
            used_cur = await db.execute(
                "SELECT 1 FROM promo_uses WHERE user_id=? AND code=?", (user_id, code)
            )
            used = await used_cur.fetchone()
            if not promo or not promo[2]:
                await db.rollback()
                await message.answer("❌ Промокод не найден или отключён.", reply_markup=await main_markup())
                return
            if used:
                await db.rollback()
                await message.answer("❌ Ты уже использовал этот промокод.", reply_markup=await main_markup())
                return
            if promo[1] <= 0:
                await db.rollback()
                await message.answer("❌ Лимит активаций промокода закончился.", reply_markup=await main_markup())
                return
            expiry = await paid_until(user_id)
            start = expiry if expiry and expiry > now_local() else now_local()
            new_expiry = start + timedelta(days=int(promo[0]))
            await db.execute(
                "UPDATE users SET paid_until=? WHERE user_id=?",
                (dt_to_db(new_expiry), user_id),
            )
            await db.execute(
                "UPDATE promos SET uses_left=uses_left-1 WHERE code=? AND uses_left>0",
                (code,),
            )
            await db.execute(
                "INSERT INTO promo_uses(user_id,code,used_at) VALUES(?,?,?)",
                (user_id, code, dt_to_db(now_local())),
            )
            await db.commit()
        await message.answer(
            f"✅ Промокод активирован! Добавлено дней: <b>{promo[0]}</b>.\n"
            f"Доступ до: <b>{new_expiry.strftime('%d.%m.%Y %H:%M UTC')}</b>",
            reply_markup=await main_markup(),
        )
        return

    if kind == "waiting_support":
        clear_state(user_id)
        support_id = await db_execute(
            "INSERT INTO support_messages(user_id,message,created_at) VALUES(?,?,?)",
            (user_id, text[:3000], dt_to_db(now_local())),
        )
        await message.answer(await get_text("support_received"), reply_markup=await main_markup())
        await notify_admins(
            f"🆘 <b>Обращение #{support_id}</b>\n"
            f"От: {safe_html(message.from_user.full_name)} (<code>{user_id}</code>)\n"
            f"{safe_html(text[:2500])}"
        )
        return

    if is_admin(user_id):
        await handle_admin_input(message, state, text)
        return

    clear_state(user_id)
    await message.answer("Используй кнопки меню.", reply_markup=await main_markup())


# =============================================================================
# PAYMENT REVIEW
# =============================================================================

@dp.callback_query(F.data.startswith("pay:"))
async def payment_review(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Недостаточно прав", show_alert=True)
        return
    parts = call.data.split(":")
    if len(parts) != 3:
        await call.answer("Некорректная заявка", show_alert=True)
        return
    action, request_id = parts[1], int(parts[2])
    row = await db_fetchone(
        "SELECT user_id,tariff_title,amount,days,status FROM payment_requests WHERE id=?",
        (request_id,),
    )
    if not row:
        await call.answer("Заявка не найдена", show_alert=True)
        return
    user_id, tariff_title, amount, days, status = row
    if status != "pending":
        await call.answer("Эта заявка уже обработана", show_alert=True)
        return

    if action == "approve":
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute(
                "SELECT status FROM payment_requests WHERE id=?", (request_id,)
            )
            current = await cur.fetchone()
            if not current or current[0] != "pending":
                await db.rollback()
                await call.answer("Заявка уже обработана", show_alert=True)
                return
            expiry = await paid_until(user_id)
            start = expiry if expiry and expiry > now_local() else now_local()
            new_expiry = start + timedelta(days=int(days))
            await db.execute(
                "UPDATE users SET paid_until=? WHERE user_id=?",
                (dt_to_db(new_expiry), user_id),
            )
            await db.execute(
                """
                UPDATE payment_requests SET status='approved',reviewed_at=?,reviewed_by=?
                WHERE id=? AND status='pending'
                """,
                (dt_to_db(now_local()), call.from_user.id, request_id),
            )
            await db.commit()
        await audit(call.from_user.id, "payment_approved", f"request={request_id}; user={user_id}")
        await send_user(
            user_id,
            "✅ <b>Оплата подтверждена!</b>\n\n"
            f"Тариф: {safe_html(tariff_title)}\n"
            f"Добавлено дней: <b>{days}</b>\n"
            f"Доступ активен до: <b>{new_expiry.strftime('%d.%m.%Y %H:%M UTC')}</b>",
        )
        await call.message.answer(f"✅ Заявка #{request_id} подтверждена. Доступ выдан.")
        await call.answer("Готово")
    elif action == "reject":
        await db_execute(
            """
            UPDATE payment_requests SET status='rejected',reviewed_at=?,reviewed_by=?
            WHERE id=? AND status='pending'
            """,
            (dt_to_db(now_local()), call.from_user.id, request_id),
        )
        await audit(call.from_user.id, "payment_rejected", f"request={request_id}; user={user_id}")
        await send_user(
            user_id,
            "❌ <b>Заявка на оплату отклонена.</b>\n"
            "Если считаешь, что произошла ошибка, напиши в поддержку.",
        )
        await call.message.answer(f"❌ Заявка #{request_id} отклонена.")
        await call.answer("Отклонено")
    else:
        await call.answer("Неизвестное действие", show_alert=True)


# =============================================================================
# ADMIN: INPUT STATE HANDLER
# =============================================================================

async def handle_admin_input(message: Message, state: dict[str, Any], text: str) -> None:
    if not is_admin(message.from_user.id):
        clear_state(message.from_user.id)
        return
    kind = state["state"]
    admin_id = message.from_user.id

    if kind == "admin_edit_button":
        key = state["key"]
        await set_button_title(key, text)
        clear_state(admin_id)
        await audit(admin_id, "button_title_changed", key)
        await message.answer("✅ Название кнопки обновлено.", reply_markup=await admin_markup())
        return

    if kind == "admin_edit_text":
        key = state["key"]
        await set_text(key, text[:MAX_TEXT_LENGTH])
        clear_state(admin_id)
        await audit(admin_id, "section_text_changed", key)
        await message.answer("✅ Текст раздела сохранён.", reply_markup=await admin_markup())
        return

    if kind == "admin_setting":
        key = state["key"]
        await set_setting(key, text[:1000])
        clear_state(admin_id)
        await audit(admin_id, "setting_changed", key)
        await message.answer("✅ Настройка сохранена.", reply_markup=await admin_markup())
        return

    if kind == "admin_game_content":
        key = state["key"]
        title = state.get("title", await get_button_title(key))
        await db_execute(
            """
            INSERT INTO game_contents(game_key,title,content) VALUES(?,?,?)
            ON CONFLICT(game_key) DO UPDATE SET title=excluded.title,content=excluded.content
            """,
            (key, title, text[:MAX_TEXT_LENGTH]),
        )
        clear_state(admin_id)
        await audit(admin_id, "game_content_changed", key)
        await message.answer("✅ Материал игры сохранён.", reply_markup=await admin_markup())
        return

    if kind == "admin_new_post":
        if "|" not in text:
            await message.answer("Формат: <code>Заголовок | Текст публикации</code>")
            return
        title, content = [part.strip() for part in text.split("|", 1)]
        if not title or not content:
            await message.answer("Заголовок и текст не должны быть пустыми.")
            return
        await db_execute(
            "INSERT INTO daily_posts(title,content,created_at) VALUES(?,?,?)",
            (title[:150], content[:3000], dt_to_db(now_local())),
        )
        clear_state(admin_id)
        await audit(admin_id, "daily_post_created", title)
        await message.answer("✅ Публикация добавлена.", reply_markup=await admin_markup())
        return

    if kind == "admin_new_promo":
        parts = text.split()
        if len(parts) != 3:
            await message.answer("Формат: <code>КОД ДНИ КОЛИЧЕСТВО</code>\nПример: <code>START 7 100</code>")
            return
        code, days_raw, uses_raw = parts
        try:
            days, uses = int(days_raw), int(uses_raw)
            if days <= 0 or uses < 0 or not re.fullmatch(r"[A-Za-z0-9_-]{3,32}", code):
                raise ValueError
        except ValueError:
            await message.answer("Проверь данные: дни > 0, лимит >= 0, код 3–32 символа.")
            return
        await db_execute(
            """
            INSERT INTO promos(code,days,uses_left,active,created_at) VALUES(?,?,?,1,?)
            ON CONFLICT(code) DO UPDATE SET days=excluded.days,uses_left=excluded.uses_left,active=1
            """,
            (code.upper(), days, uses, dt_to_db(now_local())),
        )
        clear_state(admin_id)
        await audit(admin_id, "promo_created", code.upper())
        await message.answer("✅ Промокод создан/обновлён.", reply_markup=await admin_markup())
        return

    if kind == "admin_broadcast":
        clear_state(admin_id)
        users = await db_fetchall("SELECT user_id FROM users WHERE banned=0")
        success = failed = 0
        status = await message.answer(f"📢 Начинаю рассылку для {len(users)} пользователей…")
        for (target_id,) in users:
            try:
                await bot.send_message(target_id, truncate(text))
                success += 1
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after + 1)
                try:
                    await bot.send_message(target_id, truncate(text))
                    success += 1
                except Exception:
                    failed += 1
            except (TelegramForbiddenError, TelegramBadRequest):
                failed += 1
            except TelegramNetworkError:
                failed += 1
                await asyncio.sleep(1)
            except Exception:
                failed += 1
                logger.exception("Broadcast failed for %s", target_id)
            await asyncio.sleep(BROADCAST_DELAY)
        await audit(admin_id, "broadcast", f"success={success}; failed={failed}")
        await status.edit_text(
            f"📢 <b>Рассылка завершена</b>\n\n"
            f"✅ Доставлено: {success}\n❌ Не доставлено: {failed}"
        )
        return

    if kind == "admin_tariff_new":
        # Format: title | price | days
        parts = [part.strip() for part in text.split("|")]
        if len(parts) != 3:
            await message.answer("Формат: <code>Название | Цена | Дни</code>")
            return
        title, price_raw, days_raw = parts
        try:
            price = float(price_raw.replace(",", "."))
            days = int(days_raw)
            if price < 0 or days <= 0 or not title:
                raise ValueError
        except ValueError:
            await message.answer("Цена должна быть >= 0, срок — целым числом больше 0.")
            return
        await db_execute(
            "INSERT INTO tariffs(title,price,days,active) VALUES(?,?,?,1)",
            (title[:80], price, days),
        )
        clear_state(admin_id)
        await audit(admin_id, "tariff_created", title)
        await message.answer("✅ Тариф добавлен.", reply_markup=await admin_markup())
        return

    if kind == "admin_tariff_edit":
        tariff_id = int(state["tariff_id"])
        # Format: title | price | days | active(1/0)
        parts = [part.strip() for part in text.split("|")]
        if len(parts) != 4:
            await message.answer("Формат: <code>Название | Цена | Дни | 1 или 0</code>")
            return
        title, price_raw, days_raw, active_raw = parts
        try:
            price, days, active = float(price_raw.replace(",", ".")), int(days_raw), int(active_raw)
            if not title or price < 0 or days <= 0 or active not in (0, 1):
                raise ValueError
        except ValueError:
            await message.answer("Некорректные данные тарифа.")
            return
        await db_execute(
            "UPDATE tariffs SET title=?,price=?,days=?,active=? WHERE id=?",
            (title[:80], price, days, active, tariff_id),
        )
        clear_state(admin_id)
        await audit(admin_id, "tariff_updated", str(tariff_id))
        await message.answer("✅ Тариф обновлён.", reply_markup=await admin_markup())
        return

    if kind == "admin_support_reply":
        support_id = int(state["support_id"])
        row = await db_fetchone("SELECT user_id FROM support_messages WHERE id=?", (support_id,))
        clear_state(admin_id)
        if not row:
            await message.answer("Обращение не найдено.")
            return
        sent = await send_user(row[0], f"🆘 <b>Ответ поддержки</b>\n\n{safe_html(text)}")
        await db_execute(
            "UPDATE support_messages SET status='answered',answered_at=? WHERE id=?",
            (dt_to_db(now_local()), support_id),
        )
        await audit(admin_id, "support_answered", str(support_id))
        await message.answer("✅ Ответ отправлен." if sent else "Не удалось отправить ответ пользователю.")
        return

    clear_state(admin_id)
    await message.answer("Состояние сброшено.", reply_markup=await admin_markup())


# =============================================================================
# ADMIN: DASHBOARD, STATISTICS, USERS
# =============================================================================

@dp.callback_query(F.data == "admin:stats")
async def admin_stats(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    total = (await db_fetchone("SELECT COUNT(*) FROM users"))[0]
    active = (await db_fetchone("SELECT COUNT(*) FROM users WHERE paid_until IS NOT NULL AND paid_until>?",
                                (dt_to_db(now_local()),)))[0]
    banned = (await db_fetchone("SELECT COUNT(*) FROM users WHERE banned=1"))[0]
    pending = (await db_fetchone("SELECT COUNT(*) FROM payment_requests WHERE status='pending'"))[0]
    support = (await db_fetchone("SELECT COUNT(*) FROM support_messages WHERE status='open'"))[0]
    promos = (await db_fetchone("SELECT COUNT(*) FROM promos WHERE active=1"))[0]
    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{total}</b>\n"
        f"🔐 Активных доступов: <b>{active}</b>\n"
        f"🚫 Заблокировано: <b>{banned}</b>\n"
        f"💳 Заявок на оплату: <b>{pending}</b>\n"
        f"🆘 Открытых обращений: <b>{support}</b>\n"
        f"🎟 Активных промокодов: <b>{promos}</b>"
    )
    await call.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [button("⬅️ В админку", "admin:home")]
    ]))
    await call.answer()


@dp.callback_query(F.data == "admin:users")
async def admin_users(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    rows = await db_fetchall(
        "SELECT user_id,username,first_name,banned,paid_until FROM users ORDER BY joined_at DESC LIMIT 15"
    )
    if not rows:
        text = "Пользователей пока нет."
    else:
        lines = ["👥 <b>Последние 15 пользователей</b>\n"]
        for uid, username, first_name, banned, expiry in rows:
            name = first_name or username or "Без имени"
            state = "🚫" if banned else "✅"
            lines.append(f"{state} {safe_html(name)} — <code>{uid}</code>")
        text = "\n".join(lines)
    await call.message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [button("🚫 Заблокировать / разблокировать", "admin:ban_prompt")],
            [button("⬅️ В админку", "admin:home")],
        ]),
    )
    await call.answer()


@dp.callback_query(F.data == "admin:ban_prompt")
async def admin_ban_prompt(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    set_state(call.from_user.id, "admin_ban_user")
    await call.message.answer("Отправь Telegram ID пользователя для переключения блокировки.")
    await call.answer()


@dp.callback_query(F.data == "admin:home")
async def admin_home(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    await call.message.answer("<b>👑 Админ-панель</b>", reply_markup=await admin_markup())
    await call.answer()


# Add ban input handling as a small wrapper extension.
_original_admin_input = handle_admin_input

async def handle_admin_input(message: Message, state: dict[str, Any], text: str) -> None:
    if state.get("state") == "admin_ban_user":
        try:
            target = int(text)
        except ValueError:
            await message.answer("Нужен числовой Telegram ID.")
            return
        row = await db_fetchone("SELECT banned FROM users WHERE user_id=?", (target,))
        if not row:
            clear_state(message.from_user.id)
            await message.answer("Пользователь не найден.")
            return
        new_value = 0 if row[0] else 1
        await db_execute("UPDATE users SET banned=? WHERE user_id=?", (new_value, target))
        clear_state(message.from_user.id)
        await audit(message.from_user.id, "user_ban_toggle", f"user={target}; banned={new_value}")
        await message.answer(
            f"Пользователь <code>{target}</code>: "
            f"{'заблокирован' if new_value else 'разблокирован'}.",
            reply_markup=await admin_markup(),
        )
        if new_value:
            await send_user(target, "⛔ Доступ к боту ограничен администрацией.")
        else:
            await send_user(target, "✅ Доступ к боту восстановлен.")
        return
    await _original_admin_input(message, state, text)


# =============================================================================
# ADMIN: BUTTONS AND SECTION TEXTS
# =============================================================================

@dp.callback_query(F.data == "admin:buttons")
async def admin_buttons(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    rows = []
    for key in DEFAULT_BUTTONS:
        rows.append([button(f"✏️ {await get_button_title(key)} [{key}]", f"admin:button:{key}")])
    rows.append([button("⬅️ В админку", "admin:home")])
    await call.message.answer(
        "🔘 <b>Редактирование названий кнопок</b>\nВыбери кнопку:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await call.answer()


@dp.callback_query(F.data.startswith("admin:button:"))
async def admin_button_edit(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    key = call.data.split(":")[-1]
    if key not in DEFAULT_BUTTONS:
        await call.answer("Кнопка не найдена", show_alert=True)
        return
    set_state(call.from_user.id, "admin_edit_button", key=key)
    await call.message.answer(
        f"Отправь новое название для кнопки <code>{safe_html(key)}</code>."
    )
    await call.answer()


@dp.callback_query(F.data == "admin:texts")
async def admin_texts(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    keys = list(DEFAULT_TEXTS.keys())
    rows = [
        [button(f"📝 {key}", f"admin:text:{key}")]
        for key in keys
    ]
    rows.append([button("🎮 Тексты игр", "admin:game_contents")])
    rows.append([button("⬅️ В админку", "admin:home")])
    await call.message.answer(
        "📝 <b>Редактирование текстов</b>\n"
        "Можно изменить сообщение, которое пользователь видит после нажатия соответствующей кнопки.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await call.answer()


@dp.callback_query(F.data.startswith("admin:text:"))
async def admin_text_edit(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    key = call.data.split(":", 2)[2]
    if key not in DEFAULT_TEXTS:
        await call.answer("Текст не найден", show_alert=True)
        return
    set_state(call.from_user.id, "admin_edit_text", key=key)
    current = await get_text(key)
    await call.message.answer(
        f"Отправь новый текст для <code>{safe_html(key)}</code>.\n\n"
        "HTML-разметка Telegram разрешена: &lt;b&gt;, &lt;i&gt;, &lt;u&gt;, &lt;code&gt;.\n"
        "Текущий текст:\n\n" + truncate(current, 2500)
    )
    await call.answer()


@dp.callback_query(F.data == "admin:game_contents")
async def admin_game_contents(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    rows = []
    for key in ("roblox", "standoff", "brawl", "pubg", "clash"):
        rows.append([button(await get_button_title(key), f"admin:game:{key}")])
    rows.append([button("⬅️ Назад", "admin:texts")])
    await call.message.answer("Выбери игру для изменения текста:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@dp.callback_query(F.data.startswith("admin:game:"))
async def admin_game_edit(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    key = call.data.split(":")[-1]
    if key not in {"roblox", "standoff", "brawl", "pubg", "clash"}:
        await call.answer("Раздел не найден", show_alert=True)
        return
    row = await db_fetchone("SELECT title,content FROM game_contents WHERE game_key=?", (key,))
    title = row[0] if row else await get_button_title(key)
    current = row[1] if row else "Текст ещё не задан."
    set_state(call.from_user.id, "admin_game_content", key=key, title=title)
    await call.message.answer(
        f"Отправь новый текст для <b>{safe_html(title)}</b>.\n\n"
        f"Текущий текст:\n{truncate(current, 2200)}"
    )
    await call.answer()


# =============================================================================
# ADMIN: TARIFFS
# =============================================================================

@dp.callback_query(F.data == "admin:tariffs")
async def admin_tariffs(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    tariffs = await db_fetchall("SELECT id,title,price,days,active FROM tariffs ORDER BY id")
    rows = []
    for tariff_id, title, price, days, active in tariffs:
        status = "🟢" if active else "⚫"
        rows.append([button(
            f"{status} #{tariff_id} {title} — {price:g} {await get_setting('currency', DEFAULT_CURRENCY)} / {days}д",
            f"admin:tariff:{tariff_id}",
        )])
    rows.append([button("➕ Добавить тариф", "admin:tariff_add")])
    rows.append([button("⬅️ В админку", "admin:home")])
    await call.message.answer(
        "💰 <b>Тарифы</b>\n"
        "Нажми на тариф, чтобы изменить название, цену, срок или активность.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await call.answer()


@dp.callback_query(F.data == "admin:tariff_add")
async def admin_tariff_add(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    set_state(call.from_user.id, "admin_tariff_new")
    await call.message.answer(
        "Отправь данные в формате:\n<code>Название | Цена | Дни</code>\n"
        "Пример: <code>30 дней | 99 | 30</code>"
    )
    await call.answer()


@dp.callback_query(F.data.startswith("admin:tariff:"))
async def admin_tariff_edit(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    tariff_id = int(call.data.split(":")[-1])
    row = await db_fetchone(
        "SELECT title,price,days,active FROM tariffs WHERE id=?", (tariff_id,)
    )
    if not row:
        await call.answer("Тариф не найден", show_alert=True)
        return
    title, price, days, active = row
    set_state(call.from_user.id, "admin_tariff_edit", tariff_id=tariff_id)
    await call.message.answer(
        f"Текущий тариф: <b>{safe_html(title)}</b>, {price:g}, {days} дней, active={active}\n\n"
        "Отправь новые данные:\n"
        "<code>Название | Цена | Дни | 1 или 0</code>\n"
        "Пример: <code>Месяц | 149 | 30 | 1</code>"
    )
    await call.answer()


# =============================================================================
# ADMIN: PAYMENT DETAILS AND SETTINGS
# =============================================================================

@dp.callback_query(F.data == "admin:payment")
async def admin_payment(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    details = await get_setting("payment_details")
    currency = await get_setting("currency", DEFAULT_CURRENCY)
    await call.message.answer(
        "💳 <b>Настройки оплаты</b>\n\n"
        f"Валюта: <code>{safe_html(currency)}</code>\n"
        f"Реквизиты:\n{safe_html(details)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [button("✏️ Изменить реквизиты", "admin:setting:payment_details")],
            [button("💱 Изменить валюту", "admin:setting:currency")],
            [button("⬅️ В админку", "admin:home")],
        ]),
    )
    await call.answer()


@dp.callback_query(F.data == "admin:settings")
async def admin_settings(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    rows = [
        [button("🔗 Ссылка на канал", "admin:setting:channel_url")],
        [button("💎 Ссылка рекламы", "admin:setting:ads_url")],
        [button("🆘 Доп. текст поддержки", "admin:setting:support_text")],
        [button("🏷 Название проекта", "admin:setting:project_name")],
        [button("🛠 Техобслуживание: переключить", "admin:maintenance")],
        [button("⬅️ В админку", "admin:home")],
    ]
    await call.message.answer("⚙️ <b>Настройки проекта</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@dp.callback_query(F.data.startswith("admin:setting:"))
async def admin_setting_edit(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    key = call.data.split(":", 2)[2]
    allowed = {"payment_details", "currency", "channel_url", "ads_url", "support_text", "project_name"}
    if key not in allowed:
        await call.answer("Настройка не найдена", show_alert=True)
        return
    set_state(call.from_user.id, "admin_setting", key=key)
    current = await get_setting(key)
    await call.message.answer(
        f"Отправь новое значение для <code>{safe_html(key)}</code>.\n"
        f"Текущее значение:\n{safe_html(current) or '—'}"
    )
    await call.answer()


@dp.callback_query(F.data == "admin:maintenance")
async def admin_maintenance(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    current = await get_setting("maintenance", "0")
    new_value = "0" if current == "1" else "1"
    await set_setting("maintenance", new_value)
    await audit(call.from_user.id, "maintenance_toggled", new_value)
    await call.message.answer(
        f"🛠 Техническое обслуживание: {'ВКЛЮЧЕНО' if new_value == '1' else 'ВЫКЛЮЧЕНО'}",
        reply_markup=await admin_markup(),
    )
    await call.answer()


# =============================================================================
# ADMIN: DAILY POSTS AND PROMOS
# =============================================================================

@dp.callback_query(F.data == "admin:posts")
async def admin_posts(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    posts = await db_fetchall(
        "SELECT id,title,active FROM daily_posts ORDER BY id DESC LIMIT 10"
    )
    rows = [[button("➕ Добавить публикацию", "admin:post_add")]]
    for post_id, title, active in posts:
        rows.append([button(
            f"{'🟢' if active else '⚫'} #{post_id} {title[:35]}",
            f"admin:post_toggle:{post_id}",
        )])
    rows.append([button("⬅️ В админку", "admin:home")])
    await call.message.answer(
        "📚 <b>Публикации способов заработка</b>\n"
        "Нажатие на публикацию переключает её видимость.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await call.answer()


@dp.callback_query(F.data == "admin:post_add")
async def admin_post_add(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    set_state(call.from_user.id, "admin_new_post")
    await call.message.answer(
        "Отправь публикацию в формате:\n"
        "<code>Заголовок | Полный текст</code>"
    )
    await call.answer()


@dp.callback_query(F.data.startswith("admin:post_toggle:"))
async def admin_post_toggle(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    post_id = int(call.data.split(":")[-1])
    row = await db_fetchone("SELECT active FROM daily_posts WHERE id=?", (post_id,))
    if not row:
        await call.answer("Публикация не найдена", show_alert=True)
        return
    await db_execute("UPDATE daily_posts SET active=? WHERE id=?", (0 if row[0] else 1, post_id))
    await audit(call.from_user.id, "post_visibility_toggled", str(post_id))
    await call.answer("Статус изменён")
    await admin_posts(call)


@dp.callback_query(F.data == "admin:promos")
async def admin_promos(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    promos = await db_fetchall(
        "SELECT code,days,uses_left,active FROM promos ORDER BY created_at DESC LIMIT 15"
    )
    lines = ["🎟 <b>Промокоды</b>\n"]
    for code, days, uses, active in promos:
        lines.append(f"{'🟢' if active else '⚫'} <code>{safe_html(code)}</code> — {days} дн., осталось: {uses}")
    if not promos:
        lines.append("Промокодов пока нет.")
    await call.message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [button("➕ Добавить промокод", "admin:promo_add")],
            [button("⬅️ В админку", "admin:home")],
        ]),
    )
    await call.answer()


@dp.callback_query(F.data == "admin:promo_add")
async def admin_promo_add(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    set_state(call.from_user.id, "admin_new_promo")
    await call.message.answer(
        "Отправь: <code>КОД ДНИ ЛИМИТ</code>\n"
        "Пример: <code>WELCOME 7 100</code>\n"
        "Лимит 0 означает, что промокод нельзя будет активировать."
    )
    await call.answer()


# =============================================================================
# ADMIN: SUPPORT INBOX
# =============================================================================

@dp.callback_query(F.data == "admin:support")
async def admin_support(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    rows = await db_fetchall(
        "SELECT id,user_id,message,created_at FROM support_messages "
        "WHERE status='open' ORDER BY id DESC LIMIT 10"
    )
    if not rows:
        text = "📭 Открытых обращений нет."
        keyboard = [[button("⬅️ В админку", "admin:home")]]
    else:
        lines = ["🆘 <b>Открытые обращения</b>\n"]
        keyboard = []
        for support_id, user_id, body, created in rows:
            lines.append(
                f"#{support_id} от <code>{user_id}</code>\n"
                f"{safe_html(body[:250])}\n"
            )
            keyboard.append([button(f"✉️ Ответить #{support_id}", f"support:reply:{support_id}")])
        keyboard.append([button("⬅️ В админку", "admin:home")])
        text = "\n".join(lines)
    await call.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await call.answer()


@dp.callback_query(F.data.startswith("support:reply:"))
async def admin_support_reply(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    support_id = int(call.data.split(":")[-1])
    row = await db_fetchone("SELECT id FROM support_messages WHERE id=?", (support_id,))
    if not row:
        await call.answer("Обращение не найдено", show_alert=True)
        return
    set_state(call.from_user.id, "admin_support_reply", support_id=support_id)
    await call.message.answer(f"Отправь ответ для обращения #{support_id}.")
    await call.answer()


# =============================================================================
# ADMIN: BROADCAST
# =============================================================================

@dp.callback_query(F.data == "admin:broadcast")
async def admin_broadcast(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    set_state(call.from_user.id, "admin_broadcast")
    await call.message.answer(
        "📢 Отправь текст рассылки.\n"
        "Сообщение будет отправлено всем незаблокированным пользователям.\n"
        "Для отмены отправь /cancel."
    )
    await call.answer()


@dp.message(Command("cancel"))
async def command_cancel(message: Message) -> None:
    clear_state(message.from_user.id)
    await message.answer("Действие отменено.", reply_markup=await main_markup())


# =============================================================================
# INPUT ROUTER OVERRIDE FOR ADMIN STATES
# =============================================================================

# The generic text handler above routes admin messages through the latest
# handle_admin_input function. Handle admin media states here as well.
@dp.message(F.text & ~F.text.startswith("/"))
async def admin_text_fallback(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    state = get_state(message.from_user.id)
    if state:
        await handle_admin_input(message, state, (message.text or "").strip())


# =============================================================================
# ERROR HANDLING AND STARTUP
# =============================================================================

@dp.errors()
async def global_error_handler(event: Any) -> bool:
    logger.exception("Unhandled update error: %s", event.exception)
    try:
        update = event.update
        if update.message:
            await update.message.answer("⚠️ Произошла внутренняя ошибка. Попробуй ещё раз позже.")
        elif update.callback_query:
            await update.callback_query.answer("Произошла ошибка. Попробуй позже.", show_alert=True)
    except Exception:
        pass
    return True


async def on_startup() -> None:
    await init_database()
    me = await bot.get_me()
    logger.info("Bot started: @%s (%s)", me.username, me.id)
    await notify_admins(
        f"🟢 <b>{safe_html(me.username)}</b> запущен.\n"
        f"База данных: <code>{safe_html(DATABASE_PATH)}</code>"
    )


async def main() -> None:
    await on_startup()
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            close_bot_session=True,
        )
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")
