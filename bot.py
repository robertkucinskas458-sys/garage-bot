import logging
import sqlite3
import os
import asyncio
import random
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

# ==== ДАННЫЕ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ====
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("❌ TOKEN не найден! Добавь в переменные окружения")

ADMIN_IDS_STR = os.getenv("ADMIN_IDS")
if not ADMIN_IDS_STR:
    raise ValueError("❌ ADMIN_IDS не найден! Добавь в переменные окружения")
ADMIN_IDS = [int(id.strip()) for id in ADMIN_IDS_STR.split(",")]

# ==== ТВОИ ПОСТОЯННЫЕ ДАННЫЕ ====
GROUP_CHAT_ID = -1002331168240
TOPIC_ID = 318450

CAR_NAME, CAR_PLATE = range(2)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

INSULTS = [
    "⚠️ **{} сюда писать нельзя, долбаеб!**",
    "⚠️ **{} ты че, самый умный? По теме пиши!**",
    "⚠️ **{} еще одно такое сообщение — пизды получишь!**",
    "⚠️ **{} для тебя специально тему создали, мудак!**",
    "⚠️ **{} руки из жопы? Сюда нельзя писать!**",
    "⚠️ **{} ты вообще читать умеешь? Только по теме!**",
    "⚠️ **{} за такие сообщения по ебалу дают!**",
    "⚠️ **{} иди нахуй отсюда со своим флудом!**",
    "⚠️ **{} тему видишь? Туда пиши, дебил!**",
    "⚠️ **{} последнее предупреждение, урод!**",
]

async def delete_after_delay(context, chat_id, message_id, delay=3):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except:
        pass

async def safe_delete(context, chat_id, message_id):
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except:
        pass

def get_user_mention(user):
    if user.username:
        return f"@{user.username}"
    return f"[{user.full_name}](tg://user?id={user.id})"

def get_user_name(user):
    if user.username:
        return f"@{user.username}"
    return user.full_name or str(user.id)

async def insult_user(context, update):
    user = update.effective_user
    mention = get_user_mention(user)
    await safe_delete(context, update.effective_chat.id, update.message.message_id)
    insult = random.choice(INSULTS).format(mention)
    msg = await update.effective_chat.send_message(insult, parse_mode="Markdown")
    asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 5))

def init_db():
    conn = sqlite3.connect("garage.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS cars
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  plate TEXT,
                  is_taken INTEGER DEFAULT 0,
                  taken_by INTEGER,
                  taken_at TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  car_id INTEGER,
                  user_id INTEGER,
                  action TEXT,
                  condition TEXT,
                  timestamp TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  username TEXT,
                  full_name TEXT)''')
    
    cars = [
        ("Porsche 911 Carrera (993)", "M303YP 78"),
        ("BMW M3 (E46) MostWanted", "M808KA 78"),
        ("BA3-1111 «Ока»", "С069АС77"),
        ("BMW 750i (E38)", "С404ОС77"),
        ("Ford F-150 Shelby 2020", ""),
        ("Ferrari Purosangue", "Е227РМ78"),
        ("BA3-21099", "М878ММ63"),
        ("ЗАЗ-968 «Запорожец»", "A404YA 77"),
        ("Mercedes-Benz G63 AMG (W464)", "M056YP 63"),
        ("Toyota Chaser Tourer V (JZX100)", "M717TC 78"),
        ("Mersedes-Benz V300d (W447)", "О438ET 78"),
        ("Bugatti Chiron Sport", ""),
        ("BMW X5 M (F95)", "M616TC 78"),
        ("Ford F-150 Shelby 2020", "M288YP 77"),
        ("BMW 850CSi", ""),
        ("Audi S4 (B8)", "М111ТС78"),
    ]
    for name, plate in cars:
        c.execute("INSERT OR IGNORE INTO cars (name, plate) VALUES (?, ?)", (name, plate))
    conn.commit()
    conn.close()

def save_user_info(user):
    try:
        with sqlite3.connect("garage.db") as conn:
            conn.execute(
                "INSERT OR REPLACE INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
                (user.id, user.username, user.full_name)
            )
    except:
        pass

def log_action(car_id, user_id, action, condition=None):
    try:
        with sqlite3.connect("garage.db") as conn:
            conn.execute(
                "INSERT INTO history (car_id, user_id, action, condition, timestamp) VALUES (?, ?, ?, ?, ?)",
                (car_id, user_id, action, condition, datetime.now())
            )
    except:
        pass

def is_admin(user_id):
    return user_id in ADMIN_IDS

# ========== МОДЕРАТОР ТОПИКА ==========
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Только наша группа и наш топик
    if update.effective_chat.id == GROUP_CHAT_ID and update.message.message_thread_id == TOPIC_ID:
        if update.message.text and update.message.text.startswith("/cars"):
            return
        await insult_user(context, update)
        return

# ========== ОСНОВНЫЕ ОБРАБОТЧИКИ ==========
async def cars_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_type = update.effective_chat.type
    message = update.message
    chat_id = update.effective_chat.id

    # Если это группа
    if chat_type in ["group", "supergroup"]:
        # Работаем только в нашем топике
        if chat_id != GROUP_CHAT_ID or message.message_thread_id != TOPIC_ID:
            # Игнорируем
            return

    user = update.effective_user
    save_user_info(user)

    keyboard = [
        [InlineKeyboardButton("🚗 Взять машину", callback_data="take_car")],
        [InlineKeyboardButton("🔙 Вернуть машину", callback_data="return_car")],
    ]
    if chat_type == "private" and is_admin(user.id):
        keyboard.append([InlineKeyboardButton("📜 История", callback_data="history")])
        keyboard.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin_panel")])

    msg = await message.chat.send_message(
        "🚘 **Гараж**\nВыбери действие:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 5))

# ... (остальные функции остаются без изменений, я их сократил для краткости, но в реальном коде они должны быть все)
# ... (добавь сюда все функции из предыдущего полного кода: button_handler, show_free_cars, take_car, show_user_taken_cars, ask_car_condition, return_car, show_history, admin_panel, add_car_name, add_car_plate, cancel, show_cars_for_remove, remove_car, show_taken_cars_for_admin, force_return_car, back_to_menu)

# ========== НАСТРОЙКА ==========
app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("cars", cars_command))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(ConversationHandler(
    entry_points=[CallbackQueryHandler(button_handler, pattern="^admin_add_car$")],
    states={
        CAR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_car_name)],
        CAR_PLATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_car_plate)],
    },
    fallbacks=[CommandHandler("cancel", cancel)]
))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

if __name__ == "__main__":
    init_db()
    print("🚀 Бот запущен...")
    app.run_polling()
