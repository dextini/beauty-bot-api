import asyncio
import logging
import os
import json
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8236516081:AAFjIjQBiAMs95XpURSCZZhuuYr5yDrcmlw")
API_URL = os.getenv("API_URL", "https://intuitive-fascination-production-ce82.up.railway.app")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Замени на свой Telegram ID
ADMIN_IDS = [868528632]

# Переменные для Google Sheets
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS")
SHEET_ID = os.getenv("SHEET_ID")


async def api_request(method: str, endpoint: str, data=None):
    async with aiohttp.ClientSession() as s:
        async with s.request(method, f"{API_URL}{endpoint}", json=data) as r:
            if r.status == 200:
                return await r.json()
            return None


@dp.message(CommandStart())
async def start(message: types.Message):
    user_id = message.from_user.id
    if user_id in ADMIN_IDS:
        await message.answer(
            "👑 *Beauty Bot Admin Panel*\n\n"
            "📋 /pending — заявки мастеров\n"
            "✅ /approve ID — одобрить\n"
            "❌ /reject ID — отклонить\n"
            "📊 /stats — общая статистика\n"
            "🎫 /add_promo КОД % ДНИ — создать промокод\n"
            "📥 /import_sheet — импорт мастеров из Google Таблицы\n"
            "🗑️ /delete_master ID — удалить мастера с карты\n"
            "🤖 /set_master_bot ID ТОКЕН — привязать бота мастеру\n"
            "📸 /add_photo ID ССЫЛКА — добавить фото мастеру\n"
            "📋 /list_photos ID — список фото мастера\n"
            "🗑️ /del_photo ID ИНДЕКС — удалить фото",
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            "💅 *Добро пожаловать в Beauty Map!*\n\n"
            "Нажми кнопку ниже, чтобы найти мастера рядом с тобой.\n\n"
            "✂️ *Хотите стать мастером?* Нажмите кнопку «Стать мастером» и напишите мне в личные сообщения.",
            parse_mode="Markdown",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🗺️ Открыть карту мастеров", web_app=types.WebAppInfo(url="https://project-ev8r3.vercel.app"))],
                [types.InlineKeyboardButton(text="📝 Стать мастером", url="https://t.me/pinkspotvelur")]
            ])
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


@dp.message(Command("delete_master"))
async def delete_master(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Нет прав")
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Формат: `/delete_master ID`", parse_mode="Markdown")
        return
    master_id = parts[1]
    async with aiohttp.ClientSession() as session:
        async with session.delete(f"{API_URL}/masters/{master_id}") as resp:
            if resp.status == 200:
                await message.answer(f"✅ Мастер с ID `{master_id}` удалён", parse_mode="Markdown")
            else:
                await message.answer(f"❌ Ошибка при удалении мастера {master_id}")


@dp.message(Command("set_master_bot"))
async def set_master_bot(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Нет прав")
        return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("❌ Формат: `/set_master_bot ID_МАСТЕРА ТОКЕН`\n\nПример:\n`/set_master_bot 1 1234567890:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw`", parse_mode="Markdown")
        return
    
    master_id = parts[1]
    bot_token = parts[2]
    
    async with aiohttp.ClientSession() as session:
        async with session.patch(f"{API_URL}/masters/{master_id}/bot-token?bot_token={bot_token}") as resp:
            if resp.status == 200:
                await message.answer(f"✅ Токен для мастера ID `{master_id}` сохранён.\nТеперь уведомления о новых записях будут приходить в его бота.", parse_mode="Markdown")
            else:
                await message.answer(f"❌ Ошибка при сохранении токена. Проверь, что мастер с ID `{master_id}` существует.", parse_mode="Markdown")


@dp.message(Command("add_photo"))
async def add_master_photo(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Нет прав")
        return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("❌ Формат: `/add_photo ID_МАСТЕРА ССЫЛКА_НА_ФОТО`\n\nПример:\n`/add_photo 1 https://example.com/photo.jpg`", parse_mode="Markdown")
        return
    
    master_id = parts[1]
    photo_url = parts[2]
    
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/masters/{master_id}/photos", json={"photo": photo_url}) as resp:
            if resp.status == 200:
                await message.answer(f"✅ Фото добавлено мастеру ID {master_id}")
            else:
                await message.answer("❌ Ошибка при добавлении фото")


@dp.message(Command("list_photos"))
async def list_master_photos(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Нет прав")
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("❌ Формат: `/list_photos ID_МАСТЕРА`", parse_mode="Markdown")
        return
    
    master_id = parts[1]
    
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_URL}/masters/{master_id}/photos") as resp:
            if resp.status == 200:
                data = await resp.json()
                photos = data.get("photos", [])
                if not photos:
                    await message.answer(f"📭 У мастера ID {master_id} нет фото")
                else:
                    text = f"📸 *Фото мастера ID {master_id}:*\n\n"
                    for i, photo in enumerate(photos):
                        text += f"{i}. {photo}\n"
                    await message.answer(text, parse_mode="Markdown")
            else:
                await message.answer("❌ Ошибка при получении списка фото")


@dp.message(Command("del_photo"))
async def delete_master_photo(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Нет прав")
        return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("❌ Формат: `/del_photo ID_МАСТЕРА ИНДЕКС_ФОТО`\n\nПример:\n`/del_photo 1 0` (удалит первое фото)", parse_mode="Markdown")
        return
    
    master_id = parts[1]
    photo_index = int(parts[2])
    
    async with aiohttp.ClientSession() as session:
        async with session.delete(f"{API_URL}/masters/{master_id}/photos?index={photo_index}") as resp:
            if resp.status == 200:
                await message.answer(f"✅ Фото удалено у мастера ID {master_id}")
            else:
                await message.answer("❌ Ошибка при удалении фото")


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


@dp.message(Command("import_sheet"))
async def import_from_google_sheets(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Нет прав")
        return

    if not GOOGLE_CREDENTIALS_JSON or not SHEET_ID:
        await message.answer("❌ Не настроены переменные GOOGLE_CREDENTIALS или SHEET_ID")
        return

    await message.answer("🔄 Начинаю импорт мастеров из Google Таблицы...")

    try:
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)

        sheet = client.open_by_key(SHEET_ID).sheet1
        rows = sheet.get_all_records()

        added = 0
        errors = 0

        for row in rows:
            try:
                if not row.get('name') or not row.get('address'):
                    continue

                master_data = {
                    "name": row['name'],
                    "address": row['address'],
                    "lat": float(row.get('lat', 55.751244)),
                    "lon": float(row.get('lon', 37.618423)),
                    "phone": row.get('phone', ''),
                    "instagram": row.get('instagram', ''),
                    "description": row.get('description', ''),
                    "services": row.get('services', '')
                }

                async with aiohttp.ClientSession() as session:
                    async with session.post(f"{API_URL}/masters", json=master_data) as resp:
                        if resp.status == 200:
                            added += 1
                            logger.info(f"✅ Добавлен мастер: {row['name']}")
                        else:
                            errors += 1
                            logger.error(f"❌ Ошибка добавления {row['name']}: {resp.status}")
            except Exception as e:
                errors += 1
                logger.error(f"Ошибка в строке: {e}")

        await message.answer(
            f"✅ *Импорт завершён!*\n\n"
            f"➕ Добавлено: `{added}`\n"
            f"❌ Ошибок: `{errors}`",
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"Ошибка импорта: {e}")
        await message.answer(f"❌ Ошибка при импорте: {e}")


async def main():
    logger.info("🚀 Бот администратора запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
