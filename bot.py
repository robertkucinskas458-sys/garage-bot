import logging
import sqlite3
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("Токен не найден! Добавьте TOKEN в переменные окружения")

GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "0"))
if GROUP_CHAT_ID == 0:
    raise ValueError("ID группы не найден! Добавьте GROUP_CHAT_ID в переменные окружения")

admin_ids_str = os.getenv("ADMIN_IDS", "")
if not admin_ids_str:
    raise ValueError("Список админов не найден! Добавьте ADMIN_IDS в переменные окружения")
ADMIN_IDS = [int(id.strip()) for id in admin_ids_str.split(",")]

TOPIC_ID = int(os.getenv("TOPIC_ID", "0"))

CAR_NAME, CAR_PLATE = range(2)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

def init_db():
    conn = sqlite3.connect("garage.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS cars
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, plate TEXT,
                  is_taken INTEGER DEFAULT 0, taken_by INTEGER, taken_at TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, car_id INTEGER, user_id INTEGER,
                  action TEXT, condition TEXT, timestamp TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT)''')
    conn.commit()
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
    for n, p in cars:
        c.execute("INSERT OR IGNORE INTO cars (name, plate) VALUES (?, ?)", (n, p))
    conn.commit()
    conn.close()

def get_user_name(u): return f"@{u.username}" if u.username else (u.full_name or str(u.id))

def save_user_info(u):
    with sqlite3.connect("garage.db") as conn:
        conn.execute("INSERT OR REPLACE INTO users VALUES (?, ?, ?)", (u.id, u.username, u.full_name))

def log_action(cid, uid, act, cond=None):
    with sqlite3.connect("garage.db") as conn:
        conn.execute("INSERT INTO history (car_id, user_id, action, condition, timestamp) VALUES (?, ?, ?, ?, ?)",
                     (cid, uid, act, cond, datetime.now()))

def is_admin(uid): return uid in ADMIN_IDS

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    save_user_info(u)
    kb = [[InlineKeyboardButton("🚗 Взять машину", callback_data="take_car")],
          [InlineKeyboardButton("🔙 Вернуть машину", callback_data="return_car")]]
    if is_admin(u.id):
        kb.append([InlineKeyboardButton("📜 История", callback_data="history")])
        kb.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin_panel")])
    await update.message.reply_text("Добро пожаловать в гараж!", reply_markup=InlineKeyboardMarkup(kb))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    if d == "take_car":
        await show_free_cars(q)
    elif d == "return_car":
        await show_user_taken_cars(q)
    elif d == "history" and is_admin(q.from_user.id):
        await show_history(q)
    elif d == "admin_panel" and is_admin(q.from_user.id):
        await admin_panel(q)
    elif d.startswith("take_"):
        await take_car(q, context, int(d.split("_")[1]))
    elif d.startswith("return_"):
        await ask_car_condition(q, int(d.split("_")[1]))
    elif d.startswith("confirm_return_"):
        p = d.split("_")
        await return_car(q, context, int(p[2]), p[3])
    elif d == "admin_add_car" and is_admin(q.from_user.id):
        await q.edit_message_text("Введите название машины:")
        return CAR_NAME
    elif d == "admin_remove_car" and is_admin(q.from_user.id):
        await show_cars_for_remove(q)
    elif d.startswith("remove_"):
        await remove_car(q, int(d.split("_")[1]))
    elif d == "admin_force_return" and is_admin(q.from_user.id):
        await show_taken_cars_for_admin(q)
    elif d.startswith("force_return_"):
        await force_return_car(q, context, int(d.split("_")[2]))
    elif d == "back_to_menu":
        await back_to_menu(q)

async def show_free_cars(q):
    with sqlite3.connect("garage.db") as conn:
        cars = conn.execute("SELECT id, name, plate FROM cars WHERE is_taken = 0").fetchall()
    if not cars:
        await q.edit_message_text("😕 Все машины заняты.")
        return
    kb = [[InlineKeyboardButton(f"{n}{' ('+p+')' if p else ''}", callback_data=f"take_{i}")] for i, n, p in cars]
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")])
    await q.edit_message_text("Выберите машину:", reply_markup=InlineKeyboardMarkup(kb))

async def take_car(q, ctx, car_id):
    u = q.from_user
    with sqlite3.connect("garage.db") as conn:
        c = conn.execute("SELECT name, plate, is_taken FROM cars WHERE id = ?", (car_id,)).fetchone()
        if not c or c[2]:
            await q.edit_message_text("❌ Машина уже занята.")
            return
        conn.execute("UPDATE cars SET is_taken = 1, taken_by = ?, taken_at = ? WHERE id = ?",
                     (u.id, datetime.now(), car_id))
    log_action(car_id, u.id, "take")
    msg = f"🚗 {get_user_name(u)} взял машину {c[0]}{' ('+c[1]+')' if c[1] else ''}"
    if TOPIC_ID != 0:
        await ctx.bot.send_message(chat_id=GROUP_CHAT_ID, message_thread_id=TOPIC_ID, text=msg)
    else:
        await ctx.bot.send_message(chat_id=GROUP_CHAT_ID, text=msg)
    await q.edit_message_text(f"✅ Вы взяли машину {c[0]}{' ('+c[1]+')' if c[1] else ''}")

async def show_user_taken_cars(q):
    u = q.from_user
    with sqlite3.connect("garage.db") as conn:
        if is_admin(u.id):
            cars = conn.execute("SELECT id, name, plate FROM cars WHERE is_taken = 1").fetchall()
        else:
            cars = conn.execute("SELECT id, name, plate FROM cars WHERE is_taken = 1 AND taken_by = ?", (u.id,)).fetchall()
    if not cars:
        await q.edit_message_text("У вас нет взятых машин." if not is_admin(u.id) else "Нет занятых машин.")
        return
    kb = [[InlineKeyboardButton(f"{n}{' ('+p+')' if p else ''}", callback_data=f"return_{i}")] for i, n, p in cars]
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")])
    await q.edit_message_text("Выберите машину для возврата:", reply_markup=InlineKeyboardMarkup(kb))

async def ask_car_condition(q, car_id):
    kb = [[InlineKeyboardButton("✅ Целая", callback_data=f"confirm_return_{car_id}_yes"),
           InlineKeyboardButton("❌ Повреждена", callback_data=f"confirm_return_{car_id}_no")],
          [InlineKeyboardButton("🔙 Отмена", callback_data="return_car")]]
    await q.edit_message_text("Машина целая?", reply_markup=InlineKeyboardMarkup(kb))

async def return_car(q, ctx, car_id, cond):
    u = q.from_user
    cond_text = "целая" if cond == "yes" else "с повреждениями"
    with sqlite3.connect("garage.db") as conn:
        c = conn.execute("SELECT name, plate, taken_by FROM cars WHERE id = ? AND is_taken = 1", (car_id,)).fetchone()
        if not c:
            await q.edit_message_text("❌ Машина не занята.")
            return
        if not is_admin(u.id) and c[2] != u.id:
            await q.edit_message_text("⛔ Это не ваша машина.")
            return
        conn.execute("UPDATE cars SET is_taken = 0, taken_by = NULL, taken_at = NULL WHERE id = ?", (car_id,))
    log_action(car_id, u.id, "return", cond)
    msg = f"🔙 {get_user_name(u)} вернул машину {c[0]}{' ('+c[1]+')' if c[1] else ''} ({cond_text})"
    if TOPIC_ID != 0:
        await ctx.bot.send_message(chat_id=GROUP_CHAT_ID, message_thread_id=TOPIC_ID, text=msg)
    else:
        await ctx.bot.send_message(chat_id=GROUP_CHAT_ID, text=msg)
    await q.edit_message_text(f"✅ Вы вернули машину {c[0]}{' ('+c[1]+')' if c[1] else ''} ({cond_text})")

async def show_history(q):
    with sqlite3.connect("garage.db") as conn:
        r = conn.execute("""
            SELECT h.timestamp, u.username, u.full_name, c.name, c.plate, h.action, h.condition
            FROM history h JOIN cars c ON h.car_id = c.id LEFT JOIN users u ON h.user_id = u.user_id
            ORDER BY h.timestamp DESC LIMIT 20
        """).fetchall()
    if not r:
        await q.edit_message_text("История пуста.")
        return
    text = "📜 Последние действия:\n\n"
    for ts, un, fn, cn, pl, act, cond in r:
        ud = f"@{un}" if un else (fn or "Неизвестный")
        if act == "take": at = "взял"
        elif act == "return": at = f"вернул{' (целая)' if cond=='yes' else ' (повреждена)'}"
        elif act == "force_return": at = "принудительно вернул"
        else: at = act
        text += f"{datetime.fromisoformat(ts).strftime('%d.%m %H:%M')} — {ud} {at} {cn}{' ('+pl+')' if pl else ''}\n"
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]))

async def admin_panel(q):
    kb = [[InlineKeyboardButton("➕ Добавить машину", callback_data="admin_add_car")],
          [InlineKeyboardButton("❌ Удалить машину", callback_data="admin_remove_car")],
          [InlineKeyboardButton("⚠️ Принудительный возврат", callback_data="admin_force_return")],
          [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]
    await q.edit_message_text("⚙️ Админ-панель", reply_markup=InlineKeyboardMarkup(kb))

async def add_car_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_car_name'] = update.message.text
    await update.message.reply_text("Введите госномер (или '-' если нет):")
    return CAR_PLATE

async def add_car_plate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    plate = None if update.message.text == "-" else update.message.text
    with sqlite3.connect("garage.db") as conn:
        conn.execute("INSERT INTO cars (name, plate) VALUES (?, ?)", (context.user_data['new_car_name'], plate))
    await update.message.reply_text(f"✅ Машина {context.user_data['new_car_name']} добавлена.")
    await start(update, context)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.")
    await start(update, context)
    return ConversationHandler.END

async def show_cars_for_remove(q):
    with sqlite3.connect("garage.db") as conn:
        cars = conn.execute("SELECT id, name, plate, is_taken FROM cars ORDER BY name").fetchall()
    if not cars:
        await q.edit_message_text("Список пуст.")
        return
    kb = [[InlineKeyboardButton(f"{'🔴' if t else '🟢'} {n}{' ('+p+')' if p else ''}", callback_data=f"remove_{i}")] for i, n, p, t in cars]
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")])
    await q.edit_message_text("Выберите машину для удаления:", reply_markup=InlineKeyboardMarkup(kb))

async def remove_car(q, car_id):
    with sqlite3.connect("garage.db") as conn:
        n = conn.execute("SELECT name FROM cars WHERE id = ?", (car_id,)).fetchone()
        if not n:
            await q.edit_message_text("❌ Не найдено.")
            return
        conn.execute("DELETE FROM cars WHERE id = ?", (car_id,))
        conn.execute("DELETE FROM history WHERE car_id = ?", (car_id,))
    await q.edit_message_text(f"✅ Машина {n[0]} удалена.")

async def show_taken_cars_for_admin(q):
    with sqlite3.connect("garage.db") as conn:
        cars = conn.execute("""
            SELECT c.id, c.name, c.plate, u.username, u.full_name
            FROM cars c LEFT JOIN users u ON c.taken_by = u.user_id
            WHERE c.is_taken = 1
        """).fetchall()
    if not cars:
        await q.edit_message_text("Нет занятых машин.")
        return
    kb = [[InlineKeyboardButton(f"{n}{' ('+p+')' if p else ''} (взял {('@'+un) if un else (fn or 'Неизвестный')})",
                                 callback_data=f"force_return_{i}")] for i, n, p, un, fn in cars]
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")])
    await q.edit_message_text("Выберите машину для принудительного возврата:", reply_markup=InlineKeyboardMarkup(kb))

async def force_return_car(q, ctx, car_id):
    a = q.from_user
    with sqlite3.connect("garage.db") as conn:
        c = conn.execute("SELECT name, plate, taken_by FROM cars WHERE id = ? AND is_taken = 1", (car_id,)).fetchone()
        if not c:
            await q.edit_message_text("❌ Машина не занята.")
            return
        conn.execute("UPDATE cars SET is_taken = 0, taken_by = NULL, taken_at = NULL WHERE id = ?", (car_id,))
    log_action(car_id, a.id, "force_return")
    msg = f"🔙 {get_user_name(a)} принудительно вернул машину {c[0]}{' ('+c[1]+')' if c[1] else ''}"
    if TOPIC_ID != 0:
        await ctx.bot.send_message(chat_id=GROUP_CHAT_ID, message_thread_id=TOPIC_ID, text=msg)
    else:
        await ctx.bot.send_message(chat_id=GROUP_CHAT_ID, text=msg)
    await q.edit_message_text(f"✅ Машина {c[0]}{' ('+c[1]+')' if c[1] else ''} возвращена.")

async def back_to_menu(q):
    u = q.from_user
    kb = [[InlineKeyboardButton("🚗 Взять машину", callback_data="take_car")],
          [InlineKeyboardButton("🔙 Вернуть машину", callback_data="return_car")]]
    if is_admin(u.id):
        kb.append([InlineKeyboardButton("📜 История", callback_data="history")])
        kb.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin_panel")])
    await q.edit_message_text("Добро пожаловать в гараж!", reply_markup=InlineKeyboardMarkup(kb))

app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(ConversationHandler(
    entry_points=[CallbackQueryHandler(button_handler, pattern="^admin_add_car$")],
    states={CAR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_car_name)],
            CAR_PLATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_car_plate)]},
    fallbacks=[CommandHandler("cancel", cancel)]
))

if __name__ == "__main__":
    init_db()
    app.run_polling()
