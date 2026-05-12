import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
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


@dp.message(CommandStart())
async def start(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗺️ Открыть карту мастеров", web_app=WebAppInfo(url="https://project-ev8r3.vercel.app"))],
        [InlineKeyboardButton(text="📝 Стать мастером", url="https://t.me/dextini")]
    ])
    await message.answer(
        "💅 *Добро пожаловать в Beauty Map!*\n\n"
        "Нажми кнопку ниже, чтобы найти мастера рядом с тобой.\n\n"
        "✂️ *Хотите стать мастером?* Нажмите кнопку «Стать мастером» и напишите мне в личные сообщения.",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


async def main():
    logger.info("🚀 Клиентский бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
