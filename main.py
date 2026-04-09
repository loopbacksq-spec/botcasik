import asyncio
import logging
import random
import time
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
import aiosqlite

# --- НАСТРОЙКИ ---
# Вставь сюда свой НОВЫЙ токен, если делал Revoke, иначе оставь старый
BOT_TOKEN = "8788929549:AAFPi6dYZ3mv8bUjy_SxuhUonHiDGWzysqc" 
DB_PATH = "knb_database.db"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- СОСТОЯНИЯ ---
class Form(StatesGroup):
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
            last_fish_time REAL DEFAULT 0
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
        await db.execute("INSERT INTO users (user_id, username, balance) VALUES (?, ?, 0)", (user_id, username))
        await db.commit()

async def update_balance(user_id: int, amount: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def update_last_fish(user_id: int, ts: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET last_fish_time = ? WHERE user_id = ?", (ts, user_id))
        await db.commit()

async def add_transfer(code: str, sender: int, amount: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO transfers VALUES (?, ?, ?, ?)", (code, sender, amount, time.time()))
        await db.commit()

async def get_transfer(code: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM transfers WHERE code = ?", (code,))
        row = await cursor.fetchone()
        if row:
            await db.execute("DELETE FROM transfers WHERE code = ?", (code,))
            await db.commit()
        return row

# --- КЛАВИАТУРЫ ---
def get_main_kb():
    kb = ReplyKeyboardBuilder()
    # ВАЖНО: Текст кнопок должен быть ИДЕНТИЧЕН тому, что в обработчиках ниже
    kb.row(KeyboardButton(text="Рыбалка 🎣"), KeyboardButton(text="КнБ ✊✌️✋"))
    kb.row(KeyboardButton(text="Баланс 💰"), KeyboardButton(text="Перевод 💸"))
    return kb.as_markup(resize_keyboard=True)

def get_game_kb():
    kb = ReplyKeyboardBuilder() # Используем обычную для надежности, или инлайн
    from aiogram.types import InlineKeyboardButton
    ikb = InlineKeyboardBuilder()
    ikb.row(InlineKeyboardButton(text="Камень ✊", callback_data="rock"),
            InlineKeyboardButton(text="Ножницы ✌️", callback_data="scissors"),
            InlineKeyboardButton(text="Бумага ✋", callback_data="paper"))
    return ikb.as_markup()

def get_fish_kb():
    from aiogram.types import InlineKeyboardButton
    ikb = InlineKeyboardBuilder()
    ikb.row(InlineKeyboardButton(text="Поймать 🎣", callback_data="catch_fish"))
    return ikb.as_markup()

# --- ОБРАБОТЧИКИ ---

# 1. ТЕСТОВАЯ КОМАНДА
@dp.message(Command("test"))
async def cmd_test(message: types.Message):
    await message.answer("✅ БОТ ЖИВ И РАБОТАЕТ!")

# 2. СТАРТ
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user = await get_user(message.from_user.id)
    if not user:
        await create_user(message.from_user.id, message.from_user.username or "Anon")
    
    await message.answer("🎮 Меню игры:", reply_markup=get_main_kb())

# 3. БАЛАНС (САМОЕ ВАЖНОЕ)
@dp.message(F.text == "Баланс 💰")
async def cmd_balance(message: types.Message):
    logger.info(f"Нажат баланс юзером {message.from_user.id}")
    user = await get_user(message.from_user.id)
    if user:
        await message.answer(f"💰 Твой баланс: <b>{user[2]}</b> руб.", parse_mode="HTML")
    else:
        await message.answer("Ошибка базы данных.")

# 4. РЫБАЛКА
@dp.message(F.text == "Рыбалка 🎣")
async def cmd_fishing(message: types.Message):
    logger.info(f"Нажата рыбалка юзером {message.from_user.id}")
    user = await get_user(message.from_user.id)
    now = time.time()
    
    # Если юзера нет (баг), создаем
    if not user:
        await create_user(message.from_user.id, message.from_user.username or "Anon")
        user = (message.from_user.id, "Anon", 0, 0)

    last_fish = user[3] # индекс 3 это last_fish_time
    
    if now - last_fish < 3600:
        wait = int(3600 - (now - last_fish))
        await message.answer(f"⏳ Рыба клюнет через {wait // 60} мин.")
        return

    await message.answer("🌊 Лови удачу!", reply_markup=get_fish_kb())

@dp.callback_query(F.data == "catch_fish")
async def process_fish(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    now = time.time()
    if now - user[3] < 3600:
        await callback.answer("Рано!", show_alert=True)
        return

    # Шансы
    rand = random.randint(1, 1000)
    win = 0
    if rand <= 5: win = 500      # 0.5%
    elif rand <= 25: win = 100   # 2%
    elif rand <= 75: win = 60    # 5%
    elif rand <= 125: win = 45   # 5%
    elif rand <= 375: win = 33   # 25%
    elif rand <= 675: win = 26   # 30%
    elif rand <= 875: win = 20   # 20%
    elif rand <= 975: win = 15   # 10%
    elif rand <= 995: win = 5    # 2%
    else: win = 0                # 0.5%

    await update_balance(callback.from_user.id, win)
    await update_last_fish(callback.from_user.id, now)
    
    await callback.message.edit_text(f"🎣 Поймано: <b>{win}</b> руб!", parse_mode="HTML")
    await callback.answer()

# 5. КНБ
@dp.message(F.text == "КнБ ✊✌️✋")
async def cmd_knb(message: types.Message, state: FSMContext):
    await state.set_state(Form.waiting_for_bet)
    await message.answer("💸 Введи сумму ставки (число):")

@dp.message(Form.waiting_for_bet)
async def process_bet(message: types.Message, state: FSMContext):
    if message.text.lower() in ["отмена", "назад"]:
        await state.clear()
        await message.answer("Отмена.", reply_markup=get_main_kb())
        return
    
    try:
        amount = int(message.text)
        if amount <= 0: raise Exception
    except:
        await message.answer("❌ Введи число больше 0.")
        return

    user = await get_user(message.from_user.id)
    if user[2] < amount:
        await message.answer("❌ Мало денег.")
        return

    await update_balance(message.from_user.id, -amount)
    await state.update_data(bet=amount)
    await message.answer("Выбери:", reply_markup=get_game_kb())

@dp.callback_query(F.data.in_(["rock", "scissors", "paper"]), Form.waiting_for_bet)
async def play_knb(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    bet = data['bet']
    user_choice = callback.data
    
    choices = ["rock", "scissors", "paper"]
    bot_choice = random.choice(choices)
    
    win = 0
    text = ""
    
    if user_choice == bot_choice:
        text = "Ничья 🤝"
        win = bet
    elif (user_choice == "rock" and bot_choice == "scissors") or \
         (user_choice == "scissors" and bot_choice == "paper") or \
         (user_choice == "paper" and bot_choice == "rock"):
        text = "Победа! 🎉"
        win = bet * 2
    else:
        text = "Проигрыш 😢"
        win = 0

    if win > 0:
        await update_balance(callback.from_user.id, win)

    icons = {"rock": "✊", "scissors": "✌️", "paper": "✋"}
    await callback.message.edit_text(f"Ты: {icons[user_choice]} | Бот: {icons[bot_choice]}\n{text}\nВыигрыш: {win}")
    await state.clear()
    await callback.answer()

# 6. ПЕРЕВОД (Упрощенно)
@dp.message(F.text == "Перевод 💸")
async def cmd_transfer(message: types.Message):
    await message.answer("Функция в разработке (демо).")

# ЗАПУСК
async def main():
    await init_db()
    logger.info("ЗАПУСК БОТА...")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
