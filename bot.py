import logging
import sqlite3
from datetime import datetime
from functools import wraps

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# ========== ТВОИ ДАННЫЕ ==========
TOKEN = "8565799138:AAG82YRV9MTSmwAI-J6BY1m5kpGXDsuVbAM"
GROUP_CHAT_ID = -1002331168240
ADMIN_IDS = [789615854]

CAR_NAME, CAR_PLATE = range(2)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== БАЗА ДАННЫХ ==========
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
    conn.commit()

    initial_cars = [
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
    for name, plate in initial_cars:
        c.execute("INSERT OR IGNORE INTO cars (name, plate) VALUES (?, ?)", (name, plate))
    conn.commit()
    conn.close()

def get_user_name(user):
    return f"@{user.username}" if user.username else (user.full_name or str(user.id))

def save_user_info(user):
    conn = sqlite3.connect("garage.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
              (user.id, user.username, user.full_name))
    conn.commit()
    conn.close()

def log_action(car_id, user_id, action, condition=None):
    conn = sqlite3.connect("garage.db")
    c = conn.cursor()
    c.execute("INSERT INTO history (car_id, user_id, action, condition, timestamp) VALUES (?, ?, ?, ?, ?)",
              (car_id, user_id, action, condition, datetime.now()))
    conn.commit()
    conn.close()

def is_admin(user_id):
    return user_id in ADMIN_IDS

def admin_only(func):
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        if not is_admin(update.effective_user.id):
            await update.effective_message.reply_text("⛔ Только для администраторов.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# ========== СТАРТ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user_info(user)
    keyboard = [
        [InlineKeyboardButton("🚗 Взять машину", callback_data="take_car")],
        [InlineKeyboardButton("🔙 Вернуть машину", callback_data="return_car")],
    ]
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("📜 История", callback_data="history")])
        keyboard.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin_panel")])
    await update.message.reply_text("Добро пожаловать в гараж!", reply_markup=InlineKeyboardMarkup(keyboard))

# ========== ОБРАБОТКА КНОПОК ==========
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    data = query.data

    if data == "take_car":
        await show_free_cars(query)
    elif data == "return_car":
        await show_user_taken_cars(query)
    elif data == "history" and is_admin(user.id):
        await show_history(query)
    elif data == "admin_panel" and is_admin(user.id):
        await admin_panel(query)
    elif data.startswith("take_"):
        car_id = int(data.split("_")[1])
        await take_car(query, context, car_id)
    elif data.startswith("return_"):
        car_id = int(data.split("_")[1])
        await ask_car_condition(query, car_id)
    elif data.startswith("confirm_return_"):
        parts = data.split("_")
        car_id = int(parts[2])
        condition = parts[3]
        await return_car(query, context, car_id, condition)
    elif data == "admin_add_car" and is_admin(user.id):
        await query.edit_message_text("Введите название машины:")
        return CAR_NAME
    elif data == "admin_remove_car" and is_admin(user.id):
        await show_cars_for_remove(query)
    elif data.startswith("remove_"):
        car_id = int(data.split("_")[1])
        await remove_car(query, car_id)
    elif data == "admin_force_return" and is_admin(user.id):
        await show_taken_cars_for_admin(query)
    elif data.startswith("force_return_"):
        car_id = int(data.split("_")[2])
        await force_return_car(query, context, car_id)
    elif data == "back_to_menu":
        await back_to_menu(query)

# ---------- ВЗЯТЬ МАШИНУ ----------
async def show_free_cars(query):
    conn = sqlite3.connect("garage.db")
    c = conn.cursor()
    c.execute("SELECT id, name, plate FROM cars WHERE is_taken = 0")
    cars = c.fetchall()
    conn.close()
    if not cars:
        await query.edit_message_text("😕 Все машины заняты.")
        return
    keyboard = []
    for car_id, name, plate in cars:
        plate_text = f" ({plate})" if plate else ""
        keyboard.append([InlineKeyboardButton(f"{name}{plate_text}", callback_data=f"take_{car_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")])
    await query.edit_message_text("Выберите машину:", reply_markup=InlineKeyboardMarkup(keyboard))

async def take_car(query, context, car_id):
    user = query.from_user
    conn = sqlite3.connect("garage.db")
    c = conn.cursor()
    c.execute("SELECT name, plate, is_taken FROM cars WHERE id = ?", (car_id,))
    car = c.fetchone()
    if not car or car[2] == 1:
        await query.edit_message_text("❌ Машина уже занята.")
        conn.close()
        return
    c.execute("UPDATE cars SET is_taken = 1, taken_by = ?, taken_at = ? WHERE id = ?",
              (user.id, datetime.now(), car_id))
    conn.commit()
    conn.close()
    log_action(car_id, user.id, "take")
    user_name = get_user_name(user)
    car_name = car[0]
    plate = car[1] if car[1] else ""
    plate_text = f" ({plate})" if plate else ""
    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=f"🚗 {user_name} взял машину {car_name}{plate_text}"
    )
    await query.edit_message_text(f"✅ Вы взяли машину {car_name}{plate_text}")

# ---------- ВЕРНУТЬ МАШИНУ ----------
async def show_user_taken_cars(query):
    user = query.from_user
    conn = sqlite3.connect("garage.db")
    c = conn.cursor()
    if is_admin(user.id):
        c.execute("SELECT id, name, plate FROM cars WHERE is_taken = 1")
    else:
        c.execute("SELECT id, name, plate FROM cars WHERE is_taken = 1 AND taken_by = ?", (user.id,))
    cars = c.fetchall()
    conn.close()
    if not cars:
        await query.edit_message_text("У вас нет взятых машин." if not is_admin(user.id) else "Нет занятых машин.")
        return
    keyboard = []
    for car_id, name, plate in cars:
        plate_text = f" ({plate})" if plate else ""
        keyboard.append([InlineKeyboardButton(f"{name}{plate_text}", callback_data=f"return_{car_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")])
    await query.edit_message_text("Выберите машину для возврата:", reply_markup=InlineKeyboardMarkup(keyboard))

async def ask_car_condition(query, car_id):
    keyboard = [
        [InlineKeyboardButton("✅ Целая", callback_data=f"confirm_return_{car_id}_yes"),
         InlineKeyboardButton("❌ Повреждена", callback_data=f"confirm_return_{car_id}_no")],
        [InlineKeyboardButton("🔙 Отмена", callback_data="return_car")]
    ]
    await query.edit_message_text("Машина целая?", reply_markup=InlineKeyboardMarkup(keyboard))

async def return_car(query, context, car_id, condition):
    user = query.from_user
    condition_text = "целая" if condition == "yes" else "с повреждениями"
    conn = sqlite3.connect("garage.db")
    c = conn.cursor()
    c.execute("SELECT name, plate, taken_by FROM cars WHERE id = ? AND is_taken = 1", (car_id,))
    car = c.fetchone()
    if not car:
        await query.edit_message_text("❌ Машина не занята.")
        conn.close()
        return
    if not is_admin(user.id) and car[2] != user.id:
        await query.edit_message_text("⛔ Это не ваша машина.")
        conn.close()
        return
    c.execute("UPDATE cars SET is_taken = 0, taken_by = NULL, taken_at = NULL WHERE id = ?", (car_id,))
    conn.commit()
    conn.close()
    log_action(car_id, user.id, "return", condition)
    user_name = get_user_name(user)
    car_name = car[0]
    plate = car[1] if car[1] else ""
    plate_text = f" ({plate})" if plate else ""
    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=f"🔙 {user_name} вернул машину {car_name}{plate_text} ({condition_text})"
    )
    await query.edit_message_text(f"✅ Вы вернули машину {car_name}{plate_text} ({condition_text})")

# ---------- ИСТОРИЯ ----------
async def show_history(query):
    conn = sqlite3.connect("garage.db")
    c = conn.cursor()
    c.execute("""SELECT h.timestamp, u.username, u.full_name, c.name, c.plate, h.action, h.condition
                 FROM history h
                 JOIN cars c ON h.car_id = c.id
                 LEFT JOIN users u ON h.user_id = u.user_id
                 ORDER BY h.timestamp DESC LIMIT 20""")
    rows = c.fetchall()
    conn.close()
    if not rows:
        await query.edit_message_text("История пуста.")
        return
    text = "📜 Последние действия:\n\n"
    for ts, username, full_name, car_name, plate, action, condition in rows:
        user_disp = f"@{username}" if username else (full_name or "Неизвестный")
        if action == "take":
            action_text = "взял"
        elif action == "return":
            cond = " (целая)" if condition == "yes" else " (повреждена)"
            action_text = f"вернул{cond}"
        elif action == "force_return":
            action_text = "принудительно вернул"
        else:
            action_text = action
        plate_text = f" ({plate})" if plate else ""
        time_str = datetime.fromisoformat(ts).strftime("%d.%m %H:%M")
        text += f"{time_str} — {user_disp} {action_text} {car_name}{plate_text}\n"
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# ---------- АДМИН-ПАНЕЛЬ ----------
async def admin_panel(query):
    keyboard = [
        [InlineKeyboardButton("➕ Добавить машину", callback_data="admin_add_car")],
        [InlineKeyboardButton("❌ Удалить машину", callback_data="admin_remove_car")],
        [InlineKeyboardButton("⚠️ Принудительный возврат", callback_data="admin_force_return")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")],
    ]
    await query.edit_message_text("⚙️ Админ-панель", reply_markup=InlineKeyboardMarkup(keyboard))

# ---------- ДОБАВЛЕНИЕ МАШИНЫ ----------
async def add_car_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_car_name'] = update.message.text
    await update.message.reply_text("Введите госномер (или '-' если нет):")
    return CAR_PLATE

async def add_car_plate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    plate = update.message.text
    if plate == "-":
        plate = ""
    name = context.user_data['new_car_name']
    conn = sqlite3.connect("garage.db")
    c = conn.cursor()
    c.execute("INSERT INTO cars (name, plate) VALUES (?, ?)", (name, plate))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ Машина {name} добавлена.")
    await start(update, context)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.")
    await start(update, context)
    return ConversationHandler.END

# ---------- УДАЛЕНИЕ МАШИНЫ ----------
async def show_cars_for_remove(query):
    conn = sqlite3.connect("garage.db")
    c = conn.cursor()
    c.execute("SELECT id, name, plate, is_taken FROM cars ORDER BY name")
    cars = c.fetchall()
    conn.close()
    if not cars:
        await query.edit_message_text("Список пуст.")
        return
    keyboard = []
    for car_id, name, plate, taken in cars:
        status = "🔴" if taken else "🟢"
        plate_text = f" ({plate})" if plate else ""
        keyboard.append([InlineKeyboardButton(f"{status} {name}{plate_text}", callback_data=f"remove_{car_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")])
    await query.edit_message_text("Выберите машину для удаления:", reply_markup=InlineKeyboardMarkup(keyboard))

async def remove_car(query, car_id):
    conn = sqlite3.connect("garage.db")
    c = conn.cursor()
    c.execute("SELECT name FROM cars WHERE id = ?", (car_id,))
    car = c.fetchone()
    if not car:
        await query.edit_message_text("❌ Не найдено.")
        conn.close()
        return
    c.execute("DELETE FROM cars WHERE id = ?", (car_id,))
    c.execute("DELETE FROM history WHERE car_id = ?", (car_id,))
    conn.commit()
    conn.close()
    await query.edit_message_text(f"✅ Машина {car[0]} удалена.")

# ---------- ПРИНУДИТЕЛЬНЫЙ ВОЗВРАТ ----------
async def show_taken_cars_for_admin(query):
    conn = sqlite3.connect("garage.db")
    c = conn.cursor()
    c.execute("""SELECT c.id, c.name, c.plate, u.username, u.full_name
                 FROM cars c
                 LEFT JOIN users u ON c.taken_by = u.user_id
                 WHERE c.is_taken = 1""")
    cars = c.fetchall()
    conn.close()
    if not cars:
        await query.edit_message_text("Нет занятых машин.")
        return
    keyboard = []
    for car_id, name, plate, username, full_name in cars:
        user_disp = f"@{username}" if username else (full_name or "Неизвестный")
        plate_text = f" ({plate})" if plate else ""
        keyboard.append([InlineKeyboardButton(f"{name}{plate_text} (взял {user_disp})",
                                              callback_data=f"force_return_{car_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")])
    await query.edit_message_text("Выберите машину для принудительного возврата:", reply_markup=InlineKeyboardMarkup(keyboard))

async def force_return_car(query, context, car_id):
    admin = query.from_user
    conn = sqlite3.connect("garage.db")
    c = conn.cursor()
    c.execute("SELECT name, plate, taken_by FROM cars WHERE id = ? AND is_taken = 1", (car_id,))
    car = c.fetchone()
    if not car:
        await query.edit_message_text("❌ Машина не занята.")
        conn.close()
        return
    c.execute("UPDATE cars SET is_taken = 0, taken_by = NULL, taken_at = NULL WHERE id = ?", (car_id,))
    conn.commit()
    conn.close()
    log_action(car_id, admin.id, "force_return")
    admin_name = get_user_name(admin)
    car_name = car[0]
    plate = car[1] if car[1] else ""
    plate_text = f" ({plate})" if plate else ""
    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=f"🔙 {admin_name} принудительно вернул машину {car_name}{plate_text}"
    )
    await query.edit_message_text(f"✅ Машина {car_name}{plate_text} возвращена.")

# ---------- НАЗАД В МЕНЮ ----------
async def back_to_menu(query):
    user = query.from_user
    keyboard = [
        [InlineKeyboardButton("🚗 Взять машину", callback_data="take_car")],
        [InlineKeyboardButton("🔙 Вернуть машину", callback_data="return_car")],
    ]
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("📜 История", callback_data="history")])
        keyboard.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin_panel")])
    await query.edit_message_text("Добро пожаловать в гараж!", reply_markup=InlineKeyboardMarkup(keyboard))

# ========== НАСТРОЙКА ПРИЛОЖЕНИЯ ==========
application = Application.builder().token(TOKEN).build()

add_car_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(button_handler, pattern="^admin_add_car$")],
    states={
        CAR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_car_name)],
        CAR_PLATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_car_plate)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(button_handler))
application.add_handler(add_car_conv)

# ========== ЗАПУСК (ИЗМЕНЕНО: вместо вебхука используем polling) ==========
def main():
    init_db()
    application.run_polling()
    print("Бот запущен на сервере...")

if __name__ == "__main__":
    main()
