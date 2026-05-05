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

MASTER_BOT_TOKEN = os.getenv("MASTER_BOT_TOKEN", "8236516081:AAFjIjQBiAMs95XpURSCZZhuuYr5yDrcmlw")
API_URL = os.getenv("API_URL", "https://beauty-bot-api-production.up.railway.app")

bot = Bot(token=MASTER_BOT_TOKEN)
dp = Dispatcher()

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

# ЗАМЕНИ НА СВОЙ TELEGRAM ID (можно узнать у @userinfobot)
ADMIN_IDS = [123456789]


async def api_request(method: str, endpoint: str, data=None):
    async with aiohttp.ClientSession() as s:
        async with s.request(method, f"{API_URL}{endpoint}", json=data) as r:
            try:
                return await r.json()
            except:
                return None


async def get_master(telegram_id: str):
    return await api_request("GET", f"/masters/by-telegram/{telegram_id}")


async def send_message_via_admin_bot(telegram_id: str, message: str):
    """Отправляет сообщение через бота администратора"""
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"https://api.telegram.org/bot{MASTER_BOT_TOKEN}/sendMessage",
                json={"chat_id": telegram_id, "text": message, "parse_mode": "Markdown"}
            )
    except Exception as e:
        logger.error(f"Send message error: {e}")


# ========================== /start ==========================

@dp.message(CommandStart())
async def start(message: types.Message):
    user_id = str(message.from_user.id)
    master = await get_master(user_id)

    if user_id in ADMIN_IDS:
        text = ("👑 *Админ-панель*\n\n"
                "📋 /pending — просмотр заявок\n"
                "✅ /approve ID — одобрить мастера\n"
                "❌ /reject ID — отклонить\n"
                "🔧 /masters — список мастеров\n"
                "📊 /stats — статистика")
    elif master:
        text = (f"💅 *{master['name']}*\n\n"
                "📋 /schedule — моё расписание\n"
                "📅 /bookings — мои записи\n"
                "🔒 /off YYYY-MM-DD — закрыть день\n"
                "✅ /on YYYY-MM-DD — открыть день\n"
                "🤖 /set_token ТОКЕН — привязать своего бота")
    else:
        text = ("👋 *Вы не зарегистрированы*\n\n"
                "📝 Отправьте заявку:\n"
                "`/register Имя Адрес Телефон`\n\n"
                "Пример:\n"
                "`/register Анна ул.Ленина 10 +79001234567`")
    await message.answer(text, parse_mode="Markdown")


# ========================== РЕГИСТРАЦИЯ МАСТЕРА ==========================

@dp.message(Command("register"))
async def register_master(message: types.Message):
    user_id = str(message.from_user.id)

    if await get_master(user_id):
        await message.answer("✅ Вы уже зарегистрированы")
        return

    parts = message.text.split(maxsplit=3)
    if len(parts) < 4:
        await message.answer("❌ Формат: `/register Имя Адрес Телефон`", parse_mode="Markdown")
        return

    _, name, address, phone = parts

    payload = {"telegram_id": user_id, "name": name, "address": address, "phone": phone}
    resp = await api_request("POST", "/register-request", payload)

    if resp and resp.get("status") == "ok":
        await message.answer("✅ *Заявка отправлена!*\nАдминистратор рассмотрит её.", parse_mode="Markdown")
        for admin_id in ADMIN_IDS:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{user_id}"),
                 InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{user_id}")]
            ])
            await bot.send_message(
                admin_id,
                f"🆕 *НОВАЯ ЗАЯВКА*\n\n"
                f"👤 Имя: {name}\n"
                f"📍 Адрес: {address}\n"
                f"📞 Телефон: {phone}\n"
                f"🆔 ID: `{user_id}`",
                parse_mode="Markdown",
                reply_markup=keyboard
            )
    else:
        await message.answer("❌ Ошибка при отправке заявки")


# ========================== ПРИВЯЗКА БОТА МАСТЕРА ==========================

@dp.message(Command("set_token"))
async def set_bot_token(message: types.Message):
    master = await get_master(str(message.from_user.id))
    if not master:
        await message.answer("❌ Вы не зарегистрированы как мастер")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Формат: `/set_token ТОКЕН_БОТА`\n\nПолучить токен можно у @BotFather", parse_mode="Markdown")
        return

    token = parts[1]

    async with aiohttp.ClientSession() as s:
        async with s.patch(f"{API_URL}/masters/{master['id']}/bot-token?bot_token={token}") as resp:
            if resp.status == 200:
                await message.answer("✅ *Токен сохранён!*\nТеперь уведомления будут приходить в вашего бота.", parse_mode="Markdown")
                # Пробуем отправить тестовое сообщение через бота мастера
                try:
                    async with aiohttp.ClientSession() as sess:
                        await sess.post(
                            f"https://api.telegram.org/bot{token}/sendMessage",
                            json={"chat_id": message.from_user.id, "text": "✅ Ваш бот успешно подключён! Уведомления будут приходить сюда.", "parse_mode": "Markdown"}
                        )
                except Exception as e:
                    await message.answer(f"⚠️ Не удалось отправить тестовое сообщение. Проверьте токен.")
            else:
                await message.answer("❌ Ошибка при сохранении токена")


# ========================== АДМИН-КОМАНДЫ ==========================

@dp.message(Command("pending"))
async def list_pending(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Нет прав")
        return

    requests = await api_request("GET", "/register-requests/pending")
    if not requests:
        await message.answer("📭 Нет новых заявок")
        return

    for r in requests:
        text = (f"🆔 ID: `{r['telegram_id']}`\n"
                f"👤 Имя: {r['name']}\n"
                f"📍 Адрес: {r['address']}\n"
                f"📞 Телефон: {r['phone']}")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{r['telegram_id']}"),
             InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{r['telegram_id']}")]
        ])
        await message.answer(text, reply_markup=keyboard)


@dp.callback_query(F.data.startswith("approve_"))
async def approve_callback(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет прав", show_alert=True)
        return

    tg_id = callback.data.split("_")[1]
    resp = await api_request("POST", f"/approve-master/{tg_id}")

    if resp and resp.get("status") == "ok":
        await callback.message.edit_text(callback.message.text + "\n\n✅ *Одобрено*", parse_mode="Markdown")
        await send_message_via_admin_bot(tg_id, "🎉 *Заявка одобрена!*\n\nТеперь вы можете:\n/schedule — расписание\n/bookings — записи\n/set_token — привязать своего бота")
        await callback.answer("✅ Одобрено", show_alert=True)
    else:
        await callback.answer("❌ Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("reject_"))
async def reject_callback(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет прав", show_alert=True)
        return

    tg_id = callback.data.split("_")[1]
    await callback.message.edit_text(callback.message.text + "\n\n❌ *Отклонено*", parse_mode="Markdown")
    await send_message_via_admin_bot(tg_id, "😔 *Заявка отклонена*\n\nВы можете попробовать снова.")
    await callback.answer("❌ Отклонено", show_alert=True)


@dp.message(Command("approve"))
async def approve_master(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Нет прав")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Формат: `/approve TELEGRAM_ID`", parse_mode="Markdown")
        return

    tg_id = parts[1]
    resp = await api_request("POST", f"/approve-master/{tg_id}")

    if resp and resp.get("status") == "ok":
        await message.answer(f"✅ Мастер `{tg_id}` одобрен", parse_mode="Markdown")
        await send_message_via_admin_bot(tg_id, "🎉 *Заявка одобрена!*\n\n/schedule — расписание\n/bookings — записи")
    else:
        await message.answer("❌ Ошибка")


@dp.message(Command("reject"))
async def reject_master(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Нет прав")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Формат: `/reject TELEGRAM_ID`", parse_mode="Markdown")
        return

    tg_id = parts[1]
    await message.answer(f"❌ Мастер `{tg_id}` отклонён", parse_mode="Markdown")
    await send_message_via_admin_bot(tg_id, "😔 *Заявка отклонена*")


# ========================== КОМАНДЫ МАСТЕРА ==========================

@dp.message(Command("schedule"))
async def schedule(message: types.Message):
    master = await get_master(str(message.from_user.id))
    if not master:
        await message.answer("❌ Не зарегистрированы")
        return

    days = await api_request("GET", f"/masters/{master['id']}/schedule")
    if not days:
        await message.answer("❌ Ошибка")
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
                status_emoji = "✅" if b["status"] == "confirmed" else "⏳"
                text += f"  {status_emoji} {b['time']} — {b['client_name']}\n"
            text += "\n"
    await message.answer(text, parse_mode="Markdown")


@dp.message(Command("bookings"))
async def bookings(message: types.Message):
    master = await get_master(str(message.from_user.id))
    if not master:
        await message.answer("❌ Не зарегистрированы")
        return

    all_bookings = await api_request("GET", f"/bookings/master/{master['id']}")
    if not all_bookings:
        await message.answer("📭 Нет записей")
        return

    text = "📋 *Предстоящие записи:*\n\n"
    for b in all_bookings[:15]:
        status_emoji = {"pending": "⏳", "confirmed": "✅", "cancelled": "❌"}.get(b["status"], "⏳")
        text += f"{status_emoji} *{b['date']} в {b['time']}*\n👤 {b['client_name']}\n💅 {b['service_name']} — {b['price']} ₽\n\n"
    await message.answer(text, parse_mode="Markdown")


@dp.message(Command("off"))
async def set_day_off(message: types.Message):
    master = await get_master(str(message.from_user.id))
    if not master:
        await message.answer("❌ Не зарегистрированы")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Формат: `/off 2025-05-10`", parse_mode="Markdown")
        return

    date = parts[1]
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except:
        await message.answer("❌ Неверный формат даты")
        return

    resp = await api_request("POST", f"/masters/{master['id']}/days_off?date={date}")
    if resp and resp.get("status") == "ok":
        await message.answer(f"🔴 День *{date}* закрыт", parse_mode="Markdown")
    else:
        await message.answer("❌ Ошибка")


@dp.message(Command("on"))
async def remove_day_off(message: types.Message):
    master = await get_master(str(message.from_user.id))
    if not master:
        await message.answer("❌ Не зарегистрированы")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Формат: `/on 2025-05-10`", parse_mode="Markdown")
        return

    date = parts[1]
    async with aiohttp.ClientSession() as s:
        async with s.delete(f"{API_URL}/masters/{master['id']}/days_off/{date}") as r:
            if r.status == 200:
                await message.answer(f"✅ День *{date}* открыт", parse_mode="Markdown")
            else:
                await message.answer("❌ Ошибка")


# ========================== ЗАПУСК ==========================

async def main():
    logger.info("🚀 Бот администратора запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
