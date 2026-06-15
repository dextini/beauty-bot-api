import asyncio
import logging
import os
import aiohttp
import qrcode
from io import BytesIO
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup, BufferedInputFile
from datetime import datetime, timedelta
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8236516081:AAFjIjQBiAMs95XpURSCZZhuuYr5yDrcmlw")
API_URL = os.getenv("API_URL", "https://intuitive-fascination-production-ce82.up.railway.app")
CHANNEL_USERNAME = "@pinkspotnews"
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://project-ev8r3.vercel.app")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

ADMIN_IDS = [868528632, 777000]  # Добавь сюда свой Telegram ID


async def api_request(method: str, endpoint: str, data: dict = None):
    """Универсальная функция для запросов к API"""
    url = f"{API_URL}{endpoint}"
    async with aiohttp.ClientSession() as session:
        try:
            if method == "GET":
                async with session.get(url) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return None
            elif method == "POST":
                async with session.post(url, json=data) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return None
            elif method == "PATCH":
                async with session.patch(url, json=data) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return None
            elif method == "DELETE":
                async with session.delete(url) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.error(f"API ошибка: {e}")
            return None


async def check_subscription(user_id: int) -> bool:
    """Проверка подписки на канал"""
    try:
        chat_member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return chat_member.status in ["member", "administrator", "creator"]
    except:
        return False


def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь админом"""
    return user_id in ADMIN_IDS


def admin_keyboard():
    """Клавиатура админа"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить мастера", callback_data="admin_add_master")],
        [InlineKeyboardButton(text="📋 Список мастеров", callback_data="admin_list_masters")],
        [InlineKeyboardButton(text="❌ Удалить мастера", callback_data="admin_delete_master")],
        [InlineKeyboardButton(text="🎫 Создать промокод", callback_data="admin_add_promo")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🗺️ Открыть карту", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])


def master_keyboard(master_id: int = None, has_services: bool = False):
    """Клавиатура мастера"""
    keyboard = [
        [InlineKeyboardButton(text="📊 Мой кабинет", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(text="🔗 QR-код для клиентов", callback_data="share_master_qr")],
        [InlineKeyboardButton(text="➕ Добавить услуги", callback_data="master_add_services")],
        [InlineKeyboardButton(text="📸 Портфолио", callback_data="master_portfolio")],
        [InlineKeyboardButton(text="🗺️ Карта клиентов", web_app=WebAppInfo(url=WEBAPP_URL))]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def client_keyboard():
    """Клавиатура клиента"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗺️ Найти мастера", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(text="📝 Мои записи", callback_data="my_bookings")],
        [InlineKeyboardButton(text="🎫 Промокоды", callback_data="my_promocodes")],
        [InlineKeyboardButton(text="📞 Поддержка", url="https://t.me/pinkspotvelur")]
    ])


def subscription_keyboard():
    """Клавиатура для проверки подписки"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/pinkspotnews")],
        [InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_sub")]
    ])


# ========== ОСНОВНЫЕ КОМАНДЫ ==========

@dp.message(CommandStart())
async def start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    text = message.text
    
    logger.info(f"Пользователь {user_id} ({username}) вызвал /start с параметром: {text}")
    
    # Регистрируем пользователя
    await api_request("POST", "/user/register", {"telegram_id": str(user_id), "username": username, "name": first_name})
    
    # Обработка deep link: /start master_123
    if text.startswith("/start master_"):
        master_id = text.replace("/start master_", "").strip()
        webapp_url = f"{WEBAPP_URL}?masterId={master_id}"
        
        await message.answer(
            f"🌸 *Профиль мастера*\n\n"
            f"📅 Нажмите на кнопку, чтобы открыть профиль и записаться:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📅 Открыть профиль мастера", web_app=WebAppInfo(url=webapp_url))]
            ]),
            parse_mode="Markdown"
        )
        return
    
    # Обработка deep link: /start promo_CODE
    if text.startswith("/start promo_"):
        promo_code = text.replace("/start promo_", "").strip()
        await message.answer(
            f"🎫 *Промокод активирован!*\n\n"
            f"✅ Промокод `{promo_code}` применён. Скидка будет применена при записи.",
            parse_mode="Markdown"
        )
        return
    
    # Проверка подписки
    is_subscribed = await check_subscription(user_id)
    if not is_subscribed:
        await message.answer(
            "🌸 *Требуется подписка!*\n\n"
            f"Подпишись на канал, чтобы пользоваться ботом:\n"
            f"👉 [pinkspot news](https://t.me/pinkspotnews)",
            reply_markup=subscription_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    # Админ
    if is_admin(user_id):
        await message.answer(
            "👑 *Admin Panel*\n\n"
            "Выберите действие:",
            parse_mode="Markdown",
            reply_markup=admin_keyboard()
        )
        return
    
    # Проверка на мастера
    master_data = await api_request("GET", f"/masters/by_telegram/{user_id}")
    
    if master_data and master_data.get("id"):
        master_id = master_data.get("id")
        master_name = master_data.get("name") or first_name or "Мастер"
        
        # Проверяем, есть ли услуги у мастера
        services = await api_request("GET", f"/master/{user_id}/services")
        has_services = services and len(services) > 0
        
        await message.answer(
            f"👋 *Здравствуйте, {master_name}!*\n\n"
            f"✅ Вы зарегистрированы как мастер.\n\n"
            f"📊 Нажмите «Мой кабинет» для управления профилем, услугами и портфолио.\n\n"
            f"🔗 Нажмите «QR-код для клиентов» — напечатайте на визитках!",
            parse_mode="Markdown",
            reply_markup=master_keyboard(master_id, has_services)
        )
        return
    
    # Обычный клиент
    await message.answer(
        f"💅 *Добро пожаловать в Beauty Map, {first_name}!*\n\n"
        "🌸 Нажми кнопку ниже, чтобы найти мастера рядом с тобой.\n\n"
        "📋 В разделе «Мои записи» ты можешь посмотреть все свои визиты.\n"
        "🎫 А в разделе «Промокоды» — активировать скидки.",
        parse_mode="Markdown",
        reply_markup=client_keyboard()
    )


# ========== УМНЫЕ ФУНКЦИИ ==========

@dp.callback_query(F.data == "my_bookings")
async def my_bookings(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    bookings = await api_request("GET", f"/bookings/client/{user_id}")
    
    if not bookings:
        await callback.message.answer(
            "📭 *У вас пока нет записей*\n\n"
            "Нажмите «Найти мастера» и запишитесь на процедуру!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🗺️ Найти мастера", web_app=WebAppInfo(url=WEBAPP_URL))]
            ])
        )
        await callback.answer()
        return
    
    text = "📋 *Ваши записи:*\n\n"
    for b in bookings[:10]:
        status_emoji = "✅" if b["status"] == "confirmed" else "⏳" if b["status"] == "pending" else "❌"
        text += f"{status_emoji} *{b['master_name']}* — {b['service_name']}\n   📅 {b['date']} в {b['time']}\n   💰 {b['price']} ₽\n\n"
    
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "my_promocodes")
async def my_promocodes(callback: types.CallbackQuery):
    promocodes = await api_request("GET", "/promocodes/active")
    
    if not promocodes:
        await callback.message.answer(
            "🎫 *Нет активных промокодов*\n\n"
            "Следите за новостями в нашем канале!",
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    text = "🎫 *Активные промокоды:*\n\n"
    for p in promocodes:
        text += f"🔹 `{p['code']}` — скидка {p['discount_percent']}%\n"
    
    text += "\n💡 Примените промокод при записи в веб-приложении!"
    
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()


# ========== МАСТЕР-ФУНКЦИИ ==========

@dp.callback_query(F.data == "share_master_qr")
async def share_master_qr(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    master_data = await api_request("GET", f"/masters/by_telegram/{user_id}")
    
    if not master_data:
        await callback.answer("❌ Вы не зарегистрированы как мастер", show_alert=True)
        return
    
    master_id = master_data["id"]
    bot_link = f"https://t.me/{bot.username}?start=master_{master_id}"
    
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(bot_link)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#FF6F91", back_color="white")
    
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    
    await callback.message.answer_photo(
        photo=BufferedInputFile(buffer.read(), filename="qr.png"),
        caption=f"📱 *Ваш QR-код для клиентов*\n\n"
                f"🔗 Ссылка: `{bot_link}`\n\n"
                f"💡 Напечатайте QR-код на визитках — клиенты смогут сразу перейти к вашему профилю!",
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.callback_query(F.data == "master_add_services")
async def master_add_services(callback: types.CallbackQuery):
    await callback.message.answer(
        "💅 *Как добавить услуги*\n\n"
        "1️⃣ Откройте «Мой кабинет»\n"
        "2️⃣ Перейдите во вкладку «Услуги»\n"
        "3️⃣ Нажмите «Добавить услугу»\n\n"
        "📌 После добавления услуг клиенты смогут к вам записываться!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Открыть кабинет", web_app=WebAppInfo(url=WEBAPP_URL))]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "master_portfolio")
async def master_portfolio(callback: types.CallbackQuery):
    await callback.message.answer(
        "📸 *Как добавить портфолио*\n\n"
        "1️⃣ Откройте «Мой кабинет»\n"
        "2️⃣ Перейдите во вкладку «Портфолио»\n"
        "3️⃣ Добавьте фото своих работ (можно «До/После»)\n\n"
        "✨ Клиенты выбирают мастера по примерам работ!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Открыть кабинет", web_app=WebAppInfo(url=WEBAPP_URL))]
        ])
    )
    await callback.answer()


# ========== АДМИН-ФУНКЦИИ ==========

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    stats = await api_request("GET", "/admin/stats")
    
    if not stats:
        await callback.message.answer("❌ Не удалось загрузить статистику")
        await callback.answer()
        return
    
    text = (
        f"📊 *Статистика Beauty Bot*\n\n"
        f"👥 Мастеров: {stats.get('masters_count', 0)}\n"
        f"📝 Записей: {stats.get('bookings_count', 0)}\n"
        f"💰 Выручка: {stats.get('revenue', 0)} ₽\n"
        f"👤 Клиентов: {stats.get('clients_count', 0)}\n"
        f"🎫 Промокодов: {stats.get('promocodes_count', 0)}\n\n"
        f"📅 Обновлено: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "admin_add_master")
async def admin_add_master(callback: types.CallbackQuery):
    await callback.message.answer(
        "➕ *Добавление мастера*\n\n"
        "Отправьте Telegram ID мастера:\n"
        "`123456789`\n\n"
        "💡 Как узнать ID: напишите @userinfobot",
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_list_masters")
async def admin_list_masters(callback: types.CallbackQuery):
    masters = await api_request("GET", "/masters")
    
    if not masters:
        await callback.message.answer("📭 Нет мастеров в базе")
    else:
        text = "📋 *Список мастеров:*\n\n"
        for m in masters[:10]:
            services_count = len(m.get('services', []))
            telegram_info = f"TG: {m.get('telegram_id')}" if m.get('telegram_id') else "❌ Нет TG ID"
            text += f"🆔 {m.get('id')} | 👤 {m.get('name', 'Без имени')}\n   {telegram_info} | ⭐ {m.get('rating', 0)} | 💅 {services_count} услуг\n\n"
        
        if len(masters) > 10:
            text += f"\n📌 Всего мастеров: {len(masters)}"
        
        await callback.message.answer(text, parse_mode="Markdown")
    
    await callback.answer()


@dp.callback_query(F.data == "admin_delete_master")
async def admin_delete_master_prompt(callback: types.CallbackQuery):
    # Сначала показываем список мастеров
    masters = await api_request("GET", "/masters")
    
    if not masters:
        await callback.message.answer("📭 Нет мастеров для удаления")
        await callback.answer()
        return
    
    text = "❌ *Удаление мастера*\n\nОтправьте ID мастера:\n\n"
    for m in masters[:10]:
        text += f"🔹 ID {m['id']} — {m.get('name', 'Без имени')}\n"
    
    text += "\nПример: `5`"
    
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "admin_add_promo")
async def admin_add_promo_prompt(callback: types.CallbackQuery):
    await callback.message.answer(
        "🎫 *Создание промокода*\n\n"
        "Отправьте в формате:\n`КОД СКИДКА% ДНЕЙ`\n\n"
        "Примеры:\n"
        "• `WELCOME10 10 30` — скидка 10% на 30 дней\n"
        "• `HAPPYHOUR 20 7` — скидка 20% на 7 дней",
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.message(lambda msg: msg.text and msg.from_user.id in ADMIN_IDS)
async def handle_admin_commands(message: types.Message):
    text = message.text.strip()
    user_id = message.from_user.id
    
    # Добавление мастера (только цифры)
    if text.isdigit() and len(text) > 5:
        result = await api_request("POST", "/masters", {
            "telegram_id": int(text),
            "name": f"Мастер {text}",
            "lat": 47.222078,
            "lon": 39.720358,
            "description": "Новый мастер. Заполните профиль в кабинете."
        })
        
        if result and result.get("id"):
            await message.answer(
                f"✅ *Мастер успешно добавлен!*\n\n"
                f"🆔 ID: {result['id']}\n"
                f"🤖 Telegram ID: {text}\n\n"
                f"📌 Мастер может войти в кабинет и заполнить свои данные.",
                parse_mode="Markdown"
            )
            # Отправляем уведомление мастеру
            try:
                await bot.send_message(
                    int(text),
                    "🌸 *Поздравляем! Вы стали мастером Beauty Bot!*\n\n"
                    "📊 Для управления профилем нажмите кнопку «Мой кабинет».\n\n"
                    "✨ Заполните:\n"
                    "• Ваше имя\n"
                    "• Локацию на карте\n"
                    "• Услуги и цены\n"
                    "• Портфолио своих работ\n\n"
                    "🔗 Ссылка на бота: https://t.me/pinkspotvelur_bot",
                    parse_mode="Markdown"
                )
            except:
                pass
        else:
            await message.answer("❌ Ошибка при добавлении мастера")
        return
    
    # Удаление мастера (ID мастера)
    if text.isdigit() and len(text) <= 5:
        success = await api_request("DELETE", f"/masters/{int(text)}")
        
        if success:
            await message.answer(f"✅ *Мастер ID {text} удалён*", parse_mode="Markdown")
        else:
            await message.answer("❌ Ошибка при удалении мастера")
        return
    
    # Создание промокода (КОД СКИДКА ДНЕЙ)
    parts = text.split()
    if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
        code = parts[0].upper()
        discount = int(parts[1])
        days = int(parts[2])
        
        expires_at = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        
        result = await api_request("POST", "/promocodes", {
            "code": code,
            "discount_percent": discount,
            "expires_at": expires_at,
            "max_uses": 100
        })
        
        if result:
            await message.answer(
                f"✅ *Промокод создан!*\n\n"
                f"🎫 Код: `{code}`\n"
                f"📉 Скидка: {discount}%\n"
                f"📅 Действует до: {expires_at}\n\n"
                f"🔗 Ссылка для клиентов:\n"
                f"`https://t.me/{bot.username}?start=promo_{code}`",
                parse_mode="Markdown"
            )
        else:
            await message.answer("❌ Ошибка при создании промокода")
        return
    
    # Если ничего не подошло
    await message.answer(
        "❌ *Неверный формат*\n\n"
        "Доступные команды:\n"
        "• `123456789` — добавить мастера\n"
        "• `5` — удалить мастера по ID\n"
        "• `SUMMER20 20 30` — создать промокод",
        parse_mode="Markdown"
    )


# ========== ПРОВЕРКА ПОДПИСКИ ==========

@dp.callback_query(F.data == "check_sub")
async def check_subscription_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    is_subscribed = await check_subscription(user_id)
    
    if is_subscribed:
        await callback.message.delete()
        await start(callback.message)
        await callback.answer("✅ Спасибо за подписку!", show_alert=True)
    else:
        await callback.answer("❌ Ты ещё не подписан на канал.", show_alert=True)


@dp.message(Command("close_chat"))
async def close_chat(message: types.Message):
    await message.answer("💬 *Чат закрыт*", parse_mode="Markdown")


@dp.message(Command("admin"))
async def admin_command(message: types.Message):
    if is_admin(message.from_user.id):
        await message.answer(
            "👑 *Admin Panel*\n\n"
            "Выберите действие:",
            parse_mode="Markdown",
            reply_markup=admin_keyboard()
        )
    else:
        await message.answer("⛔ У вас нет доступа к админ-панели")


# ========== ЗАПУСК ==========

async def main():
    logger.info("🚀 Beauty Bot запущен!")
    
    # Устанавливаем команды для меню
    await bot.set_my_commands([
        types.BotCommand(command="start", description="🔄 Главное меню"),
        types.BotCommand(command="admin", description="👑 Админ-панель"),
        types.BotCommand(command="close_chat", description="💬 Закрыть чат"),
    ])
    
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
