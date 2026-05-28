import asyncio
import logging
import os
import json
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8236516081:AAFjIjQBiAMs95XpURSCZZhuuYr5yDrcmlw")
API_URL = os.getenv("API_URL", "https://intuitive-fascination-production-ce82.up.railway.app")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Замени на свой Telegram ID
ADMIN_IDS = [868528632]


async def get_master(telegram_id: str):
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{API_URL}/masters/by-telegram/{telegram_id}") as r:
            if r.status == 200:
                return await r.json()
    return None


@dp.message(CommandStart())
async def start(message: types.Message):
    user_id = message.from_user.id
    master = await get_master(str(user_id))
    
    if master:
        await message.answer(
            f"💅 *{master['name']}*, добро пожаловать!\n\n"
            "📋 /schedule — расписание на 7 дней\n"
            "📅 /bookings — мои записи\n"
            "🔒 /off ГГГГ-ММ-ДД — закрыть день\n"
            "✅ /on ГГГГ-ММ-ДД — открыть день\n"
            "🤖 /set_token ТОКЕН — привязать своего бота",
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            "👋 Привет! Ты не зарегистрирован как мастер.\n\n"
            f"Твой Telegram ID: `{user_id}`",
            parse_mode="Markdown"
        )


@dp.message(Command("schedule"))
async def schedule(message: types.Message):
    master = await get_master(str(message.from_user.id))
    if not master:
        await message.answer("❌ Ты не зарегистрирован как мастер.")
        return

    async with aiohttp.ClientSession() as s:
        async with s.get(f"{API_URL}/masters/{master['id']}/schedule") as r:
            if r.status != 200:
                await message.answer("❌ Ошибка загрузки расписания")
                return
            days = await r.json()

    WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    text = "📅 *Расписание на 7 дней:*\n\n"
    for day in days:
        dt = datetime.strptime(day["date"], "%Y-%m-%d")
        weekday = WEEKDAYS[dt.weekday()]
        date_str = dt.strftime("%d.%m")
        
        if day["day_off"]:
            text += f"🔴 *{date_str} ({weekday})* — выходной\n\n"
        elif not day["bookings"]:
            text += f"🟢 *{date_str} ({weekday})* — свободно\n\n"
        else:
            text += f"🟡 *{date_str} ({weekday})* — {len(day['bookings'])} записей:\n"
            for b in day["bookings"]:
                status_emoji = "✅" if b["status"] == "confirmed" else "⏳"
                text += f"  {status_emoji} {b['time']} — {b['client_name']}\n"
            text += "\n"
    await message.answer(text, parse_mode="Markdown")


@dp.message(Command("bookings"))
async def bookings(message: types.Message):
    master = await get_master(str(message.from_user.id))
    if not master:
        await message.answer("❌ Ты не зарегистрирован как мастер.")
        return

    async with aiohttp.ClientSession() as s:
        async with s.get(f"{API_URL}/bookings/master/{master['id']}") as r:
            if r.status != 200:
                await message.answer("❌ Ошибка загрузки записей")
                return
            all_bookings = await r.json()

    if not all_bookings:
        await message.answer("📭 Нет предстоящих записей.")
        return

    text = "📋 *Все предстоящие записи:*\n\n"
    for b in all_bookings[:15]:
        status_emoji = {"pending": "⏳", "awaiting_payment": "💳", "confirmed": "✅", "cancelled": "❌"}.get(b["status"], "⏳")
        text += f"{status_emoji} *{b['date']} в {b['time']}*\n👤 {b['client_name']}\n💅 {b['service_name']} — {b['price']} ₽\n\n"
    await message.answer(text, parse_mode="Markdown")


@dp.message(Command("off"))
async def set_day_off(message: types.Message):
    master = await get_master(str(message.from_user.id))
    if not master:
        await message.answer("❌ Ты не зарегистрирован как мастер.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Формат: `/off ГГГГ-ММ-ДД`", parse_mode="Markdown")
        return

    date = parts[1]
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except:
        await message.answer("❌ Неверный формат даты")
        return

    async with aiohttp.ClientSession() as s:
        async with s.post(f"{API_URL}/masters/{master['id']}/days_off?date={date}") as r:
            if r.status == 200:
                await message.answer(f"🔴 День *{date}* закрыт", parse_mode="Markdown")
            else:
                await message.answer("❌ Ошибка")


@dp.message(Command("on"))
async def remove_day_off(message: types.Message):
    master = await get_master(str(message.from_user.id))
    if not master:
        await message.answer("❌ Ты не зарегистрирован как мастер.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Формат: `/on ГГГГ-ММ-ДД`", parse_mode="Markdown")
        return

    date = parts[1]
    async with aiohttp.ClientSession() as s:
        async with s.delete(f"{API_URL}/masters/{master['id']}/days_off/{date}") as r:
            if r.status == 200:
                await message.answer(f"✅ День *{date}* открыт", parse_mode="Markdown")
            else:
                await message.answer("❌ Ошибка")


@dp.message(Command("set_token"))
async def set_bot_token(message: types.Message):
    master = await get_master(str(message.from_user.id))
    if not master:
        await message.answer("❌ Ты не зарегистрирован как мастер.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Формат: `/set_token ТОКЕН`", parse_mode="Markdown")
        return

    token = parts[1]
    async with aiohttp.ClientSession() as s:
        async with s.patch(f"{API_URL}/masters/{master['id']}/bot-token?bot_token={token}") as r:
            if r.status == 200:
                await message.answer("✅ Токен сохранён! Уведомления будут приходить в вашего бота.")
            else:
                await message.answer("❌ Ошибка")


# === КНОПКИ ПОДТВЕРДИТЬ/ОТМЕНИТЬ С ДЕПОЗИТОМ ===
@dp.callback_query(F.data.startswith("confirm_"))
async def confirm_booking(callback: types.CallbackQuery):
    booking_id = int(callback.data.split("_")[1])
    
    master = await get_master(str(callback.from_user.id))
    if not master:
        await callback.answer("❌ Вы не зарегистрированы как мастер", show_alert=True)
        return
    
    async with aiohttp.ClientSession() as s:
        # Создаём депозитный платёж
        async with s.post(f"{API_URL}/create-deposit-payment", json={"booking_id": booking_id}) as resp:
            if resp.status == 200:
                data = await resp.json()
                
                # Отправляем клиенту ссылку на оплату
                booking = await s.get(f"{API_URL}/bookings/{booking_id}")
                booking_data = await booking.json()
                
                await bot.send_message(
                    booking_data["client_telegram_id"],
                    f"💳 *Мастер подтвердил запись!*\n\n"
                    f"💅 Услуга: {booking_data['service_name']}\n"
                    f"👩 Мастер: {master['name']}\n"
                    f"📅 {booking_data['date']} в {booking_data['time']}\n\n"
                    f"💰 *Депозит {data['deposit_amount']} ₽ (10% от стоимости)*\n\n"
                    f"[Оплатить сейчас]({data['payment_url']})\n\n"
                    f"После оплаты вы сможете общаться с мастером в чате.",
                    parse_mode="Markdown"
                )
                
                await callback.message.edit_text(
                    callback.message.text + "\n\n💳 *Клиенту отправлена ссылка на оплату депозита*",
                    parse_mode="Markdown"
                )
                await callback.answer("✅ Запись ожидает оплаты", show_alert=True)
            else:
                await callback.answer("❌ Ошибка при создании платежа", show_alert=True)


@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_booking(callback: types.CallbackQuery):
    booking_id = int(callback.data.split("_")[1])
    
    master = await get_master(str(callback.from_user.id))
    if not master:
        await callback.answer("❌ Вы не зарегистрированы как мастер", show_alert=True)
        return
    
    async with aiohttp.ClientSession() as s:
        async with s.patch(f"{API_URL}/bookings/{booking_id}/status?status=cancelled") as r:
            if r.status == 200:
                await callback.message.edit_text(
                    callback.message.text + "\n\n❌ *Запись отменена.*",
                    parse_mode="Markdown"
                )
                await callback.answer("❌ Запись отменена", show_alert=True)
            else:
                await callback.answer("❌ Ошибка", show_alert=True)


@dp.message(Command("set_token"))
async def set_bot_token(message: types.Message):
    master = await get_master(str(message.from_user.id))
    if not master:
        await message.answer("❌ Ты не зарегистрирован как мастер.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Формат: `/set_token ТОКЕН`", parse_mode="Markdown")
        return

    token = parts[1]
    async with aiohttp.ClientSession() as s:
        async with s.patch(f"{API_URL}/masters/{master['id']}/bot-token?bot_token={token}") as r:
            if r.status == 200:
                await message.answer("✅ Токен сохранён! Уведомления будут приходить в вашего бота.")
            else:
                await message.answer("❌ Ошибка")


async def main():
    logger.info("🚀 Мастер-бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
