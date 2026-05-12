import asyncio
import logging
import os
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_URL = os.getenv("API_URL", "https://intuitive-fascination-production-ce82.up.railway.app")

if not BOT_TOKEN:
    logger.error("BOT_TOKEN not set!")
    exit(1)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ЗАМЕНИ НА СВОЙ TELEGRAM ID (узнай у @userinfobot)
ADMIN_ID = 868528632  # ← СЮДА ВСТАВЬ СВОЙ ID


@dp.message(CommandStart())
async def start(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗺️ Открыть карту мастеров", web_app=WebAppInfo(url="https://project-ev8r3.vercel.app"))],
        [InlineKeyboardButton(text="📝 Стать мастером", url="https://t.me/pinkspotvelur")]
    ])
    await message.answer(
        "💅 *Добро пожаловать в Beauty Map!*\n\n"
        "Нажми кнопку ниже, чтобы найти мастера рядом с тобой.\n\n"
        "✂️ *Хотите стать мастером?* Нажмите кнопку «Стать мастером» и напишите мне в личные сообщения.",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


@dp.message(Command("regbot"))
async def register_master_bot(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет прав")
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("❌ Формат: `/regbot ТОКЕН`\n\nПример: `/regbot 1234567890:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw`", parse_mode="Markdown")
        return
    
    token = parts[1].strip()
    
    async with aiohttp.ClientSession() as session:
        master_id = 1  # ВРЕМЕННО, потом заменишь на ID нужного мастера
        async with session.patch(f"{API_URL}/masters/{master_id}/bot-token?bot_token={token}") as resp:
            if resp.status == 200:
                await message.answer(f"✅ Токен бота сохранён для мастера ID {master_id}.\nТеперь этот мастер будет получать уведомления о новых записях.")
            else:
                await message.answer("❌ Ошибка при сохранении токена. Проверь, что API работает.")


async def main():
    logger.info("🚀 Клиентский бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
