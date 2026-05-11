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

# ЗАМЕНИ НА СВОЙ TELEGRAM ID (узнай у @userinfobot)
ADMIN_IDS = [123456789]


async def api_request(method: str, endpoint: str, data=None):
    async with aiohttp.ClientSession() as s:
        async with s.request(method, f"{API_URL}{endpoint}", json=data) as r:
            if r.status == 200:
                return await r.json()
            return None


@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer("👑 Бот администратора работает на Railway!\n\n/pending — заявки\n/approve ID — одобрить\n/reject ID — отклонить")


@dp.message(Command("pending"))
async def pending(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Нет прав")
        return
    requests = await api_request("GET", "/register-requests/pending")
    if not requests:
        await message.answer("📭 Нет новых заявок")
        return
    for r in requests:
        await message.answer(f"🆔 ID: `{r['telegram_id']}`\n👤 Имя: {r['name']}\n📍 Адрес: {r['address']}\n📞 Телефон: {r['phone']}\n\n✅ /approve {r['telegram_id']}", parse_mode="Markdown")


@dp.message(Command("approve"))
async def approve(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Нет прав")
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Формат: `/approve TELEGRAM_ID`", parse_mode="Markdown")
        return
    resp = await api_request("POST", f"/approve-master/{parts[1]}")
    if resp:
        await message.answer(f"✅ Мастер `{parts[1]}` одобрен", parse_mode="Markdown")
    else:
        await message.answer("❌ Ошибка при одобрении")


@dp.message(Command("reject"))
async def reject(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Нет прав")
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Формат: `/reject TELEGRAM_ID`", parse_mode="Markdown")
        return
    await message.answer(f"❌ Мастер `{parts[1]}` отклонён", parse_mode="Markdown")


async def main():
    logger.info("🚀 Бот администратора запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
