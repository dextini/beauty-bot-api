import asyncio
import logging
import os
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MASTER_BOT_TOKEN = os.getenv("MASTER_BOT_TOKEN", "8236516081:AAFjIjQBiAMs95XpURSCZZhuuYr5yDrcmlw")
API_URL = os.getenv("API_URL", "https://beauty-bot-api-production.up.railway.app")

bot = Bot(token=MASTER_BOT_TOKEN)
dp = Dispatcher()

ADMIN_IDS = [123456789]  # ЗАМЕНИ НА СВОЙ ID


async def api_request(method: str, endpoint: str, data=None):
    async with aiohttp.ClientSession() as s:
        async with s.request(method, f"{API_URL}{endpoint}", json=data) as r:
            if r.status == 200:
                return await r.json()
            return None


@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer(
        "👑 *Beauty Bot Admin Panel*\n\n"
        "📋 /pending — заявки мастеров\n"
        "✅ /approve ID — одобрить\n"
        "❌ /reject ID — отклонить\n"
        "📊 /stats — общая статистика\n"
        "🎫 /add_promo КОД % ДНИ — создать промокод",
        parse_mode="Markdown"
    )


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
        await message.answer(
            f"🆔 ID: `{r['telegram_id']}`\n"
            f"👤 Имя: {r['name']}\n"
            f"📍 Адрес: {r['address']}\n"
            f"📞 Телефон: {r['phone']}\n"
            f"✅ /approve {r['telegram_id']}",
            parse_mode="Markdown"
        )


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


@dp.message(Command("add_promo"))
async def add_promo(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Нет прав")
        return
    parts = message.text.split()
    if len(parts) < 4:
        await message.answer("❌ Формат: `/add_promo КОД СКИДКА% ДНЕЙ`\nПример: `/add_promo SUMMER20 20 30`", parse_mode="Markdown")
        return
    
    code = parts[1].upper()
    discount = int(parts[2])
    days = int(parts[3])
    
    valid_until = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{API_URL}/add-promo", json={"code": code, "discount_percent": discount, "valid_until": valid_until, "max_uses": 100}) as r:
            if r.status == 200:
                await message.answer(f"✅ Промокод `{code}` создан!\nСкидка {discount}% до {valid_until}", parse_mode="Markdown")
            else:
                await message.answer("❌ Ошибка при создании промокода")


async def main():
    logger.info("🚀 Бот администратора запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
