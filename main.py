import asyncio
import logging
import random
import time
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
import aiosqlite

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = "8788929549:AAFPi6dYZ3mv8bUjy_SxuhUonHiDGWzysqc"
DB_PATH = "knb_database.db"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- СОСТОЯНИЯ ---
class Form(StatesGroup):
    waiting_for_nickname_permission = State()
    waiting_for_bet = State()
    waiting_for_transfer_amount = State()
    waiting_for_receive_code = State()

# --- БАЗА ДАННЫХ ---
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 0,
            is_public_nick INTEGER DEFAULT 0,
            last_fish_time REAL DEFAULT 0,
            first_start_shown INTEGER DEFAULT 0
        )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS transfers (
            code TEXT PRIMARY KEY,
            sender_id INTEGER,
            amount INTEGER,
            created_at REAL
        )''')
        await db.commit()

async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return await cursor.fetchone()

async def create_user(user_id: int, username: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
        await db.commit()

async def update_balance(user_id: int, amount: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def set_nickname_permission(user_id: int, is_public: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_public_nick = ? WHERE user_id = ?", (is_public, user_id))
        await db.commit()

async def update_last_fish_time(user_id: int, timestamp: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET last_fish_time = ? WHERE user_id = ?", (timestamp, user_id))
        await db.commit()

async def mark_first_start_shown(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET first_start_shown = 1 WHERE user_id = ?", (user_id,))
        await db.commit()

async def add_transfer_code(code: str, sender_id: int, amount: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO transfers (code, sender_id, amount, created_at) VALUES (?, ?, ?, ?)", 
                         (code, sender_id, amount, time.time()))
        await db.commit()

async def get_and_delete_transfer_code(code: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT sender_id, amount, created_at FROM transfers WHERE code = ?", (code,))
        row = await cursor.fetchone()
        if row:
            await db.execute("DELETE FROM transfers WHERE code = ?", (code,))
            await db.commit()
            return row
        return None

async def clean_old_transfers():
    current_time = time.time()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT code, sender_id, amount FROM transfers WHERE created_at < ?", (current_time - 300,))
        expired_codes = await cursor.fetchall()
        for code, sender_id, amount in expired_codes:
            await db.execute("DELETE FROM transfers WHERE code = ?", (code,))
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, sender_id))
        await db.commit()

# --- КЛАВИАТУРЫ ---
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    # Используем точные эмодзи
    builder.row(KeyboardButton(text="Рыбалка 🎣"), KeyboardButton(text="КнБ ✊✌️✋"))
    builder.row(KeyboardButton(text="Баланс 💰"), KeyboardButton(text="Перевод 💸"))
    builder.row(KeyboardButton(text="🔄 Сброс / Reset")) # Кнопка для экстренного сброса
    return builder.as_markup(resize_keyboard=True)

def get_yes_no_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Да", callback_data="perm_yes"),
                InlineKeyboardButton(text="Нет", callback_data="perm_no"))
    return builder.as_markup()

def get_game_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Камень ✊", callback_data="game_rock"),
                InlineKeyboardButton(text="Ножницы ✌️", callback_data="game_scissors"),
                InlineKeyboardButton(text="Бумага ✋", callback_data="game_paper"))
    builder.row(InlineKeyboardButton(text="Отмена ❌", callback_data="game_cancel"))
    return builder.as_markup()

def get_fish_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Поймать 🎣", callback_data="fish_catch"))
    return builder.as_markup()

def get_transfer_choice_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Отправить 📤", callback_data="trans_send"),
                InlineKeyboardButton(text="Получить 📥", callback_data="trans_receive"))
    builder.row(InlineKeyboardButton(text="Назад 🔙", callback_data="back_menu"))
    return builder.as_markup()

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start") | F.text.contains("/start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await clean_old_transfers()

    user = await get_user(message.from_user.id)
    
    if not user:
        await create_user(message.from_user.id, message.from_user.username or "Unknown")
        await message.answer(
            "Разрешаете ли вы показывать ваш ник для показа в статистике топов? Потом нельзя будет изменить свой ответ.",
            reply_markup=get_yes_no_keyboard()
        )
        await message.answer("Лучший мессенджер @anonimgramofficial")
        return

    await message.answer("КнБ легальное только у нас!", reply_markup=get_main_keyboard())

@dp.message(F.text.contains("сброс") | F.text.contains("Reset") | Command("reset"))
async def cmd_reset(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("✅ Состояние сброшено. Меню обновлено.", reply_markup=get_main_keyboard())

@dp.callback_query(F.data.in_(["perm_yes", "perm_no"]))
async def process_permission(callback: types.CallbackQuery, state: FSMContext):
    is_public = 1 if callback.data == "perm_yes" else 0
    await set_nickname_permission(callback.from_user.id, is_public)
    await callback.message.edit_text("Настройка сохранена.")
    await callback.message.answer("КнБ легальное только у нас!", reply_markup=get_main_keyboard())

# --- ИСПРАВЛЕННЫЕ КНОПКИ МЕНЮ ---
# Используем F.text.startswith или contains для надежности, но лучше точное совпадение, если эмодзи верные.
# Добавим обработку на случай, если пользователь нажал кнопку, но бот не понял.

@dp.message(F.text == "Рыбалка 🎣")
async def cmd_fishing(message: types.Message):
    logger.info(f"User {message.from_user.id} clicked Fishing")
    await message.answer("Лови первые свои деньги!", reply_markup=get_fish_keyboard())

@dp.message(F.text == "Баланс 💰")
async def cmd_balance(message: types.Message):
    logger.info(f"User {message.from_user.id} checked balance")
    user = await get_user(message.from_user.id)
    if user:
        await message.answer(f"💳 Ваш баланс: <b>{user[2]}</b> рублей.", parse_mode="HTML")
    else:
        await message.answer("Ошибка пользователя.")

@dp.message(F.text == "КнБ ✊✌️✋")
async def cmd_knb_start(message: types.Message, state: FSMContext):
    logger.info(f"User {message.from_user.id} started KNB")
    await state.set_state(Form.waiting_for_bet)
    await message.answer("Введите ставку (число). Для отмены напишите 'отмена'.")

@dp.message(F.text == "Перевод 💸")
async def cmd_transfer_menu(message: types.Message):
    logger.info(f"User {message.from_user.id} opened transfer menu")
    await message.answer("Выберите действие:", reply_markup=get_transfer_choice_keyboard())

# --- РЫБАЛКА ЛОГИКА ---
@dp.callback_query(F.data == "fish_catch")
async def process_fishing(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Ошибка пользователя", show_alert=True)
        return

    current_time = time.time()
    last_fish = user[4] 
    
    # Кулдаун 1 час (3600 сек)
    if current_time - last_fish < 3600:
        remaining = int(3600 - (current_time - last_fish))
        mins = remaining // 60
        secs = remaining % 60
        await callback.answer(f"⏳ Рыба клюнет только через {mins} мин {secs} сек!", show_alert=True)
        return

    # Шансы
    prizes = [
        (0, 3), (5, 10), (15, 30), (33, 25), (45, 30),
        (60, 21), (20, 40), (26, 50), (100, 2), (500, 0.5)
    ]
    
    total_weight = sum(weight for _, weight in prizes)
    rand_val = random.uniform(0, total_weight)
    
    current_weight = 0
    won_amount = 0
    
    for amount, weight in prizes:
        current_weight += weight
        if rand_val <= current_weight:
            won_amount = amount
            break
            
    await update_balance(callback.from_user.id, won_amount)
    await update_last_fish_time(callback.from_user.id, current_time)
    
    await callback.message.edit_text(f"🎣 Улов: <b>{won_amount}</b> рублей!", parse_mode="HTML")
    await callback.answer()

# --- КНБ ЛОГИКА ---
@dp.message(Form.waiting_for_bet)
async def process_bet_input(message: types.Message, state: FSMContext):
    text = message.text.strip().lower()
    
    if text in ["отмена", "cancel", "назад", "меню"]:
        await state.clear()
        await message.answer("Действие отменено.", reply_markup=get_main_keyboard())
        return

    try:
        bet = int(text)
        if bet < 1: raise ValueError
    except ValueError:
        await message.answer("❌ Ставка должна быть числом больше 0. Попробуйте еще раз.")
        return

    user = await get_user(message.from_user.id)
    if not user or user[2] < bet:
        await message.answer(f"❌ Недостаточно средств. Баланс: {user[2] if user else 0} руб.")
        return

    await update_balance(message.from_user.id, -bet)
    await state.update_data(bet=bet)
    await message.answer("Выбери:", reply_markup=get_game_keyboard())

@dp.callback_query(F.data.startswith("game_"), Form.waiting_for_bet)
async def process_game_choice(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    bet = data['bet']
    user_choice = callback.data.split("_")[1]
    
    choices = ["rock", "scissors", "paper"]
    bot_choice = random.choice(choices)
    
    result = ""
    multiplier = 0
    
    if user_choice == bot_choice:
        result = "Ничья! 🤝"
        multiplier = 1
    elif (user_choice == "rock" and bot_choice == "scissors") or \
         (user_choice == "scissors" and bot_choice == "paper") or \
         (user_choice == "paper" and bot_choice == "rock"):
        result = "Победа! 🎉"
        multiplier = 2
    else:
        result = "Проигрыш! 😢"
        multiplier = 0

    win_amount = bet * multiplier
    if win_amount > 0:
        await update_balance(callback.from_user.id, win_amount)

    ru_map = {"rock": "Камень ✊", "scissors": "Ножницы ✌️", "paper": "Бумага ✋"}
    
    text_res = f"Вы: {ru_map[user_choice]}\nБот: {ru_map[bot_choice]}\n\n{result}\nСтавка: {bet} | Выигрыш: {win_amount}"
    
    await callback.message.edit_text(text_res)
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "game_cancel", Form.waiting_for_bet)
async def cancel_game(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    bet = data['bet']
    await update_balance(callback.from_user.id, bet)
    await state.clear()
    await callback.message.edit_text("Игра отменена. Деньги возвращены.")
    await callback.answer()

# --- ПЕРЕВОДЫ ---
@dp.callback_query(F.data == "trans_send")
async def start_send_transfer(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(Form.waiting_for_transfer_amount)
    await callback.message.edit_text("Введите сумму перевода:")

@dp.message(Form.waiting_for_transfer_amount)
async def process_transfer_amount(message: types.Message, state: FSMContext):
    text = message.text.strip().lower()
    if text in ["отмена", "cancel", "назад"]:
        await state.clear()
        await message.answer("Отменено.", reply_markup=get_main_keyboard())
        return
    
    try:
        amount = int(text)
        if amount < 1: raise ValueError
    except ValueError:
        await message.answer("Введите число.")
        return
        
    user = await get_user(message.from_user.id)
    if user[2] < amount:
        await message.answer("Мало денег.")
        return
        
    await update_balance(message.from_user.id, -amount)
    code = str(random.randint(10000, 99999))
    await add_transfer_code(code, message.from_user.id, amount)
    
    await state.clear()
    await message.answer(f"Код: <code>{code}</code>\nОтдай его другу.", parse_mode="HTML", reply_markup=get_main_keyboard())

@dp.callback_query(F.data == "trans_receive")
async def start_receive_transfer(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(Form.waiting_for_receive_code)
    await callback.message.edit_text("Введите код:")

@dp.message(Form.waiting_for_receive_code)
async def process_receive_code(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if text.lower() in ["отмена", "cancel", "назад"]:
        await state.clear()
        await message.answer("Отменено.", reply_markup=get_main_keyboard())
        return
    
    transfer_data = await get_and_delete_transfer_code(text)
    
    if not transfer_
        await message.answer("Неверный код.")
    else:
        sender_id, amount, created_at = transfer_data
        if time.time() - created_at > 300:
             await message.answer("Код протух.")
        else:
            await update_balance(message.from_user.id, amount)
            await message.answer(f"Получено {amount} руб!", reply_markup=get_main_keyboard())
            
    await state.clear()

@dp.callback_query(F.data == "back_menu")
async def back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Меню:", reply_markup=get_main_keyboard())

# --- ЗАПУСК ---
async def main():
    await init_db()
    logger.info("Bot started...")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
