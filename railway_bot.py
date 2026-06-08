import asyncio
import logging
import os
import aiohttp
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, PreCheckoutQuery, SuccessfulPayment
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8236516081:AAFjIjQBiAMs95XpURSCZZhuuYr5yDrcmlw")
PROVIDER_TOKEN = os.getenv("PROVIDER_TOKEN", "твой_платежный_токен_из_юкассы")  # 👈 ЗАМЕНИ НА СВОЙ ТОКЕН!
API_URL = os.getenv("API_URL", "https://intuitive-fascination-production-ce82.up.railway.app")
CHANNEL_USERNAME = "@pinkspotnews"
COMMISSION_PERCENT = 7  # Фиксированная комиссия 7%

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ========== АДМИНЫ ==========
ADMIN_IDS = [868528632]  # ТВОЙ TELEGRAM ID

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

async def api_request(method: str, endpoint: str, data: dict = None):
    """Универсальная функция для запросов к API"""
    url = f"{API_URL}{endpoint}"
    async with aiohttp.ClientSession() as session:
        try:
            if method == "GET":
                async with session.get(url) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return None
            elif method == "POST":
                async with session.post(url, json=data) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return None
            elif method == "PATCH":
                async with session.patch(url, json=data) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return None
            elif method == "DELETE":
                async with session.delete(url) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.error(f"API ошибка {method} {endpoint}: {e}")
            return None

async def check_subscription(user_id: int) -> bool:
    try:
        chat_member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return chat_member.status in ["member", "administrator", "creator"]
    except:
        return False

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ========== КЛАВИАТУРЫ ==========

def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить мастера", callback_data="admin_add_master")],
        [InlineKeyboardButton(text="📋 Список мастеров", callback_data="admin_list_masters")],
        [InlineKeyboardButton(text="🔗 Назначить Telegram ID", callback_data="admin_set_telegram")],
        [InlineKeyboardButton(text="✏️ Редактировать услуги", callback_data="admin_edit_services")],
        [InlineKeyboardButton(text="❌ Удалить мастера", callback_data="admin_delete_master")],
        [InlineKeyboardButton(text="🎫 Создать промокод", callback_data="admin_add_promo")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🗺️ Открыть карту", web_app=WebAppInfo(url="https://project-ev8r3.vercel.app"))]
    ])

def master_keyboard(master_id: int = None):
    keyboard = [
        [InlineKeyboardButton(text="📊 Мой кабинет", web_app=WebAppInfo(url="https://project-ev8r3.vercel.app"))],
        [InlineKeyboardButton(text="🔗 Поделиться ссылкой", callback_data="share_master_link")],
        [InlineKeyboardButton(text="🗺️ Карта клиентов", web_app=WebAppInfo(url="https://project-ev8r3.vercel.app"))]
    ]
    if master_id:
        keyboard.append([InlineKeyboardButton(text="⚙️ Управление услугами", callback_data=f"master_services_{master_id}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def client_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗺️ Найти мастера", web_app=WebAppInfo(url="https://project-ev8r3.vercel.app"))],
        [InlineKeyboardButton(text="🎫 Ввести промокод", callback_data="enter_promo")],
        [InlineKeyboardButton(text="📝 Стать мастером", url="https://t.me/pinkspotvelur")]
    ])

def subscription_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/pinkspotnews")],
        [InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_sub")]
    ])

def back_to_admin():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в админ-панель", callback_data="admin_back")]
    ])

# ========== КОМАНДА /START ==========

@dp.message(CommandStart())
async def start(message: types.Message):
    user_id = message.from_user.id
    text = message.text
    
    logger.info(f"Пользователь {user_id} вызвал /start")
    
    # Регистрация пользователя
    await api_request("POST", "/user/register", {"telegram_id": str(user_id)})
    
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
    if is_admin(user_id):
        logger.info(f"Админ {user_id} получил админ-панель")
        await message.answer(
            "👑 *Beauty Bot Admin Panel*\n\n"
            "👥 Управление мастерами\n"
            "🎫 Промокоды\n"
            "📊 Статистика\n\n"
            "Выберите действие:",
            parse_mode="Markdown",
            reply_markup=admin_keyboard()
        )
        return
    
    # ========== ПРОВЕРКА НА МАСТЕРА ==========
    master_data = await api_request("GET", f"/masters/by_telegram/{user_id}")
    
    if master_data and master_data.get("id"):
        master_name = master_data.get("name", "Мастер")
        master_id = master_data.get("id")
        logger.info(f"Мастер {master_name} (ID: {user_id}) авторизован")
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
            reply_markup=master_keyboard(master_id)
        )
        return
    
    # ========== ОБЫЧНЫЙ КЛИЕНТ ==========
    logger.info(f"Обычный клиент {user_id}")
    await message.answer(
        "💅 *Добро пожаловать в Beauty Map!*\n\n"
        "Нажми кнопку ниже, чтобы найти мастера рядом с тобой.\n\n"
        "✂️ *Хотите стать мастером?* Нажмите кнопку «Стать мастером».",
        parse_mode="Markdown",
        reply_markup=client_keyboard()
    )


# ========== НАТИВНАЯ ОПЛАТА ЧЕРЕЗ ЮKASSA ==========

@dp.callback_query(F.data.startswith("pay_commission_"))
async def handle_pay_commission(callback: types.CallbackQuery):
    """Обработка нажатия на кнопку оплаты комиссии (вызывается из веб-приложения)"""
    booking_id = int(callback.data.split("_")[2])
    
    # Получаем информацию о бронировании через API
    booking = await api_request("GET", f"/bookings/client/{callback.from_user.id}")
    if not booking:
        await callback.answer("❌ Запись не найдена", show_alert=True)
        return
    
    target_booking = None
    for b in booking:
        if b.get("id") == booking_id:
            target_booking = b
            break
    
    if not target_booking:
        await callback.answer("❌ Запись не найдена", show_alert=True)
        return
    
    commission_amount = target_booking.get("commission_amount", 0)
    service_name = target_booking.get("service_name", "Услуга")
    
    if commission_amount <= 0:
        await callback.answer("✅ Комиссия уже оплачена", show_alert=True)
        return
    
    # Сумма в копейках (Telegram требует копейки)
    amount_kopecks = int(commission_amount * 100)
    
    # Данные для чека (provider_data)
    provider_data = {
        "receipt": {
            "items": [{
                "description": f"Комиссия Beauty Map ({COMMISSION_PERCENT}%) за запись: {service_name}",
                "quantity": "1.00",
                "amount": {
                    "value": f"{commission_amount:.2f}",
                    "currency": "RUB"
                },
                "vat_code": 1,
                "payment_mode": "full_payment",
                "payment_subject": "service"
            }],
            "customer": {
                "email": f"user_{callback.from_user.id}@beauty-map.ru"
            }
        }
    }
    
    try:
        await bot.send_invoice(
            chat_id=callback.from_user.id,
            title=f"💸 Комиссия Beauty Map",
            description=f"Комиссия {COMMISSION_PERCENT}% за запись: {service_name}",
            payload=f"commission_{booking_id}",
            provider_token=PROVIDER_TOKEN,
            currency="RUB",
            prices=[LabeledPrice(label="Комиссия сервиса", amount=amount_kopecks)],
            need_email=True,
            send_email_to_provider=True,
            provider_data=json.dumps(provider_data)
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка отправки инвойса: {e}")
        await callback.answer(f"❌ Ошибка: {str(e)[:100]}", show_alert=True)

@dp.pre_checkout_query()
async def pre_checkout_query_handler(pre_checkout_q: PreCheckoutQuery):
    """Обработка предварительного запроса перед оплатой (обязательно ответить в течение 10 секунд)"""
    logger.info(f"PreCheckoutQuery получен: {pre_checkout_q.id}")
    
    # Обязательно отвечаем в течение 10 секунд!
    await bot.answer_pre_checkout_query(
        pre_checkout_query_id=pre_checkout_q.id,
        ok=True
    )

@dp.message(lambda message: message.successful_payment is not None)
async def successful_payment_handler(message: types.Message):
    """Обработка успешного платежа"""
    payment = message.successful_payment
    payload = payment.invoice_payload
    telegram_payment_charge_id = payment.telegram_payment_charge_id
    provider_payment_charge_id = payment.provider_payment_charge_id
    
    logger.info(f"Успешный платеж: {telegram_payment_charge_id}")
    
    # Парсим payload (commission_123)
    if payload.startswith("commission_"):
        booking_id = int(payload.split("_")[1])
        
        # Обновляем статус платежа в БД через API
        result = await api_request("POST", "/payment-callback", {
            "payment_id": provider_payment_charge_id,
            "booking_id": booking_id
        })
        
        await message.answer(
            f"✅ *Оплата прошла успешно!*\n\n"
            f"Ваша запись подтверждена. Чат с мастером открыт.\n\n"
            f"📄 ID платежа: `{telegram_payment_charge_id}`\n\n"
            f"💬 Чат с мастером будет доступен в разделе «Записи».",
            parse_mode="Markdown"
        )


# ========== АДМИН-КОЛБЭКИ ==========

@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "👑 *Beauty Bot Admin Panel*\n\n"
        "Выберите действие:",
        parse_mode="Markdown",
        reply_markup=admin_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_add_master")
async def admin_add_master(callback: types.CallbackQuery):
    await callback.message.answer(
        "➕ *Добавление мастера*\n\n"
        "Отправьте данные в формате:\n"
        "`Имя | Адрес | Телефон | Instagram | Описание`\n\n"
        "Пример:\n"
        "`Алина Козлова | ул. Ленина, 12 | +79001234567 | @alina_nails | Мастер маникюра 6 лет опыта`\n\n"
        "📍 *Важно:* после добавления назначьте Telegram ID мастеру через пункт «Назначить Telegram ID».",
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message(lambda msg: msg.text and " | " in msg.text and is_admin(msg.from_user.id))
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
    
    result = await api_request("POST", "/admin/add-master", {
        "name": name,
        "address": address,
        "phone": phone,
        "instagram": instagram,
        "description": description
    })
    
    if result:
        master_id = result.get("id")
        await message.answer(
            f"✅ Мастер *{name}* добавлен!\n\n"
            f"🆔 ID мастера: `{master_id}`\n\n"
            f"🔗 Теперь назначьте ему Telegram ID через пункт «Назначить Telegram ID».\n\n"
            f"💡 Команда: `/admin` для возврата в админ-панель",
            parse_mode="Markdown"
        )
    else:
        await message.answer("❌ Ошибка при добавлении мастера")

@dp.callback_query(F.data == "admin_list_masters")
async def admin_list_masters(callback: types.CallbackQuery):
    masters = await api_request("GET", "/masters")
    
    if not masters:
        await callback.message.answer("📭 Нет мастеров в базе", reply_markup=back_to_admin())
    else:
        text = "📋 *Список мастеров:*\n\n"
        for m in masters[:15]:
            text += f"🆔 *ID:* `{m.get('id', '?')}`\n"
            text += f"👤 *Имя:* {m.get('name', '?')}\n"
            text += f"🤖 *Telegram ID:* {m.get('telegram_id') or '❌ не назначен'}\n"
            text += f"⭐ *Рейтинг:* {m.get('rating', '0')}\n"
            text += f"✅ *Записей:* {m.get('completed_bookings', 0)}\n"
            text += "─" * 25 + "\n\n"
        
        if len(masters) > 15:
            text += f"\n📊 *Всего мастеров:* {len(masters)}\n"
        
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=back_to_admin())
    
    await callback.answer()

@dp.callback_query(F.data == "admin_set_telegram")
async def admin_set_telegram_prompt(callback: types.CallbackQuery):
    masters = await api_request("GET", "/masters")
    if masters:
        no_telegram = [m for m in masters if not m.get('telegram_id')]
        if no_telegram:
            hint = "📋 *Мастера без Telegram ID:*\n"
            for m in no_telegram[:5]:
                hint += f"🆔 ID: `{m.get('id')}` — {m.get('name')}\n"
            hint += "\n"
        else:
            hint = "✅ У всех мастеров назначен Telegram ID\n\n"
    else:
        hint = ""
    
    await callback.message.answer(
        f"🔗 *Назначение Telegram ID мастеру*\n\n"
        f"{hint}"
        f"Отправьте в формате:\n"
        f"`ID_МАСТЕРА TELEGRAM_ID`\n\n"
        f"Пример:\n"
        f"`1 123456789`\n\n"
        f"💡 *Как узнать Telegram ID:* напишите @userinfobot",
        parse_mode="Markdown",
        reply_markup=back_to_admin()
    )
    await callback.answer()

@dp.message(lambda msg: msg.text and len(msg.text.split()) == 2 and is_admin(msg.from_user.id) and msg.text.split()[0].isdigit())
async def handle_set_telegram(message: types.Message):
    parts = message.text.split()
    master_id = parts[0]
    telegram_id = parts[1]
    
    result = await api_request("PATCH", f"/masters/{master_id}/telegram", {"telegram_id": telegram_id})
    
    if result:
        await message.answer(
            f"✅ Telegram ID `{telegram_id}` назначен мастеру ID {master_id}\n\n"
            f"🎉 Теперь мастер может войти в свой кабинет через /start",
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            f"❌ Ошибка при назначении Telegram ID.\n\n"
            f"Проверьте, существует ли мастер с ID {master_id}.\n"
            f"Список ID можно посмотреть в «Список мастеров»."
        )

@dp.callback_query(F.data == "admin_edit_services")
async def admin_edit_services_prompt(callback: types.CallbackQuery):
    await callback.message.answer(
        "✏️ *Редактирование услуг мастера*\n\n"
        "Отправьте в формате:\n"
        "`ID_МАСТЕРА НАЗВАНИЕ | ЦЕНА | ДЛИТЕЛЬНОСТЬ`\n\n"
        "Пример:\n"
        "`1 Маникюр классический | 1200 | 60`\n\n"
        "📍 Длительность в минутах\n\n"
        "Чтобы удалить услугу:\n"
        "`ID_МАСТЕРА DELETE НАЗВАНИЕ`",
        parse_mode="Markdown",
        reply_markup=back_to_admin()
    )
    await callback.answer()

@dp.message(lambda msg: msg.text and is_admin(msg.from_user.id) and (" | " in msg.text or "DELETE" in msg.text.upper()))
async def handle_edit_services(message: types.Message):
    text = message.text
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❌ Неверный формат")
        return
    
    master_id = parts[0]
    rest = parts[1]
    
    if "DELETE" in rest.upper():
        service_name = rest.replace("DELETE", "").strip()
        result = await api_request("DELETE", f"/master/{master_id}/services", {"name": service_name})
        if result:
            await message.answer(f"✅ Услуга *{service_name}* удалена у мастера ID {master_id}", parse_mode="Markdown")
        else:
            await message.answer("❌ Ошибка при удалении услуги")
    else:
        service_parts = rest.split(" | ")
        if len(service_parts) < 3:
            await message.answer("❌ Неверный формат. Используйте: `Название | Цена | Длительность`")
            return
        
        service_name = service_parts[0].strip()
        price = int(service_parts[1].strip())
        duration = int(service_parts[2].strip())
        
        result = await api_request("POST", f"/master/{master_id}/services", {
            "name": service_name,
            "price": price,
            "duration_min": duration
        })
        
        if result:
            await message.answer(
                f"✅ Услуга *{service_name}* добавлена мастеру ID {master_id}\n\n"
                f"💰 Цена: {price} ₽\n"
                f"⏱️ Длительность: {duration} мин",
                parse_mode="Markdown"
            )
        else:
            await message.answer("❌ Ошибка при добавлении услуги")

@dp.callback_query(F.data == "admin_delete_master")
async def admin_delete_master_prompt(callback: types.CallbackQuery):
    await callback.message.answer(
        "❌ *Удаление мастера*\n\n"
        "Отправьте ID мастера для удаления:\n"
        "`ID`\n\n"
        "Пример:\n"
        "`1`\n\n"
        "⚠️ *Внимание:* все записи и услуги мастера будут удалены!\n\n"
        "📋 Список ID мастеров можно посмотреть в «Список мастеров»",
        parse_mode="Markdown",
        reply_markup=back_to_admin()
    )
    await callback.answer()

@dp.message(lambda msg: msg.text and msg.text.isdigit() and is_admin(msg.from_user.id))
async def handle_delete_master(message: types.Message):
    master_id = int(message.text)
    
    masters = await api_request("GET", "/masters")
    master_name = next((m.get("name") for m in masters if m.get("id") == master_id), f"ID {master_id}")
    
    success = await api_request("DELETE", f"/masters/{master_id}")
    
    if success:
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
        "Скидка в процентах, действует указанное количество дней.\n\n"
        "Максимальное количество использований: 100",
        parse_mode="Markdown",
        reply_markup=back_to_admin()
    )
    await callback.answer()

@dp.message(lambda msg: msg.text and len(msg.text.split()) == 3 and is_admin(msg.from_user.id))
async def handle_add_promo(message: types.Message):
    parts = message.text.split()
    code = parts[0].upper()
    discount = int(parts[1])
    days = int(parts[2])
    
    valid_until = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    
    result = await api_request("POST", "/admin/add-promo", {
        "code": code,
        "discount_percent": discount,
        "valid_until": valid_until,
        "max_uses": 100
    })
    
    if result:
        await message.answer(
            f"✅ Промокод `{code}` создан!\n\n"
            f"🎁 Скидка {discount}%\n"
            f"📅 Действует до {valid_until}\n"
            f"🔢 Максимум использований: 100",
            parse_mode="Markdown"
        )
    else:
        await message.answer("❌ Ошибка при создании промокода")

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    masters = await api_request("GET", "/masters") or []
    masters_count = len(masters)
    
    all_bookings = []
    for master in masters:
        bookings = await api_request("GET", f"/bookings/master/{master['id']}") or []
        all_bookings.extend(bookings)
    
    bookings_count = len(all_bookings)
    confirmed_bookings = [b for b in all_bookings if b.get("status") == "confirmed"]
    total_revenue = sum(b.get("price", 0) for b in confirmed_bookings)
    
    text = f"📊 *СТАТИСТИКА BEAUTY MAP*\n\n"
    text += f"👨‍💼 *Мастеров:* {masters_count}\n"
    text += f"📅 *Всего записей:* {bookings_count}\n"
    text += f"✅ *Подтверждённых:* {len(confirmed_bookings)}\n"
    text += f"💰 *Выручка:* {total_revenue} ₽\n"
    text += f"💸 *Комиссия сервиса:* {COMMISSION_PERCENT}%\n\n"
    
    if masters_count > 0:
        text += f"📈 *Средняя выручка на мастера:* {total_revenue // masters_count} ₽"
    
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=back_to_admin())
    await callback.answer()


# ========== МАСТЕР-КОЛБЭКИ ==========

@dp.callback_query(F.data == "share_master_link")
async def share_master_link(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    master_data = await api_request("GET", f"/masters/by_telegram/{user_id}")
    
    if master_data:
        link = f"https://project-ev8r3.vercel.app/?id={master_data['id']}"
        await callback.message.answer(
            f"🔗 *Ваша персональная ссылка:*\n"
            f"`{link}`\n\n"
            f"📤 Отправьте её клиентам — они сразу попадут на вашу страницу с услугами.\n\n"
            f"💡 *Совет:* добавьте ссылку в Instagram Bio или закрепите в Telegram!",
            parse_mode="Markdown"
        )
    else:
        await callback.answer("❌ Ошибка: вы не зарегистрированы как мастер", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data.startswith("master_services_"))
async def master_services_callback(callback: types.CallbackQuery):
    master_id = int(callback.data.split("_")[2])
    await callback.message.answer(
        f"✏️ *Управление услугами*\n\n"
        f"Для добавления услуги отправьте:\n"
        f"`Название | Цена | Длительность`\n\n"
        f"Пример:\n"
        f"`Наращивание ресниц | 3000 | 120`\n\n"
        f"Для удаления услуги отправьте:\n"
        f"`DELETE Название`\n\n"
        f"💡 После изменения обновите кабинет мастера на карте.",
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message(lambda msg: " | " in msg.text and not is_admin(msg.from_user.id))
async def handle_master_add_service(message: types.Message):
    user_id = message.from_user.id
    master_data = await api_request("GET", f"/masters/by_telegram/{user_id}")
    
    if not master_data:
        await message.answer("❌ Вы не зарегистрированы как мастер")
        return
    
    parts = message.text.split(" | ")
    if len(parts) < 3:
        await message.answer("❌ Неверный формат. Используйте: `Название | Цена | Длительность`", parse_mode="Markdown")
        return
    
    service_name = parts[0].strip()
    price = int(parts[1].strip())
    duration = int(parts[2].strip())
    
    result = await api_request("POST", f"/master/{master_data['id']}/services", {
        "name": service_name,
        "price": price,
        "duration_min": duration
    })
    
    if result:
        await message.answer(
            f"✅ Услуга *{service_name}* добавлена!\n\n"
            f"💰 Цена: {price} ₽\n"
            f"⏱️ Длительность: {duration} мин\n\n"
            f"📊 Обновите кабинет мастера на карте, чтобы увидеть изменения.",
            parse_mode="Markdown"
        )
    else:
        await message.answer("❌ Ошибка при добавлении услуги")

@dp.message(lambda msg: msg.text and msg.text.upper().startswith("DELETE") and not is_admin(msg.from_user.id))
async def handle_master_delete_service(message: types.Message):
    user_id = message.from_user.id
    master_data = await api_request("GET", f"/masters/by_telegram/{user_id}")
    
    if not master_data:
        await message.answer("❌ Вы не зарегистрированы как мастер")
        return
    
    service_name = message.text.replace("DELETE", "").strip()
    
    result = await api_request("DELETE", f"/master/{master_data['id']}/services", {"name": service_name})
    
    if result:
        await message.answer(f"✅ Услуга *{service_name}* удалена", parse_mode="Markdown")
    else:
        await message.answer("❌ Ошибка при удалении услуги")


# ========== КЛИЕНТ-КОЛБЭКИ ==========

@dp.callback_query(F.data == "enter_promo")
async def enter_promo_prompt(callback: types.CallbackQuery):
    await callback.message.answer(
        "🎫 *Введите промокод*\n\n"
        "Отправьте код одним сообщением.\n\n"
        "Пример: `SUMMER20`\n\n"
        "✅ После активации скидка применится к следующей записи.",
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message(lambda msg: msg.text and len(msg.text) < 30 and not is_admin(msg.from_user.id) and not msg.text.startswith("/"))
async def handle_enter_promo(message: types.Message):
    user_id = message.from_user.id
    promo_code = message.text.upper().strip()
    
    result = await api_request("POST", "/apply-promo", {
        "user_id": str(user_id),
        "promo_code": promo_code
    })
    
    if result:
        discount = result.get("discount_percent", 0)
        await message.answer(
            f"✅ Промокод `{promo_code}` активирован!\n\n"
            f"🎁 Скидка {discount}% будет применена к следующей записи.\n\n"
            f"📅 Действует до {result.get('valid_until', 'указанной даты')}",
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            f"❌ Промокод `{promo_code}` недействителен или уже использован.\n\n"
            f"Проверьте правильность написания и попробуйте снова.",
            parse_mode="Markdown"
        )


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


# ========== КОМАНДЫ ==========

@dp.message(Command("close_chat"))
async def close_chat(message: types.Message):
    await message.answer(
        "💬 *Чат закрыт*\n\n"
        "Чтобы начать новый чат, откройте ссылку из уведомления о записи.\n\n"
        "📍 Основное меню: /start",
        parse_mode="Markdown"
    )

@dp.message(Command("admin"))
async def admin_command(message: types.Message):
    if is_admin(message.from_user.id):
        await start(message)
    else:
        await message.answer("⛔ У вас нет доступа к админ-панели")


# ========== ЗАПУСК ==========

async def main():
    logger.info("🚀 Бот запущен")
    logger.info(f"👑 Админы: {ADMIN_IDS}")
    logger.info(f"🌐 API URL: {API_URL}")
    logger.info(f"💸 Комиссия: {COMMISSION_PERCENT}%")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
