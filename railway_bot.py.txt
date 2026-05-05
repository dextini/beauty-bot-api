import asyncio
import logging
import os
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MASTER_BOT_TOKEN = os.getenv("MASTER_BOT_TOKEN", "8236516081:AAFjIjQBiAMs95XpURSCZZhuuYr5yDrcmlw")
API_URL = os.getenv("API_URL", "https://beauty-bot-api-production.up.railway.app")

bot = Bot(token=MASTER_BOT_TOKEN)
dp = Dispatcher()

ADMIN_IDS = [123456789]  # ЗАМЕНИ НА СВОЙ ID ПОТОМ


@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer("👑 Бот администратора работает на Railway!")


async def main():
    logger.info("🚀 Бот администратора запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
