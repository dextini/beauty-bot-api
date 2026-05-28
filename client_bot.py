import asyncio
import logging
import os
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8236516081:AAFjIjQBiAMs95XpURSCZZhuuYr5yDrcmlw")
API_URL = os.getenv("API_URL", "https://intuitive-fascination-production-ce82.up.railway.app")
CHANNEL_USERNAME = "@pinkspotnews"  # ТВОЙ КАНАЛ

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Хранилище активных чатов
active_chats = {}


async def check_subscription(user_id: int) -> bool:
    try:
        chat_member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return chat_member.status in ["member", "administrator", "creator"]
    except:
        return False


@dp.message(CommandStart())
async def start(message: types.Message):
    user_id = message.from_user.id
    text = message.text
    
    # Проверка, не является ли команда открытием чата
    if text.startswith("/start chat_"):
        token = text.replace("/start chat_", "")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_URL}/chat/{token}") as resp:
                if resp.status == 200:
                    chat_data = await resp.json()
                    active_chats[user_id] = {
                        "type": "chat",
                        "booking_id": chat_data["booking_id"],
                        "other_party_id": chat_data["master_telegram_id"] if user_id == chat_data["client_telegram_id"] else chat_data["client_telegram_id"],
                        "token": token
                    }
                    await message.answer(
                        "💬 *Чат открыт!*\n\n"
                        "Вы можете общаться с мастером/клиентом здесь.\n"
                        "Просто пишите сообщения — они будут доставлены.\n\n"
                        "✉️ *Чтобы закрыть чат, напишите /close_chat*",
                        parse_mode="Markdown"
                    )
                else:
                    await message.answer("❌ Чат не найден или устарел")
        return
    
    # Проверка, не является ли команда подтверждением оплаты
    if text.startswith("/start payment_"):
        booking_id = int(text.replace("/start payment_", ""))
        
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{API_URL}/confirm-payment/{booking_id}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    await message.answer(
                        f"✅ *Оплата подтверждена!*\n\n"
                        f"Ваша запись подтверждена, и чат с мастером открыт.\n\n"
                        f"💬 [Перейти в чат]({data['chat_link']})",
                        parse_mode="Markdown"
                    )
                else:
                    await message.answer("❌ Ошибка подтверждения оплаты")
        return
    
    # Обычное начало
    is_subscribed = await check_subscription(user_id)
    
    if not is_subscribed:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/pinkspotnews")],
            [InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_sub")]
        ])
        await message.answer(
            "🌸 *Требуется подписка!*\n\n"
            "Чтобы пользоваться картой мастеров, подпишись на наш канал:\n"
            f"👉 [pinkspot news](https://t.me/pinkspotnews)\n\n"
            "После подписки нажми «Проверить подписку».",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗺️ Открыть карту мастеров", web_app=WebAppInfo(url="https://project-ev8r3.vercel.app"))],
        [InlineKeyboardButton(text="📝 Стать мастером", url="https://t.me/pinkspotvelur")]
    ])
    await message.answer(
        "💅 *Добро пожаловать в Beauty Map!*\n\n"
        "Нажми кнопку ниже, чтобы найти мастера рядом с тобой.\n\n"
        "✂️ *Хотите стать мастером?* Нажмите кнопку «Стать мастером» и напишите мне в личные сообщения.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


@dp.message()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    
    # Если пользователь в активном чате
    if user_id in active_chats and active_chats[user_id]["type"] == "chat":
        chat = active_chats[user_id]
        other_id = chat["other_party_id"]
        
        try:
            await bot.send_message(
                other_id,
                f"💬 *Сообщение от {'мастера' if user_id == chat.get('master_id', 0) else 'клиента'}*\n\n{message.text}",
                parse_mode="Markdown"
            )
            await message.answer("✅ Сообщение отправлено")
        except Exception as e:
            await message.answer(f"❌ Ошибка отправки: {e}")
        return


@dp.message(Command("close_chat"))
async def close_chat(message: types.Message):
    user_id = message.from_user.id
    if user_id in active_chats:
        del active_chats[user_id]
        await message.answer("💬 *Чат закрыт*\n\nЧтобы начать новый чат, откройте ссылку из уведомления о записи.", parse_mode="Markdown")
    else:
        await message.answer("❌ У вас нет активного чата")


@dp.callback_query(F.data == "check_sub")
async def check_subscription_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    is_subscribed = await check_subscription(user_id)
    
    if is_subscribed:
        await callback.message.delete()
        await start(callback.message)
        await callback.answer("✅ Спасибо за подписку!", show_alert=True)
    else:
        await callback.answer("❌ Ты ещё не подписан. Нажми на кнопку «Подписаться» и попробуй снова.", show_alert=True)


async def main():
    logger.info("🚀 Клиентский бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
