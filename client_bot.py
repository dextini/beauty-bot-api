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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8236516081:AAFjIjQBiAMs95XpURSCZZhuuYr5yDrcmlw")
API_URL = os.getenv("API_URL", "https://intuitive-fascination-production-ce82.up.railway.app")
CHANNEL_USERNAME = "@pinkspotnews"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

ADMIN_IDS = [868528632]


async def api_request(method: str, endpoint: str, data: dict = None):
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
    try:
        chat_member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return chat_member.status in ["member", "administrator", "creator"]
    except:
        return False


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить мастера", callback_data="admin_add_master")],
        [InlineKeyboardButton(text="📋 Список мастеров", callback_data="admin_list_masters")],
        [InlineKeyboardButton(text="❌ Удалить мастера", callback_data="admin_delete_master")],
        [InlineKeyboardButton(text="🎫 Создать промокод", callback_data="admin_add_promo")],
        [InlineKeyboardButton(text="🗺️ Открыть карту", web_app=WebAppInfo(url="https://project-ev8r3.vercel.app"))]
    ])


def master_keyboard(master_id: int = None):
    keyboard = [
        [InlineKeyboardButton(text="📊 Мой кабинет", web_app=WebAppInfo(url="https://project-ev8r3.vercel.app"))],
        [InlineKeyboardButton(text="🔗 QR-код для клиентов", callback_data="share_master_qr")],
        [InlineKeyboardButton(text="🗺️ Карта клиентов", web_app=WebAppInfo(url="https://project-ev8r3.vercel.app"))]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def client_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗺️ Найти мастера", web_app=WebAppInfo(url="https://project-ev8r3.vercel.app"))],
        [InlineKeyboardButton(text="📝 Стать мастером", url="https://t.me/pinkspotvelur")]
    ])


def subscription_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/pinkspotnews")],
        [InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_sub")]
    ])


@dp.message(CommandStart())
async def start(message: types.Message):
    user_id = message.from_user.id
    text = message.text
    
    logger.info(f"Пользователь {user_id} вызвал /start с параметром: {text}")
    
    await apiRequest("POST", "/user/register", {"telegram_id": str(user_id)})
    
    # Ссылка на мастера
    if text.startswith("/start master_"):
        master_id = text.replace("/start master_", "").strip()
        webapp_url = f"https://project-ev8r3.vercel.app/?id={master_id}"
        
        await message.answer(
            f"🌸 *Профиль мастера*\n\nНажмите на кнопку, чтобы открыть профиль и записаться:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📅 Открыть профиль мастера", web_app=WebAppInfo(url=webapp_url))]
            ]),
            parse_mode="Markdown"
        )
        return
    
    # Ссылка на чат
    if text.startswith("/start chat_"):
        token = text.replace("/start chat_", "")
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_URL}/chat/{token}") as resp:
                if resp.status == 200:
                    await message.answer(
                        "💬 *Чат открыт!*\n\nЧтобы закрыть чат, напишите /close_chat",
                        parse_mode="Markdown"
                    )
                else:
                    await message.answer("❌ Чат не найден или устарел")
        return
    
    # Ссылка на оплату
    if text.startswith("/start pay_"):
        payment_id = text.replace("/start pay_", "")
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{API_URL}/payment-callback", json={"payment_id": payment_id}) as resp:
                if resp.status == 200:
                    await message.answer(
                        "✅ *Оплата подтверждена!*\n\nВаша запись подтверждена!",
                        parse_mode="Markdown"
                    )
                else:
                    await message.answer("❌ Ошибка подтверждения оплаты")
        return
    
    # Проверка подписки
    is_subscribed = await check_subscription(user_id)
    if not is_subscribed:
        await message.answer(
            "🌸 *Требуется подписка!*\n\nПодпишись на канал:\n"
            f"👉 [pinkspot news](https://t.me/pinkspotnews)",
            reply_markup=subscription_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    # Админ
    if is_admin(user_id):
        await message.answer(
            "👑 *Admin Panel*\n\nВыберите действие:",
            parse_mode="Markdown",
            reply_markup=admin_keyboard()
        )
        return
    
    # Проверка на мастера
    master_data = await apiRequest("GET", f"/masters/by_telegram/{user_id}")
    
    if master_data and master_data.get("id"):
        master_name = master_data.get("name", "Мастер")
        master_id = master_data.get("id")
        await message.answer(
            f"👋 *Здравствуйте, {master_name}!*\n\n"
            f"✅ Вы зарегистрированы как мастер.\n\n"
            f"📊 Нажмите «Мой кабинет мастера» для управления.\n\n"
            f"🔗 Нажмите «QR-код для клиентов» — напечатайте на визитках!",
            parse_mode="Markdown",
            reply_markup=master_keyboard(master_id)
        )
        return
    
    # Обычный клиент
    await message.answer(
        "💅 *Добро пожаловать в Beauty Map!*\n\n"
        "Нажми кнопку ниже, чтобы найти мастера рядом с тобой.",
        parse_mode="Markdown",
        reply_markup=client_keyboard()
    )


# QR-код для мастера
@dp.callback_query(F.data == "share_master_qr")
async def share_master_qr(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    master_data = await apiRequest("GET", f"/masters/by_telegram/{user_id}")
    
    if not master_data:
        await callback.answer("❌ Вы не зарегистрированы как мастер", show_alert=True)
        return
    
    master_id = master_data["id"]
    bot_link = f"https://t.me/pinkspotvelur_bot?start=master_{master_id}"
    
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(bot_link)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#FF6F91", back_color="white")
    
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    
    await callback.message.answer_photo(
        photo=BufferedInputFile(buffer.read(), filename="qr.png"),
        caption=f"📱 *Ваш QR-код для клиентов*\n\n🔗 Ссылка: `{bot_link}`",
        parse_mode="Markdown"
    )
    await callback.answer()


# Админ-колбэки
@dp.callback_query(F.data == "admin_add_master")
async def admin_add_master(callback: types.CallbackQuery):
    await callback.message.answer(
        "➕ *Добавление мастера*\n\nОтправьте Telegram ID мастера:\n`123456789`",
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.message(lambda msg: msg.text and msg.text.isdigit() and msg.from_user.id in ADMIN_IDS)
async def handle_add_master(message: types.Message):
    telegram_id = message.text.strip()
    result = await apiRequest("POST", "/admin/add-master", {"telegram_id": telegram_id})
    
    if result:
        await message.answer(f"✅ Мастер с Telegram ID `{telegram_id}` добавлен!", parse_mode="Markdown")
    else:
        await message.answer("❌ Ошибка при добавлении мастера")


@dp.callback_query(F.data == "admin_list_masters")
async def admin_list_masters(callback: types.CallbackQuery):
    masters = await apiRequest("GET", "/admin/masters")
    
    if not masters:
        await callback.message.answer("📭 Нет мастеров в базе")
    else:
        text = "📋 *Список мастеров:*\n\n"
        for m in masters[:15]:
            text += f"🆔 ID: {m['id']}\n👤 Имя: {m.get('name') or 'Не заполнено'}\n🤖 Telegram ID: {m.get('telegram_id') or 'Нет'}\n\n"
        await callback.message.answer(text, parse_mode="Markdown")
    
    await callback.answer()


@dp.callback_query(F.data == "admin_delete_master")
async def admin_delete_master_prompt(callback: types.CallbackQuery):
    await callback.message.answer("❌ *Удаление мастера*\n\nОтправьте ID мастера для удаления:\n`1`", parse_mode="Markdown")
    await callback.answer()


@dp.message(lambda msg: msg.text and msg.text.isdigit() and msg.from_user.id in ADMIN_IDS)
async def handle_delete_master(message: types.Message):
    master_id = message.text
    success = await apiRequest("DELETE", f"/admin/delete-master/{master_id}")
    
    if success:
        await message.answer(f"✅ Мастер *ID {master_id}* удалён", parse_mode="Markdown")
    else:
        await message.answer("❌ Ошибка при удалении мастера")


@dp.callback_query(F.data == "admin_add_promo")
async def admin_add_promo_prompt(callback: types.CallbackQuery):
    await callback.message.answer(
        "🎫 *Создание промокода*\n\nОтправьте в формате:\n`КОД СКИДКА% ДНЕЙ`\nПример: `SUMMER20 20 30`",
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.message(lambda msg: msg.text and len(msg.text.split()) == 3 and msg.from_user.id in ADMIN_IDS)
async def handle_add_promo(message: types.Message):
    parts = message.text.split()
    code = parts[0].upper()
    discount = int(parts[1])
    days = int(parts[2])
    
    valid_until = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    result = await apiRequest("POST", "/admin/add-promo", {"code": code, "discount": discount, "valid_until": valid_until, "max_uses": 100})
    
    if result:
        await message.answer(f"✅ Промокод `{code}` создан! Скидка {discount}% до {valid_until}", parse_mode="Markdown")
    else:
        await message.answer("❌ Ошибка при создании промокода")


@dp.callback_query(F.data == "check_sub")
async def check_subscription_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    is_subscribed = await check_subscription(user_id)
    
    if is_subscribed:
        await callback.message.delete()
        await start(callback.message)
        await callback.answer("✅ Спасибо за подписку!", show_alert=True)
    else:
        await callback.answer("❌ Ты ещё не подписан.", show_alert=True)


@dp.message(Command("close_chat"))
async def close_chat(message: types.Message):
    await message.answer("💬 *Чат закрыт*", parse_mode="Markdown")


async def main():
    logger.info("🚀 Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
