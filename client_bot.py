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
CHANNEL_USERNAME = "@pinkspotnews"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ========== АДМИНЫ ==========
ADMIN_IDS = [868528632]  # ЗАМЕНИ НА СВОЙ TELEGRAM ID

# ========== ПРОВЕРКА ПОДПИСКИ ==========
async def check_subscription(user_id: int) -> bool:
    try:
        chat_member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return chat_member.status in ["member", "administrator", "creator"]
    except:
        return False

# ========== КЛАВИАТУРЫ ==========
def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить мастера", callback_data="admin_add_master")],
        [InlineKeyboardButton(text="📋 Список мастеров", callback_data="admin_list_masters")],
        [InlineKeyboardButton(text="🔗 Назначить Telegram ID", callback_data="admin_set_telegram")],
        [InlineKeyboardButton(text="❌ Удалить мастера", callback_data="admin_delete_master")],
        [InlineKeyboardButton(text="🎫 Создать промокод", callback_data="admin_add_promo")],
        [InlineKeyboardButton(text="🗺️ Открыть карту", web_app=WebAppInfo(url="https://project-ev8r3.vercel.app"))]
    ])

def master_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Мой кабинет мастера", web_app=WebAppInfo(url="https://project-ev8r3.vercel.app"))],
        [InlineKeyboardButton(text="🔗 Поделиться ссылкой", callback_data="share_master_link")],
        [InlineKeyboardButton(text="🗺️ Открыть карту клиентов", web_app=WebAppInfo(url="https://project-ev8r3.vercel.app"))]
    ])

def client_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗺️ Открыть карту мастеров", web_app=WebAppInfo(url="https://project-ev8r3.vercel.app"))],
        [InlineKeyboardButton(text="📝 Стать мастером", url="https://t.me/pinkspotvelur")]
    ])

def subscription_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/pinkspotnews")],
        [InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_sub")]
    ])

# ========== ОСНОВНАЯ КОМАНДА /START ==========
@dp.message(CommandStart())
async def start(message: types.Message):
    user_id = message.from_user.id
    text = message.text
    
    # Регистрация пользователя
    async with aiohttp.ClientSession() as session:
        await session.post(f"{API_URL}/user/register", json={"telegram_id": str(user_id)})
    
    # Обработка чата
    if text.startswith("/start chat_"):
        token = text.replace("/start chat_", "")
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_URL}/chat/{token}") as resp:
                if resp.status == 200:
                    await message.answer(
                        "💬 *Чат открыт!*\n\n"
                        "Вы можете общаться с мастером/клиентом здесь.\n"
                        "✉️ *Чтобы закрыть чат, напишите /close_chat*",
                        parse_mode="Markdown"
                    )
                else:
                    await message.answer("❌ Чат не найден или устарел")
        return
    
    # Обработка оплаты
    if text.startswith("/start pay_"):
        payment_id = text.replace("/start pay_", "")
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{API_URL}/payment-callback", json={"payment_id": payment_id}) as resp:
                if resp.status == 200:
                    await message.answer(
                        "✅ *Оплата подтверждена!*\n\n"
                        "Ваша запись подтверждена, и чат с мастером открыт.",
                        parse_mode="Markdown"
                    )
                else:
                    await message.answer("❌ Ошибка подтверждения оплаты")
        return
    
    # Проверка подписки на канал
    is_subscribed = await check_subscription(user_id)
    if not is_subscribed:
        await message.answer(
            "🌸 *Требуется подписка!*\n\n"
            "Чтобы пользоваться картой мастеров, подпишись на наш канал:\n"
            f"👉 [pinkspot news](https://t.me/pinkspotnews)\n\n"
            "После подписки нажми «Проверить подписку».",
            reply_markup=subscription_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    # ========== АДМИН-ПАНЕЛЬ ==========
    if user_id in ADMIN_IDS:
        await message.answer(
            "👑 *Beauty Bot Admin Panel*\n\n"
            "Выберите действие:",
            parse_mode="Markdown",
            reply_markup=admin_keyboard()
        )
        return
    
    # ========== ПРОВЕРКА НА МАСТЕРА ==========
    is_master = False
    master_name = None
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{API_URL}/masters/by_telegram/{user_id}") as resp:
                if resp.status == 200:
                    master_data = await resp.json()
                    is_master = True
                    master_name = master_data.get("name")
        except:
            pass
    
    if is_master:
        await message.answer(
            f"👋 *Здравствуйте, {master_name}!*\n\n"
            f"✅ Вы зарегистрированы как мастер Beauty Map.\n\n"
            f"📊 Нажмите «Мой кабинет мастера» для управления:\n"
            f"• Услугами и ценами\n"
            f"• Расписанием и днями отдыха\n"
            f"• Просмотром записей клиентов\n"
            f"• Общением в чате\n\n"
            f"🔗 Можете поделиться ссылкой на свой профиль с клиентами!",
            parse_mode="Markdown",
            reply_markup=master_keyboard()
        )
        return
    
    # ========== ОБЫЧНЫЙ КЛИЕНТ ==========
    await message.answer(
        "💅 *Добро пожаловать в Beauty Map!*\n\n"
        "Нажми кнопку ниже, чтобы найти мастера рядом с тобой.\n\n"
        "✂️ *Хотите стать мастером?* Нажмите кнопку «Стать мастером».",
        parse_mode="Markdown",
        reply_markup=client_keyboard()
    )


# ========== АДМИН-КОЛБЭКИ ==========

@dp.callback_query(F.data == "admin_add_master")
async def admin_add_master(callback: types.CallbackQuery):
    await callback.message.answer(
        "➕ *Добавление мастера*\n\n"
        "Отправьте данные в формате:\n"
        "`Имя | Адрес | Телефон | Instagram | Описание`\n\n"
        "Пример:\n"
        "`Алина Козлова | ул. Ленина, 12 | +79001234567 | @alina_nails | Мастер маникюра`\n\n"
        "📍 *Важно:* после добавления назначьте Telegram ID мастеру через пункт «Назначить Telegram ID».",
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.message(lambda msg: msg.text and " | " in msg.text and msg.from_user.id in ADMIN_IDS)
async def handle_add_master(message: types.Message):
    parts = message.text.split(" | ")
    if len(parts) < 2:
        await message.answer("❌ Неверный формат. Используйте: `Имя | Адрес | Телефон | Instagram | Описание`", parse_mode="Markdown")
        return
    
    name = parts[0].strip()
    address = parts[1].strip()
    phone = parts[2].strip() if len(parts) > 2 else ""
    instagram = parts[3].strip() if len(parts) > 3 else ""
    description = parts[4].strip() if len(parts) > 4 else ""
    
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/admin/add-master", json={
            "name": name,
            "address": address,
            "phone": phone,
            "instagram": instagram,
            "description": description
        }) as resp:
            if resp.status == 200:
                await message.answer(f"✅ Мастер *{name}* добавлен!\n\n🔗 Теперь назначьте ему Telegram ID через пункт «Назначить Telegram ID».", parse_mode="Markdown")
            else:
                await message.answer("❌ Ошибка при добавлении мастера")


@dp.callback_query(F.data == "admin_list_masters")
async def admin_list_masters(callback: types.CallbackQuery):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_URL}/admin/masters") as resp:
            if resp.status == 200:
                masters = await resp.json()
                if not masters:
                    await callback.message.answer("📭 Нет мастеров в базе")
                else:
                    text = "📋 *Список мастеров:*\n\n"
                    for m in masters:
                        text += f"🆔 *ID:* {m['id']}\n"
                        text += f"👤 *Имя:* {m['name']}\n"
                        text += f"🤖 *Telegram ID:* {m.get('telegram_id') or '❌ не назначен'}\n"
                        text += f"📞 *Телефон:* {m.get('phone') or '-'}\n"
                        text += f"📷 *Instagram:* {m.get('instagram') or '-'}\n"
                        text += f"🔤 *Иконка:* {m.get('icon') or '💅'}\n"
                        text += "─" * 25 + "\n\n"
                    
                    if len(masters) > 10:
                        text += f"\n📊 *Всего мастеров:* {len(masters)}"
                    
                    await callback.message.answer(text, parse_mode="Markdown")
            else:
                await callback.message.answer("❌ Ошибка загрузки списка мастеров")
    await callback.answer()


@dp.callback_query(F.data == "admin_set_telegram")
async def admin_set_telegram_prompt(callback: types.CallbackQuery):
    await callback.message.answer(
        "🔗 *Назначение Telegram ID мастеру*\n\n"
        "Отправьте в формате:\n"
        "`ID_МАСТЕРА TELEGRAM_ID`\n\n"
        "Пример:\n"
        "`1 123456789`\n\n"
        "💡 *Как узнать Telegram ID:* напишите @userinfobot",
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.message(lambda msg: msg.text and len(msg.text.split()) == 2 and msg.from_user.id in ADMIN_IDS and msg.text.split()[0].isdigit())
async def handle_set_telegram(message: types.Message):
    parts = message.text.split()
    master_id = parts[0]
    telegram_id = parts[1]
    
    async with aiohttp.ClientSession() as session:
        async with session.patch(f"{API_URL}/admin/set-telegram/{master_id}?telegram_id={telegram_id}") as resp:
            if resp.status == 200:
                await message.answer(f"✅ Telegram ID `{telegram_id}` назначен мастеру ID {master_id}\n\n🎉 Теперь мастер может войти в свой кабинет через /start", parse_mode="Markdown")
            else:
                await message.answer("❌ Ошибка при назначении Telegram ID")


@dp.callback_query(F.data == "admin_delete_master")
async def admin_delete_master_prompt(callback: types.CallbackQuery):
    await callback.message.answer(
        "❌ *Удаление мастера*\n\n"
        "Отправьте ID мастера для удаления:\n"
        "`ID`\n\n"
        "Пример:\n"
        "`1`\n\n"
        "⚠️ *Внимание:* все записи и услуги мастера будут удалены!",
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.message(lambda msg: msg.text and msg.text.isdigit() and msg.from_user.id in ADMIN_IDS)
async def handle_delete_master(message: types.Message):
    master_id = message.text
    
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_URL}/admin/masters") as resp:
            masters = await resp.json()
            master_name = next((m.get("name") for m in masters if str(m.get("id")) == master_id), f"ID {master_id}")
    
    async with aiohttp.ClientSession() as session:
        async with session.delete(f"{API_URL}/admin/delete-master/{master_id}") as resp:
            if resp.status == 200:
                await message.answer(f"✅ Мастер *{master_name}* удалён", parse_mode="Markdown")
            else:
                await message.answer("❌ Ошибка при удалении мастера")


@dp.callback_query(F.data == "admin_add_promo")
async def admin_add_promo_prompt(callback: types.CallbackQuery):
    await callback.message.answer(
        "🎫 *Создание промокода*\n\n"
        "Отправьте в формате:\n"
        "`КОД СКИДКА% ДНЕЙ`\n\n"
        "Пример:\n"
        "`SUMMER20 20 30`\n\n"
        "Скидка в процентах, действует указанное количество дней.",
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.message(lambda msg: msg.text and len(msg.text.split()) == 3 and msg.from_user.id in ADMIN_IDS)
async def handle_add_promo(message: types.Message):
    parts = message.text.split()
    code = parts[0].upper()
    discount = int(parts[1])
    days = int(parts[2])
    
    from datetime import datetime, timedelta
    valid_until = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/admin/add-promo", json={
            "code": code,
            "discount_percent": discount,
            "valid_until": valid_until,
            "max_uses": 100
        }) as resp:
            if resp.status == 200:
                await message.answer(f"✅ Промокод `{code}` создан!\n🎁 Скидка {discount}% до {valid_until}", parse_mode="Markdown")
            else:
                await message.answer("❌ Ошибка при создании промокода")


# ========== МАСТЕР-КОЛБЭКИ ==========

@dp.callback_query(F.data == "share_master_link")
async def share_master_link(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_URL}/masters/by_telegram/{user_id}") as resp:
            if resp.status == 200:
                master = await resp.json()
                link = f"https://project-ev8r3.vercel.app/?id={master['id']}"
                await callback.message.answer(
                    f"🔗 *Ваша персональная ссылка:*\n"
                    f"`{link}`\n\n"
                    f"📤 Отправьте её клиентам — они сразу попадут на вашу страницу с услугами.\n\n"
                    f"💡 *Совет:* добавьте ссылку в Instagram Bio или закрепите в Telegram!",
                    parse_mode="Markdown"
                )
                await callback.answer()
            else:
                await callback.answer("❌ Ошибка: вы не зарегистрированы как мастер", show_alert=True)


# ========== ПРОВЕРКА ПОДПИСКИ ==========

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


# ========== КОМАНДА ЗАКРЫТЬ ЧАТ ==========

@dp.message(Command("close_chat"))
async def close_chat(message: types.Message):
    await message.answer(
        "💬 *Чат закрыт*\n\n"
        "Чтобы начать новый чат, откройте ссылку из уведомления о записи.",
        parse_mode="Markdown"
    )


# ========== ОБРАБОТКА СООБЩЕНИЙ ДЛЯ ЧАТА ==========
active_chats = {}

@dp.message()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    
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


# ========== ЗАПУСК ==========

async def main():
    logger.info("🚀 Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
