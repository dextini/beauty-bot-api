# client_bot.py
import logging
import os
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = "8236516081:AAFjIjQBiAMs95XpURSCZZhuuYr5yDrcmlw"
API_URL = "https://intuitive-fascination-production-ce82.up.railway.app"
MAIN_APP_URL = "https://intuitive-fascination-production-ce82.up.railway.app"

def get_db():
    db_path = os.path.join(os.getcwd(), "data", "beauty.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def get_master_by_id(master_id):
    conn = get_db()
    try:
        master = conn.execute("SELECT * FROM masters WHERE id = ?", (master_id,)).fetchone()
        if master:
            services = conn.execute("SELECT * FROM services WHERE master_id = ?", (master_id,)).fetchall()
            master_dict = dict(master)
            master_dict['services'] = [dict(s) for s in services]
            return master_dict
        return None
    finally:
        conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        text = update.message.text
        payload = text.replace('/start', '').strip()
        
        logger.info(f"🔄 /start от {user.id} с payload: '{payload}'")
        
        # ===== ЕСЛИ ЕСТЬ ПАРАМЕТР master_XXX =====
        if payload and payload.startswith('master_'):
            master_id_str = payload.replace('master_', '')
            
            try:
                master_id = int(master_id_str)
                master = get_master_by_id(master_id)
                
                if master:
                    webapp_url = f"{MAIN_APP_URL}?start=master_{master_id}"
                    
                    services_text = ""
                    if master.get('services'):
                        services_list = [f"• {s['name']} — {s['price']} ₽" for s in master['services'][:5]]
                        services_text = "\n".join(services_list)
                        if len(master['services']) > 5:
                            services_text += f"\n• ... и ещё {len(master['services']) - 5} услуг"
                    else:
                        services_text = "У мастера пока нет услуг"
                    
                    avatar_url = master.get('avatar')
                    avatar_text = ""
                    if avatar_url:
                        photo_url = avatar_url if avatar_url.startswith('http') else API_URL + avatar_url
                        
                        await update.message.reply_photo(
                            photo=photo_url,
                            caption=(
                                f"🌸 *{master['name']}*\n\n"
                                f"⭐ Рейтинг: {master.get('rating', 4.8)} ★\n"
                                f"📍 {master.get('address', 'Адрес не указан')}\n"
                                f"📞 {master.get('phone', 'Телефон не указан')}\n\n"
                                f"💅 *Услуги:*\n{services_text}\n\n"
                                f"👇 *Нажмите кнопку*, чтобы записаться:"
                            ),
                            parse_mode="Markdown"
                        )
                    else:
                        await update.message.reply_text(
                            f"🌸 *{master['name']}*\n\n"
                            f"⭐ Рейтинг: {master.get('rating', 4.8)} ★\n"
                            f"📍 {master.get('address', 'Адрес не указан')}\n"
                            f"📞 {master.get('phone', 'Телефон не указан')}\n\n"
                            f"💅 *Услуги:*\n{services_text}\n\n"
                            f"👇 *Нажмите кнопку*, чтобы записаться:",
                            parse_mode="Markdown"
                        )
                    
                    keyboard = InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            "📅 ЗАПИСАТЬСЯ К МАСТЕРУ",
                            web_app=WebAppInfo(url=webapp_url)
                        )
                    ]])
                    
                    await update.message.reply_text(
                        "Нажмите кнопку ниже, чтобы открыть профиль мастера и записаться 👇",
                        reply_markup=keyboard
                    )
                    
                    logger.info(f"✅ Отправлен профиль мастера {master['name']} (ID: {master_id})")
                    
                else:
                    await fallback_start(update)
                    
            except ValueError:
                await fallback_start(update)
                
        # ===== ОБЫЧНЫЙ START =====
        else:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "🌸 ОТКРЫТЬ BEAUTY CONNECT",
                    web_app=WebAppInfo(url=MAIN_APP_URL)
                )
            ]])
            
            await update.message.reply_text(
                "🌸 *Beauty Connect*\n\n"
                "Добро пожаловать в приложение для записи к мастерам красоты! 💅\n\n"
                "✨ *Что вы можете делать:*\n"
                "• Находить мастеров на карте\n"
                "• Смотреть портфолио и отзывы\n"
                "• Записываться на услуги\n"
                "• Оплачивать депозит\n"
                "• Общаться с мастером в чате\n\n"
                "👇 *Нажмите кнопку*, чтобы открыть приложение:",
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            
            logger.info(f"✅ Обычный /start от {user.id} ({user.first_name})")
            
    except Exception as e:
        logger.error(f"❌ Ошибка в /start: {e}")
        await fallback_start(update)

async def fallback_start(update: Update):
    try:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "🌸 ОТКРЫТЬ BEAUTY CONNECT",
                web_app=WebAppInfo(url=MAIN_APP_URL)
            )
        ]])
        await update.message.reply_text(
            "🌸 *Beauty Connect*\n\nНажмите кнопку, чтобы открыть приложение:",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"❌ Ошибка в fallback_start: {e}")

def main():
    try:
        logger.info("🚀 Запуск бота Beauty Connect...")
        app = Application.builder().token(TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        logger.info("✅ Бот запущен и готов к работе!")
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске бота: {e}")

if __name__ == "__main__":
    main()
