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

# ========== ДАННЫЕ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ==========
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("❌ Ошибка: TOKEN не найден! Добавь в переменные окружения")

GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID")
if not GROUP_CHAT_ID:
    raise ValueError("❌ Ошибка: GROUP_CHAT_ID не найден!")
GROUP_CHAT_ID = int(GROUP_CHAT_ID)

admin_ids_str = os.getenv("ADMIN_IDS", "")
if not admin_ids_str:
    raise ValueError("❌ Ошибка: ADMIN_IDS не найден!")
ADMIN_IDS = [int(id.strip()) for id in admin_ids_str.split(",")]

TOPIC_ID = os.getenv("TOPIC_ID")
if not TOPIC_ID:
    raise ValueError("❌ Ошибка: TOPIC_ID не найден!")
TOPIC_ID = int(TOPIC_ID)

CAR_NAME, CAR_PLATE = range(2)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ========== РУГАТЕЛЬСТВА (10 вариантов) ==========
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

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
async def delete_after_delay(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int = 3):
    """Удалить сообщение через указанное количество секунд"""
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logging.error(f"Не удалось удалить сообщение {message_id}: {e}")

async def safe_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    """Безопасное удаление сообщения"""
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logging.error(f"Ошибка удаления: {e}")

def get_user_mention(user):
    """Получить упоминание пользователя"""
    if user.username:
        return f"@{user.username}"
    else:
        return f"[{user.full_name}](tg://user?id={user.id})"

def get_user_name(user):
    """Получить имя пользователя для отображения"""
    if user.username:
        return f"@{user.username}"
    else:
        return user.full_name or str(user.id)

async def insult_user(context: ContextTypes.DEFAULT_TYPE, update: Update):
    """Поругать пользователя и удалить его сообщение"""
    user = update.effective_user
    mention = get_user_mention(user)
    
    await safe_delete(context, update.effective_chat.id, update.message.message_id)
    
    insult_template = random.choice(INSULTS)
    insult = insult_template.format(mention)
    
    msg = await update.effective_chat.send_message(
        insult,
        parse_mode="Markdown"
    )
    asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 5))

def init_db():
    """Инициализация базы данных"""
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
    except Exception as e:
        logging.error(f"Ошибка сохранения пользователя: {e}")

def log_action(car_id, user_id, action, condition=None):
    try:
        with sqlite3.connect("garage.db") as conn:
            conn.execute(
                "INSERT INTO history (car_id, user_id, action, condition, timestamp) VALUES (?, ?, ?, ?, ?)",
                (car_id, user_id, action, condition, datetime.now())
            )
    except Exception as e:
        logging.error(f"Ошибка логирования: {e}")

def is_admin(user_id):
    return user_id in ADMIN_IDS

# ========== МОДЕРАТОР ЧАТА ==========
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка всех сообщений в группе"""
    # Если это не группа — пропускаем
    if update.effective_chat.type not in ["group", "supergroup"]:
        return
    
    # ЕСЛИ ЭТО НАШ ТОПИК — НЕ ТРОГАЕМ (можно писать всё что угодно)
    if update.message.message_thread_id == TOPIC_ID:
        return
    
    # Если это команда /cars в основном чате — удаляем и не запускаем
    if update.message.text and update.message.text.startswith("/cars"):
        await safe_delete(context, update.effective_chat.id, update.message.message_id)
        return
    
    # ВСЁ ОСТАЛЬНОЕ В ОСНОВНОМ ЧАТЕ — УДАЛЯЕМ И РУГАЕМСЯ
    await insult_user(context, update)

# ========== ОСНОВНЫЕ ОБРАБОТЧИКИ ==========
async def cars_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /cars - работает только в ЛС и в топике, в основном чате игнорится"""
    chat_type = update.effective_chat.type
    
    # Если это группа и НЕ наш топик — удаляем и игнорим
    if chat_type in ["group", "supergroup"] and update.message.message_thread_id != TOPIC_ID:
        await safe_delete(context, update.effective_chat.id, update.message.message_id)
        return
    
    # Удаляем сообщение с командой
    await safe_delete(context, update.effective_chat.id, update.message.message_id)
    
    user = update.effective_user
    save_user_info(user)
    
    keyboard = [
        [InlineKeyboardButton("🚗 Взять машину", callback_data="take_car")],
        [InlineKeyboardButton("🔙 Вернуть машину", callback_data="return_car")],
    ]
    
    if chat_type == "private" and is_admin(user.id):
        keyboard.append([InlineKeyboardButton("📜 История", callback_data="history")])
        keyboard.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin_panel")])
    
    msg = await update.effective_chat.send_message(
        "🚘 **Гараж**\nВыбери действие:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    
    asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 5))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data
    chat_type = query.message.chat.type

    await safe_delete(context, query.message.chat_id, query.message.message_id)

    if data == "take_car":
        await show_free_cars(context, user)
    elif data == "return_car":
        await show_user_taken_cars(context, user)
    elif data == "history" and is_admin(user.id):
        if chat_type == "private":
            await show_history(context, user)
        else:
            msg = await context.bot.send_message(user.id, "📜 История доступна только в личных сообщениях")
            asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))
    elif data == "admin_panel" and is_admin(user.id):
        if chat_type == "private":
            await admin_panel(context, user)
        else:
            msg = await context.bot.send_message(user.id, "⚙️ Админ-панель доступна только в личных сообщениях")
            asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))
    elif data.startswith("take_"):
        await take_car(context, user, int(data.split("_")[1]))
    elif data.startswith("return_"):
        await ask_car_condition(context, user, int(data.split("_")[1]))
    elif data.startswith("confirm_return_"):
        parts = data.split("_")
        await return_car(context, user, int(parts[2]), parts[3])
    elif data == "admin_add_car" and is_admin(user.id):
        msg = await context.bot.send_message(user.id, "✏️ Введи название машины:")
        asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 5))
        return CAR_NAME
    elif data == "admin_remove_car" and is_admin(user.id):
        await show_cars_for_remove(context, user)
    elif data.startswith("remove_"):
        await remove_car(context, user, int(data.split("_")[1]))
    elif data == "admin_force_return" and is_admin(user.id):
        await show_taken_cars_for_admin(context, user)
    elif data.startswith("force_return_"):
        await force_return_car(context, user, int(data.split("_")[2]))
    elif data == "back_to_menu":
        await back_to_menu(context, user, chat_type)

async def show_free_cars(context: ContextTypes.DEFAULT_TYPE, user):
    try:
        with sqlite3.connect("garage.db") as conn:
            cars = conn.execute(
                "SELECT id, name, plate FROM cars WHERE is_taken = 0"
            ).fetchall()
        
        if not cars:
            msg = await context.bot.send_message(user.id, "😕 **Все машины заняты**")
            asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))
            return
        
        keyboard = []
        for car_id, name, plate in cars:
            plate_text = f" ({plate})" if plate else ""
            keyboard.append([InlineKeyboardButton(
                f"{name}{plate_text}",
                callback_data=f"take_{car_id}"
            )])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")])
        
        msg = await context.bot.send_message(
            user.id,
            "🚗 **Доступные машины:**",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 10))
    except Exception as e:
        logging.error(f"Ошибка показа машин: {e}")
        msg = await context.bot.send_message(user.id, "❌ Ошибка загрузки списка")
        asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))

async def take_car(context: ContextTypes.DEFAULT_TYPE, user, car_id):
    try:
        with sqlite3.connect("garage.db") as conn:
            car = conn.execute(
                "SELECT name, plate, is_taken FROM cars WHERE id = ?",
                (car_id,)
            ).fetchone()
            
            if not car or car[2] == 1:
                msg = await context.bot.send_message(user.id, "❌ **Машина уже занята**")
                asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))
                return
            
            conn.execute(
                "UPDATE cars SET is_taken = 1, taken_by = ?, taken_at = ? WHERE id = ?",
                (user.id, datetime.now(), car_id)
            )
        
        log_action(car_id, user.id, "take")
        
        car_name = car[0]
        plate_text = f" ({car[1]})" if car[1] else ""
        user_name = get_user_name(user)
        
        # Отправляем ТОЛЬКО в топик
        await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            message_thread_id=TOPIC_ID,
            text=f"🚗 {user_name} взял машину {car_name}{plate_text}"
        )
        
        msg = await context.bot.send_message(
            user.id,
            f"✅ **Ты взял:**\n{car_name}{plate_text}"
        )
        asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))
    except Exception as e:
        logging.error(f"Ошибка взятия машины: {e}")
        msg = await context.bot.send_message(user.id, "❌ Ошибка операции")
        asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))

async def show_user_taken_cars(context: ContextTypes.DEFAULT_TYPE, user):
    try:
        with sqlite3.connect("garage.db") as conn:
            if is_admin(user.id):
                cars = conn.execute(
                    "SELECT id, name, plate FROM cars WHERE is_taken = 1"
                ).fetchall()
            else:
                cars = conn.execute(
                    "SELECT id, name, plate FROM cars WHERE is_taken = 1 AND taken_by = ?",
                    (user.id,)
                ).fetchall()
        
        if not cars:
            msg = "Нет занятых машин" if is_admin(user.id) else "У тебя нет взятых машин"
            msg_obj = await context.bot.send_message(user.id, f"ℹ️ **{msg}**")
            asyncio.create_task(delete_after_delay(context, msg_obj.chat_id, msg_obj.message_id, 3))
            return
        
        keyboard = []
        for car_id, name, plate in cars:
            plate_text = f" ({plate})" if plate else ""
            keyboard.append([InlineKeyboardButton(
                f"{name}{plate_text}",
                callback_data=f"return_{car_id}"
            )])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")])
        
        msg = await context.bot.send_message(
            user.id,
            "🔙 **Твои машины:**",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 10))
    except Exception as e:
        logging.error(f"Ошибка показа взятых машин: {e}")
        msg = await context.bot.send_message(user.id, "❌ Ошибка загрузки")
        asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))

async def ask_car_condition(context: ContextTypes.DEFAULT_TYPE, user, car_id):
    keyboard = [
        [
            InlineKeyboardButton("✅ Целая", callback_data=f"confirm_return_{car_id}_yes"),
            InlineKeyboardButton("❌ Повреждена", callback_data=f"confirm_return_{car_id}_no")
        ],
        [InlineKeyboardButton("◀️ Отмена", callback_data="return_car")]
    ]
    msg = await context.bot.send_message(
        user.id,
        "❓ **Машина целая?**",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 10))

async def return_car(context: ContextTypes.DEFAULT_TYPE, user, car_id, condition):
    condition_text = "✅ целая" if condition == "yes" else "⚠️ повреждена"
    
    try:
        with sqlite3.connect("garage.db") as conn:
            car = conn.execute(
                "SELECT name, plate, taken_by FROM cars WHERE id = ? AND is_taken = 1",
                (car_id,)
            ).fetchone()
            
            if not car:
                msg = await context.bot.send_message(user.id, "❌ **Машина не занята**")
                asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))
                return
            
            if not is_admin(user.id) and car[2] != user.id:
                msg = await context.bot.send_message(user.id, "⛔ **Это не твоя машина**")
                asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))
                return
            
            conn.execute(
                "UPDATE cars SET is_taken = 0, taken_by = NULL, taken_at = NULL WHERE id = ?",
                (car_id,)
            )
        
        log_action(car_id, user.id, "return", condition)
        
        car_name = car[0]
        plate_text = f" ({car[1]})" if car[1] else ""
        user_name = get_user_name(user)
        
        # Отправляем ТОЛЬКО в топик
        await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            message_thread_id=TOPIC_ID,
            text=f"🔙 {user_name} вернул машину {car_name}{plate_text} ({condition_text})"
        )
        
        msg = await context.bot.send_message(
            user.id,
            f"✅ **Ты вернул:**\n{car_name}{plate_text}\n\n📦 Состояние: {condition_text}"
        )
        asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 5))
    except Exception as e:
        logging.error(f"Ошибка возврата: {e}")
        msg = await context.bot.send_message(user.id, "❌ Ошибка операции")
        asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))

async def show_history(context: ContextTypes.DEFAULT_TYPE, user):
    try:
        with sqlite3.connect("garage.db") as conn:
            rows = conn.execute("""
                SELECT h.timestamp, u.username, u.full_name, c.name, c.plate, h.action, h.condition
                FROM history h
                JOIN cars c ON h.car_id = c.id
                LEFT JOIN users u ON h.user_id = u.user_id
                ORDER BY h.timestamp DESC LIMIT 15
            """).fetchall()
        
        if not rows:
            msg = await context.bot.send_message(user.id, "📭 **История пуста**")
            asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))
            return
        
        text = "📜 **Последние действия:**\n\n"
        for ts, username, full_name, car_name, plate, action, condition in rows:
            user_disp = f"@{username}" if username else (full_name or "Неизвестный")
            time_str = datetime.fromisoformat(ts).strftime("%d.%m %H:%M")
            
            if action == "take":
                action_text = "🚗 взял"
            elif action == "return":
                cond = "✅ целая" if condition == "yes" else "⚠️ повреждена"
                action_text = f"🔙 вернул ({cond})"
            elif action == "force_return":
                action_text = "⚡ принудительно"
            else:
                action_text = action
            
            plate_text = f" ({plate})" if plate else ""
            text += f"• {time_str} — {user_disp} {action_text} {car_name}{plate_text}\n"
        
        msg = await context.bot.send_message(
            user.id,
            text,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")
            ]])
        )
        asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 15))
    except Exception as e:
        logging.error(f"Ошибка истории: {e}")
        msg = await context.bot.send_message(user.id, "❌ Ошибка загрузки истории")
        asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))

async def admin_panel(context: ContextTypes.DEFAULT_TYPE, user):
    keyboard = [
        [InlineKeyboardButton("➕ Добавить машину", callback_data="admin_add_car")],
        [InlineKeyboardButton("❌ Удалить машину", callback_data="admin_remove_car")],
        [InlineKeyboardButton("⚡ Принудительный возврат", callback_data="admin_force_return")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")],
    ]
    msg = await context.bot.send_message(
        user.id,
        "⚙️ **Админ-панель**",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 15))

async def add_car_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_car_name"] = update.message.text
    await safe_delete(context, update.effective_chat.id, update.message.message_id)
    
    msg = await update.effective_chat.send_message("🔤 **Введи госномер** (или '-' если нет):")
    asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 5))
    return CAR_PLATE

async def add_car_plate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    plate = None if update.message.text == "-" else update.message.text
    name = context.user_data["new_car_name"]
    await safe_delete(context, update.effective_chat.id, update.message.message_id)
    
    try:
        with sqlite3.connect("garage.db") as conn:
            conn.execute(
                "INSERT INTO cars (name, plate) VALUES (?, ?)",
                (name, plate)
            )
        msg = await update.effective_chat.send_message(f"✅ **Машина добавлена:** {name}")
        asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))
    except Exception as e:
        logging.error(f"Ошибка добавления: {e}")
        msg = await update.effective_chat.send_message("❌ Ошибка добавления")
        asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_delete(context, update.effective_chat.id, update.message.message_id)
    msg = await update.effective_chat.send_message("❌ **Отменено**")
    asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))
    return ConversationHandler.END

async def show_cars_for_remove(context: ContextTypes.DEFAULT_TYPE, user):
    try:
        with sqlite3.connect("garage.db") as conn:
            cars = conn.execute(
                "SELECT id, name, plate, is_taken FROM cars ORDER BY name"
            ).fetchall()
        
        if not cars:
            msg = await context.bot.send_message(user.id, "📭 **Список пуст**")
            asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))
            return
        
        keyboard = []
        for car_id, name, plate, taken in cars:
            status = "🔴" if taken else "🟢"
            plate_text = f" ({plate})" if plate else ""
            keyboard.append([InlineKeyboardButton(
                f"{status} {name}{plate_text}",
                callback_data=f"remove_{car_id}"
            )])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")])
        
        msg = await context.bot.send_message(
            user.id,
            "🗑 **Выбери машину для удаления:**",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 15))
    except Exception as e:
        logging.error(f"Ошибка показа для удаления: {e}")
        msg = await context.bot.send_message(user.id, "❌ Ошибка загрузки")
        asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))

async def remove_car(context: ContextTypes.DEFAULT_TYPE, user, car_id):
    try:
        with sqlite3.connect("garage.db") as conn:
            car = conn.execute(
                "SELECT name FROM cars WHERE id = ?",
                (car_id,)
            ).fetchone()
            
            if not car:
                msg = await context.bot.send_message(user.id, "❌ **Не найдено**")
                asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))
                return
            
            conn.execute("DELETE FROM cars WHERE id = ?", (car_id,))
            conn.execute("DELETE FROM history WHERE car_id = ?", (car_id,))
        
        msg = await context.bot.send_message(user.id, f"✅ **Машина удалена:** {car[0]}")
        asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))
    except Exception as e:
        logging.error(f"Ошибка удаления: {e}")
        msg = await context.bot.send_message(user.id, "❌ Ошибка удаления")
        asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))

async def show_taken_cars_for_admin(context: ContextTypes.DEFAULT_TYPE, user):
    try:
        with sqlite3.connect("garage.db") as conn:
            cars = conn.execute("""
                SELECT c.id, c.name, c.plate
                FROM cars c
                WHERE c.is_taken = 1
            """).fetchall()
        
        if not cars:
            msg = await context.bot.send_message(user.id, "ℹ️ **Нет занятых машин**")
            asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))
            return
        
        keyboard = []
        for car_id, name, plate in cars:
            plate_text = f" ({plate})" if plate else ""
            keyboard.append([InlineKeyboardButton(
                f"{name}{plate_text}",
                callback_data=f"force_return_{car_id}"
            )])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")])
        
        msg = await context.bot.send_message(
            user.id,
            "⚡ **Принудительный возврат:**",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 15))
    except Exception as e:
        logging.error(f"Ошибка показа занятых: {e}")
        msg = await context.bot.send_message(user.id, "❌ Ошибка загрузки")
        asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))

async def force_return_car(context: ContextTypes.DEFAULT_TYPE, admin, car_id):
    try:
        with sqlite3.connect("garage.db") as conn:
            car = conn.execute(
                "SELECT name, plate FROM cars WHERE id = ? AND is_taken = 1",
                (car_id,)
            ).fetchone()
            
            if not car:
                msg = await context.bot.send_message(admin.id, "❌ **Машина не занята**")
                asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))
                return
            
            conn.execute(
                "UPDATE cars SET is_taken = 0, taken_by = NULL, taken_at = NULL WHERE id = ?",
                (car_id,)
            )
        
        log_action(car_id, admin.id, "force_return")
        
        car_name = car[0]
        plate_text = f" ({car[1]})" if car[1] else ""
        admin_name = get_user_name(admin)
        
        # Отправляем ТОЛЬКО в топик
        await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            message_thread_id=TOPIC_ID,
            text=f"⚡ {admin_name} принудительно вернул машину {car_name}{plate_text}"
        )
        
        msg = await context.bot.send_message(
            admin.id,
            f"✅ **Машина возвращена:** {car_name}{plate_text}"
        )
        asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))
    except Exception as e:
        logging.error(f"Ошибка принудительного возврата: {e}")
        msg = await context.bot.send_message(admin.id, "❌ Ошибка операции")
        asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 3))

async def back_to_menu(context: ContextTypes.DEFAULT_TYPE, user, chat_type):
    keyboard = [
        [InlineKeyboardButton("🚗 Взять машину", callback_data="take_car")],
        [InlineKeyboardButton("🔙 Вернуть машину", callback_data="return_car")],
    ]
    
    if chat_type == "private" and is_admin(user.id):
        keyboard.append([InlineKeyboardButton("📜 История", callback_data="history")])
        keyboard.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin_panel")])
    
    msg = await context.bot.send_message(
        user.id,
        "🚘 **Гараж**\nВыбери действие:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    asyncio.create_task(delete_after_delay(context, msg.chat_id, msg.message_id, 10))

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

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    init_db()
    print("🚀 Бот запущен с командой /cars и модерацией чата...")
    app.run_polling()
