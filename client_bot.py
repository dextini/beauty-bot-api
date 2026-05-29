import asyncio
import logging
import os
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8236516081:AAFjIjQBiAMs95XpURSCZZhuuYr5yDrcmlw")
API_URL = os.getenv("API_URL", "https://intuitive-fascination-production-ce82.up.railway.app")
CHANNEL_USERNAME = "@pinkspotnews"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# АДМИНЫ
ADMIN_IDS = [868528632]  # ЗАМЕНИ НА СВОЙ ID


async def check_subscription(user_id: int) -> bool:
    try:
        chat_member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return chat_member.status in ["member", "administrator", "creator"]
    except:
        return False


def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить мастера", callback_data="admin_add_master")],
        [InlineKeyboardButton(text="📋 Список мастеров", callback_data="admin_list_masters")],
        [InlineKeyboardButton(text="🔗 Назначить Telegram ID", callback_data="admin_set_telegram")],
        [InlineKeyboardButton(text="❌ Удалить мастера", callback_data="admin_delete_master")],
        [InlineKeyboardButton(text="🗺️ Открыть карту", web_app=WebAppInfo(url="https://project-ev8r3.vercel.app"))]
    ])


@dp.message(CommandStart())
async def start(message: types.Message):
    user_id = message.from_user.id
    text = message.text
    
    # Регистрируем пользователя при первом /start (начало бесплатного периода)
    async with aiohttp.ClientSession() as session:
        await session.post(f"{API_URL}/user/register", json={"telegram_id": str(user_id)})
    
    # Проверка чата
    if text.startswith("/start chat_"):
        token = text.replace("/start chat_", "")
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_URL}/chat/{token}") as resp:
                if resp.status == 200:
                    chat_data = await resp.json()
                    await message.answer(
                        "💬 *Чат открыт!*\n\n"
                        "Вы можете общаться с мастером/клиентом здесь.\n"
                        "Просто пишите сообщения — они будут доставлены.\n\n"
                        "✉️ *Чтобы закрыть чат, напишите /close_chat*",
                        parse_mode="Markdown"
                    )
                else:
                    await message.answer("❌ Чат не найден или устарел")
        return
    
    # Проверка оплаты
    if text.startswith("/start pay_"):
        payment_id = text.replace("/start pay_", "")
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{API_URL}/payment-callback", json={"payment_id": payment_id}) as resp:
                if resp.status == 200:
                    await message.answer(
                        "✅ *Оплата подтверждена!*\n\n"
                        "Ваша запись подтверждена, и чат с мастером открыт.\n\n"
                        "💬 Откройте чат в веб-приложении, чтобы общаться с мастером.",
                        parse_mode="Markdown"
                    )
                else:
                    await message.answer("❌ Ошибка подтверждения оплаты")
        return
    
    # Проверка подписки
    is_subscribed = await check_subscription(user_id)
    
    if not is_subscribed:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/pinkspotnews")],
            [InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_sub")]
        ])
        await message.answer(
            "🌸 *Требуется подписка!*\n\n"
            "Чтобы пользоваться картой мастеров, подпишись на наш канал:\n"
            f"👉 [pinkspot news](https://t.me/pinkspotnews)\n\n"
            "После подписки нажми «Проверить подписку».",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return
    
    # Админ-панель
    if user_id in ADMIN_IDS:
        await message.answer(
            "👑 *Beauty Bot Admin Panel*\n\n"
            "Выберите действие:",
            parse_mode="Markdown",
            reply_markup=admin_keyboard()
        )
        return
    
    # Обычный пользователь
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗺️ Открыть карту мастеров", web_app=WebAppInfo(url="https://project-ev8r3.vercel.app"))],
        [InlineKeyboardButton(text="📝 Стать мастером", url="https://t.me/pinkspotvelur")]
    ])
    await message.answer(
        "💅 *Добро пожаловать в Beauty Map!*\n\n"
        "Нажми кнопку ниже, чтобы найти мастера рядом с тобой.\n\n"
        "✂️ *Хотите стать мастером?* Нажмите кнопку «Стать мастером» и напишите мне в личные сообщения.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


# ========== АДМИН-КОЛБЭКИ ==========
@dp.callback_query(F.data == "admin_add_master")
async def admin_add_master(callback: types.CallbackQuery):
    await callback.message.answer(
        "➕ *Добавление мастера*\n\n"
        "Отправьте данные в формате:\n"
        "`Имя | Адрес | Телефон | Instagram | Описание`\n\n"
        "Пример:\n"
        "`Анна Смирнова | ул. Тверская, 15 | +79001234567 | @anna_nails | Мастер маникюра`",
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.message(lambda msg: msg.text and " | " in msg.text and msg.from_user.id in ADMIN_IDS)
async def handle_add_master(message: types.Message):
    parts = message.text.split(" | ")
    if len(parts) < 2:
        await message.answer("❌ Неверный формат.")
        return
    
    name = parts[0].strip()
    address = parts[1].strip()
    phone = parts[2].strip() if len(parts) > 2 else ""
    instagram = parts[3].strip() if len(parts) > 3 else ""
    description = parts[4].strip() if len(parts) > 4 else ""
    
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/admin/add-master", json={
            "name": name, "address": address, "phone": phone,
            "instagram": instagram, "description": description
        }) as resp:
            if resp.status == 200:
                await message.answer(f"✅ Мастер *{name}* добавлен!", parse_mode="Markdown")
            else:
                await message.answer("❌ Ошибка при добавлении")


@dp.callback_query(F.data == "admin_list_masters")
async def admin_list_masters(callback: types.CallbackQuery):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_URL}/admin/masters") as resp:
            if resp.status == 200:
                masters = await resp.json()
                if not masters:
                    await callback.message.answer("📭 Нет мастеров")
                else:
                    text = "📋 *Список мастеров:*\n\n"
                    for m in masters:
                        text += f"🆔 *ID:* {m['id']}\n👤 *Имя:* {m['name']}\n🤖 *Telegram ID:* {m.get('telegram_id') or '❌'}\n─" * 20 + "\n"
                    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "admin_set_telegram")
async def admin_set_telegram_prompt(callback: types.CallbackQuery):
    await callback.message.answer(
        "🔗 *Назначение Telegram ID*\n\n"
        "Отправьте: `ID_МАСТЕРА TELEGRAM_ID`\nПример: `1 123456789`",
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.message(lambda msg: msg.text and len(msg.text.split()) == 2 and msg.from_user.id in ADMIN_IDS and msg.text.split()[0].isdigit())
async def handle_set_telegram(message: types.Message):
    parts = message.text.split()
    master_id = parts[0]
    telegram_id = parts[1]
    
    async with aiohttp.ClientSession() as session:
        async with session.patch(f"{API_URL}/admin/set-telegram/{master_id}?telegram_id={telegram_id}") as resp:
            if resp.status == 200:
                await message.answer(f"✅ Telegram ID назначен мастеру {master_id}")
            else:
                await message.answer("❌ Ошибка")


@dp.callback_query(F.data == "admin_delete_master")
async def admin_delete_master_prompt(callback: types.CallbackQuery):
    await callback.message.answer("❌ *Удаление мастера*\n\nОтправьте ID мастера:", parse_mode="Markdown")
    await callback.answer()


@dp.message(lambda msg: msg.text and msg.text.isdigit() and msg.from_user.id in ADMIN_IDS)
async def handle_delete_master(message: types.Message):
    master_id = message.text
    async with aiohttp.ClientSession() as session:
        async with session.delete(f"{API_URL}/admin/delete-master/{master_id}") as resp:
            if resp.status == 200:
                await message.answer(f"✅ Мастер с ID {master_id} удалён")
            else:
                await message.answer("❌ Ошибка")


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
