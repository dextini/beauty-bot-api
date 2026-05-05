import asyncio
import logging
import os
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ⚠️ Замените на токен бота мастеров (создайте нового бота у @BotFather)
MASTER_BOT_TOKEN = os.getenv("MASTER_BOT_TOKEN", "8236516081:AAFjIjQBiAMs95XpURSCZZhuuYr5yDrcmlw")
API_URL = os.getenv("API_URL", "https://beauty-bot-api-production.up.railway.app")

bot = Bot(token=MASTER_BOT_TOKEN)
dp = Dispatcher()

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


async def get_master(telegram_id: str):
    """Получить данные мастера по Telegram ID"""
    async with aiohttp.ClientSession() as s:
        try:
            async with s.get(f"{API_URL}/masters/by_telegram/{telegram_id}") as r:
                if r.status == 200:
                    return await r.json()
        except Exception as e:
            logger.error(f"Error getting master: {e}")
    return None


async def send_message(telegram_id: str, message: str):
    """Отправка сообщения пользователю"""
    if not telegram_id:
        return
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"https://api.telegram.org/bot{MASTER_BOT_TOKEN}/sendMessage",
                json={"chat_id": telegram_id, "text": message, "parse_mode": "Markdown"}
            )
    except Exception as e:
        logger.error(f"Send message error: {e}")


# --- /start ---
@dp.message(CommandStart())
async def start(message: types.Message):
    master = await get_master(str(message.from_user.id))
    if master:
        await message.answer(
            f"💅 Привет, *{master['name']}*!\n\n"
            f"Доступные команды:\n"
            f"📋 /schedule — расписание на 7 дней\n"
            f"🔒 /off ГГГГ-ММ-ДД — закрыть день\n"
            f"✅ /on ГГГГ-ММ-ДД — открыть день\n"
            f"📅 /bookings — все предстоящие записи\n"
            f"ℹ️ /help — помощь",
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            "👋 Привет! Ты не зарегистрирован как мастер.\n\n"
            "Напиши администратору чтобы тебя добавили в систему.\n"
            f"Твой Telegram ID: `{message.from_user.id}`",
            parse_mode="Markdown"
        )


# --- /schedule ---
@dp.message(Command("schedule"))
async def schedule(message: types.Message):
    master = await get_master(str(message.from_user.id))
    if not master:
        await message.answer("❌ Ты не зарегистрирован как мастер.")
        return

    async with aiohttp.ClientSession() as s:
        try:
            async with s.get(f"{API_URL}/masters/{master['id']}/schedule") as r:
                if r.status != 200:
                    await message.answer("❌ Ошибка загрузки расписания")
                    return
                days = await r.json()
        except Exception as e:
            logger.error(f"Schedule error: {e}")
            await message.answer("❌ Ошибка подключения к серверу")
            return

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
                status_emoji = "✅" if b["status"] == "confirmed" else "⏳" if b["status"] == "pending" else "❌"
                phone = f" | {b['client_phone']}" if b.get("client_phone") else ""
                text += f"  {status_emoji} {b['time']} — {b['client_name']}{phone} ({b['service_name']})\n"
            text += "\n"

    await message.answer(text, parse_mode="Markdown")


# --- /bookings ---
@dp.message(Command("bookings"))
async def bookings(message: types.Message):
    master = await get_master(str(message.from_user.id))
    if not master:
        await message.answer("❌ Ты не зарегистрирован как мастер.")
        return

    async with aiohttp.ClientSession() as s:
        try:
            async with s.get(f"{API_URL}/bookings/master/{master['id']}") as r:
                if r.status != 200:
                    await message.answer("❌ Ошибка загрузки записей")
                    return
                all_bookings = await r.json()
        except Exception as e:
            logger.error(f"Bookings error: {e}")
            await message.answer("❌ Ошибка подключения к серверу")
            return

    if not all_bookings:
        await message.answer("📋 Нет предстоящих записей.")
        return

    text = "📋 *Все предстоящие записи:*\n\n"
    for b in all_bookings[:15]:
        status_emoji = {"pending": "⏳", "confirmed": "✅", "cancelled": "❌"}.get(b["status"], "⏳")
        phone = f"\n   📞 {b['client_phone']}" if b.get("client_phone") else ""
        text += (
            f"{status_emoji} *{b['date']} в {b['time']}*\n"
            f"   👩 {b['client_name']}{phone}\n"
            f"   💅 {b['service_name']} — {b['price']} ₽\n\n"
        )

    await message.answer(text, parse_mode="Markdown")


# --- /off YYYY-MM-DD ---
@dp.message(Command("off"))
async def set_day_off(message: types.Message):
    master = await get_master(str(message.from_user.id))
    if not master:
        await message.answer("❌ Ты не зарегистрирован как мастер.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Укажи дату: `/off 2025-05-10`", parse_mode="Markdown")
        return

    date = parts[1]
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        await message.answer("❌ Неверный формат даты. Используй: `ГГГГ-ММ-ДД`", parse_mode="Markdown")
        return

    async with aiohttp.ClientSession() as s:
        try:
            async with s.post(f"{API_URL}/masters/{master['id']}/days_off?date={date}") as r:
                if r.status == 200:
                    await message.answer(f"🔴 День *{date}* закрыт. Новые записи на этот день невозможны.", parse_mode="Markdown")
                else:
                    await message.answer("❌ Ошибка. Попробуй ещё раз.")
        except Exception as e:
            logger.error(f"Set day off error: {e}")
            await message.answer("❌ Ошибка подключения к серверу")


# --- /on YYYY-MM-DD ---
@dp.message(Command("on"))
async def remove_day_off(message: types.Message):
    master = await get_master(str(message.from_user.id))
    if not master:
        await message.answer("❌ Ты не зарегистрирован как мастер.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Укажи дату: `/on 2025-05-10`", parse_mode="Markdown")
        return

    date = parts[1]
    async with aiohttp.ClientSession() as s:
        try:
            async with s.delete(f"{API_URL}/masters/{master['id']}/days_off/{date}") as r:
                if r.status == 200:
                    await message.answer(f"✅ День *{date}* открыт для записей!", parse_mode="Markdown")
                else:
                    await message.answer("❌ Ошибка. Попробуй ещё раз.")
        except Exception as e:
            logger.error(f"Remove day off error: {e}")
            await message.answer("❌ Ошибка подключения к серверу")


# --- /help ---
@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    await message.answer(
        "ℹ️ *Команды бота мастера:*\n\n"
        "📋 /schedule — расписание на 7 дней\n"
        "📅 /bookings — все предстоящие записи\n"
        "🔒 /off 2025-05-10 — закрыть день (выходной)\n"
        "✅ /on 2025-05-10 — открыть день\n\n"
        "Когда клиент записывается — ты получаешь уведомление с кнопками подтвердить/отменить.",
        parse_mode="Markdown"
    )


# --- Кнопки подтвердить/отменить (ИСПРАВЛЕНО - без GET запроса) ---
@dp.callback_query(F.data.startswith("confirm_"))
async def confirm_booking(callback: types.CallbackQuery):
    booking_id = int(callback.data.split("_")[1])
    
    # Проверяем, что мастер зарегистрирован
    master = await get_master(str(callback.from_user.id))
    if not master:
        await callback.answer("❌ Вы не зарегистрированы как мастер", show_alert=True)
        return
    
    async with aiohttp.ClientSession() as s:
        try:
            # Прямо отправляем PATCH запрос на подтверждение
            async with s.patch(f"{API_URL}/bookings/{booking_id}/status?status=confirmed") as r:
                # Получаем текст ответа для диагностики
                response_text = await r.text()
                logger.info(f"PATCH response status: {r.status}, body: {response_text}")
                
                if r.status == 200:
                    # Обновляем сообщение
                    await callback.message.edit_text(
                        callback.message.text + "\n\n✅ *Запись подтверждена!*",
                        parse_mode="Markdown"
                    )
                    
                    await callback.answer("✅ Запись подтверждена!", show_alert=True)
                else:
                    await callback.answer(f"❌ Ошибка {r.status}: проверьте логи", show_alert=True)
        except Exception as e:
            logger.error(f"Confirm booking error: {e}")
            await callback.answer("❌ Ошибка сервера", show_alert=True)


@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_booking(callback: types.CallbackQuery):
    booking_id = int(callback.data.split("_")[1])
    
    # Проверяем, что мастер зарегистрирован
    master = await get_master(str(callback.from_user.id))
    if not master:
        await callback.answer("❌ Вы не зарегистрированы как мастер", show_alert=True)
        return
    
    async with aiohttp.ClientSession() as s:
        try:
            # Прямо отправляем PATCH запрос на отмену
            async with s.patch(f"{API_URL}/bookings/{booking_id}/status?status=cancelled") as r:
                response_text = await r.text()
                logger.info(f"PATCH response status: {r.status}, body: {response_text}")
                
                if r.status == 200:
                    # Обновляем сообщение
                    await callback.message.edit_text(
                        callback.message.text + "\n\n❌ *Запись отменена.*",
                        parse_mode="Markdown"
                    )
                    
                    await callback.answer("❌ Запись отменена", show_alert=True)
                else:
                    await callback.answer(f"❌ Ошибка {r.status}: проверьте логи", show_alert=True)
        except Exception as e:
            logger.error(f"Cancel booking error: {e}")
            await callback.answer("❌ Ошибка сервера", show_alert=True)


async def main():
    logger.info("Starting Master Bot...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
