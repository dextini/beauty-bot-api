Skip to content
dextini
beauty-bot-api
Repository navigation
Code
Issues
Pull requests
Actions
Projects
Wiki
Security and quality
1
 (1)
Insights
Settings
Files
Go to file
t
T
Procfile.txt
beauty.db
client_bot.py
index (1).html
main.py
master_bot.py
railway_bot.py
requirements.txt
beauty-bot-api
/client_bot.py
dextini
dextini
client_bot.py
46b5185
 · 
now
beauty-bot-api
/client_bot.py

Code

Blame
72 lines (56 loc) · 3.05 KB
async def start(message: types.Message):
Code view is read-only. Switch to the editor.
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
        [InlineKeyboardButton(text="📝 Стать мастером", url="https://t.me/pinkspotvelur")]
    ])
    await message.answer(
        "💅 *Добро пожаловать в Beauty Map!*\n\n"
        "Нажми кнопку ниже, чтобы найти мастера рядом с тобой.\n\n"
        "✂️ *Хотите стать мастером?* Нажмите кнопку «Стать мастером» и напишите мне в личные сообщения.",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


from aiogram.filters import Command

# ЗАМЕНИ НА СВОЙ TELEGRAM ID (узнай у @userinfobot)
ADMIN_ID = 868528632

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
    
    # Отправляем запрос к API для сохранения токена
    import aiohttp
    async with aiohttp.ClientSession() as session:
        # Здесь нужно знать master_id. Пока сохраняем в переменную, потом привяжешь к нужному мастеру
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
Symbols
Find definitions and references for functions and other symbols in this file by clicking a symbol below or in the code.

Filter symbols
r
R
const
logger
const
BOT_TOKEN
const
API_URL
const
bot
const
dp
func
start
const
ADMIN_ID
func
register_master_bot
func
main
