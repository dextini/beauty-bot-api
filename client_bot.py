# client_bot.py
import logging
import asyncio
import os
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================
#  КОНФИГУРАЦИЯ
# ============================================================
TOKEN = "8236516081:AAFjIjQBiAMs95XpURSCZZhuuYr5yDrcmlw"
API_URL = "https://intuitive-fascination-production-ce82.up.railway.app"
MAIN_APP_URL = "https://intuitive-fascination-production-ce82.up.railway.app"

# ============================================================
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================
def get_db():
    """Подключение к БД"""
    db_path = os.path.join(os.getcwd(), "data", "beauty.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def get_master_by_id(master_id):
    """Получить мастера по ID"""
    conn = get_db()
    try:
        master = conn.execute("SELECT * FROM masters WHERE id = ?", (master_id,)).fetchone()
        return dict(master) if master else None
    finally:
        conn.close()

# ============================================================
#  ОБРАБОТЧИК КОМАНДЫ /START
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    try:
        user = update.effective_user
        text = update.message.text
        payload = text.replace('/start', '').strip()
        
        logger.info(f"🔄 /start от {user.id} ({user.first_name}) с payload: '{payload}'")
        
        # ===== ЕСЛИ ЕСТЬ ПАРАМЕТР master_XXX =====
        if payload and payload.startswith('master_'):
            master_id_str = payload.replace('master_', '')
            logger.info(f"🔗 Глубокая ссылка на мастера: {master_id_str}")
            
            try:
                master_id = int(master_id_str)
                master = get_master_by_id(master_id)
                
                if master:
                    # Мастер найден → отправляем кнопку с WebApp
                    webapp_url = f"{MAIN_APP_URL}?start=master_{master_id}"
                    
                    await update.message.reply_text(
                        f"🌸 *Beauty Connect*\n\n"
                        f"Вы перешли по ссылке мастера *{master['name']}*\n\n"
                        f"⭐ Рейтинг: {master.get('rating', 4.8)} ★\n"
                        f"💅 Услуг: {len(master.get('services', []))}\n\n"
                        f"👇 Нажмите кнопку, чтобы открыть приложение и записаться:",
                        parse_mode="Markdown"
                    )
                    
                    keyboard = InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            "🌸 Открыть приложение",
                            web_app=WebAppInfo(url=webapp_url)
                        )
                    ]])
                    
                    await update.message.reply_text(
                        "Нажмите кнопку ниже 👇",
                        reply_markup=keyboard
                    )
                    
                    logger.info(f"✅ Отправлена кнопка с WebApp для мастера {master['name']} (ID: {master_id})")
                    
                else:
                    # Мастер не найден
                    logger.warning(f"⚠️ Мастер с ID {master_id} не найден в БД")
                    await update.message.reply_text(
                        "🌸 *Beauty Connect*\n\n"
                        "❌ Мастер не найден. Возможно, ссылка устарела.\n\n"
                        "Попробуйте найти мастера через приложение:",
                        parse_mode="Markdown"
                    )
                    keyboard = InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            "🌸 Открыть приложение",
                            web_app=WebAppInfo(url=MAIN_APP_URL)
                        )
                    ]])
                    await update.message.reply_text(
                        "Нажмите кнопку ниже 👇",
                        reply_markup=keyboard
                    )
                    
            except ValueError:
                logger.error(f"❌ Неверный формат master_id: {master_id_str}")
                await fallback_start(update)
                
        # ===== ОБЫЧНЫЙ START (без параметров) =====
        else:
            await update.message.reply_text(
                "🌸 *Beauty Connect*\n\n"
                "Добро пожаловать в приложение для записи к мастерам красоты! 💅\n\n"
                "✨ *Что вы можете делать:*\n"
                "• Находить мастеров на карте\n"
                "• Смотреть портфолио и отзывы\n"
                "• Записываться на услуги\n"
                "• Оплачивать депозит\n"
                "• Общаться с мастером в чате\n\n"
                "👇 Нажмите кнопку, чтобы открыть приложение:",
                parse_mode="Markdown"
            )
            
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "🌸 Открыть Beauty Connect",
                    web_app=WebAppInfo(url=MAIN_APP_URL)
                )
            ]])
            
            await update.message.reply_text(
                "Нажмите кнопку ниже 👇",
                reply_markup=keyboard
            )
            
            logger.info(f"✅ Обычный /start от {user.id} ({user.first_name})")
            
    except Exception as e:
        logger.error(f"❌ Ошибка в /start: {e}")
        await fallback_start(update)

# ============================================================
#  ЗАПАСНОЙ ВАРИАНТ /START (НА СЛУЧАЙ ОШИБКИ)
# ============================================================
async def fallback_start(update: Update):
    """Запасной вариант /start"""
    try:
        await update.message.reply_text(
            "🌸 *Beauty Connect*\n\n"
            "Добро пожаловать! Нажмите кнопку, чтобы открыть приложение:",
            parse_mode="Markdown"
        )
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "🌸 Открыть приложение",
                web_app=WebAppInfo(url=MAIN_APP_URL)
            )
        ]])
        await update.message.reply_text("👇", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"❌ Ошибка в fallback_start: {e}")

# ============================================================
#  ОБРАБОТЧИК ИНЛАЙН КНОПОК
# ============================================================
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на инлайн-кнопки"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    logger.info(f"🔘 Нажата кнопка: {data}")
    
    if data == "open_app":
        await query.edit_message_text(
            "🌸 *Beauty Connect*\n\n"
            "Нажмите кнопку ниже, чтобы открыть приложение:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "🌸 Открыть приложение",
                    web_app=WebAppInfo(url=MAIN_APP_URL)
                )
            ]])
        )

# ============================================================
#  ЗАПУСК БОТА
# ============================================================
def main():
    """Запуск бота"""
    try:
        logger.info("🚀 Запуск бота Beauty Connect...")
        
        # Создаём приложение
        app = Application.builder().token(TOKEN).build()
        
        # Регистрируем обработчики
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CallbackQueryHandler(button_callback))
        
        # Запускаем бота
        logger.info("✅ Бот запущен и готов к работе!")
        app.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске бота: {e}")

if __name__ == "__main__":
    main()
