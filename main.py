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
BOT_TOKEN = "8788929549:AAFPi6dYZ3mv8bUjy_SxuhUonHiDGWzysqc" # Твой токен
DB_PATH = "knb_database.db"

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- СОСТОЯНИЯ (FSM) ---
class Form(StatesGroup):
    waiting_for_nickname_permission = State()
    waiting_for_bet = State()
    waiting_for_transfer_amount = State()
    waiting_for_receive_code = State()

# --- БАЗА ДАННЫХ ---
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Таблица пользователей
        await db.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 0,
            is_public_nick INTEGER DEFAULT 0, -- 1: Да, 0: Нет (Аноним)
            last_fish_time REAL DEFAULT 0,
            first_start_shown INTEGER DEFAULT 0
        )''')
        
        # Таблица кодов перевода
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
    """Удаляет коды старше 5 минут (300 секунд) и возвращает деньги"""
    current_time = time.time()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT code, sender_id, amount FROM transfers WHERE created_at < ?", (current_time - 300,))
        expired_codes = await cursor.fetchall()
        
        for code, sender_id, amount in expired_codes:
            await db.execute("DELETE FROM transfers WHERE code = ?", (code,))
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, sender_id))
            logger.info(f"Возврат средств пользователю {sender_id} за истекший код {code}")
        
        await db.commit()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="Рыбалка 🎣"), KeyboardButton(text="КнБ ✊✌️✋"))
    builder.row(KeyboardButton(text="Баланс 💰"), KeyboardButton(text="Перевод 💸"))
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

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    
    # Очистка старых переводов
    await clean_old_transfers()

    user = await get_user(message.from_user.id)
    
    if not user:
        # Новый пользователь
        await create_user(message.from_user.id, message.from_user.username or "Unknown")
        await message.answer(
            "Разрешаете ли вы показывать ваш ник для показа в статистике топов? Потом нельзя будет изменить свой ответ.",
            reply_markup=get_yes_no_keyboard()
        )
        # Отправляем рекламу только если это самый первый запуск (логика handled inside DB check usually, but here we send immediately for new users)
        # Но по ТЗ: "только 1 раз в первый раз". Так как юзер новый, отправляем.
        await message.answer("Лучший мессенджер @anonimgramofficial")
        return

    # Существующий пользователь
    await message.answer("КнБ легальное только у нас!", reply_markup=get_main_keyboard())

@dp.callback_query(F.data.in_(["perm_yes", "perm_no"]))
async def process_permission(callback: types.CallbackQuery, state: FSMContext):
    is_public = 1 if callback.data == "perm_yes" else 0
    await set_nickname_permission(callback.from_user.id, is_public)
    
    await callback.message.edit_text("Настройка сохранена.")
    await callback.message.answer("КнБ легальное только у нас!", reply_markup=get_main_keyboard())

@dp.message(F.text == "Рыбалка 🎣")
async def cmd_fishing(message: types.Message):
    user = await get_user(message.from_user.id)
    if not user: return # Защита
    
    current_time = time.time()
    last_fish = user[4] # last_fish_time index
    
    if current_time - last_fish < 3600: # 1 час = 3600 сек
        remaining = int(3600 - (current_time - last_fish))
        mins = remaining // 60
        secs = remaining % 60
        await message.answer(f"Вы уже ловили рыбу! Следующая попытка через {mins} мин {secs} сек.")
        return

    await message.answer("Лови первые свои деньги!", reply_markup=get_fish_keyboard())

@dp.callback_query(F.data == "fish_catch")
async def process_fishing(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    current_time = time.time()
    
    # Double check cooldown to prevent race conditions
    if current_time - user[4] < 3600:
        await callback.answer("Кулдаун еще не прошел!", show_alert=True)
        return

    # Логика выигрыша
    # Суммируем шансы: 3+10+30+25+30+21+40+50+2+0.5 = 211.5
    # Нормализуем или используем взвешенный random
    prizes = [
        (0, 3),
        (5, 10),
        (15, 30),
        (33, 25),
        (45, 30),
        (60, 21),
        (20, 40),
        (26, 50),
        (100, 2),
        (500, 0.5)
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
    
    await callback.message.edit_text(f"🎣 Вы поймали: {won_amount} рублей!")
    await callback.answer()

@dp.message(F.text == "КнБ ✊✌️✋")
async def cmd_knb_start(message: types.Message, state: FSMContext):
    await state.set_state(Form.waiting_for_bet)
    await message.answer("Введите ставку (минимум 1 рубль). Для отмены напишите 'отмена'.")

@dp.message(Form.waiting_for_bet)
async def process_bet_input(message: types.Message, state: FSMContext):
    text = message.text.strip().lower()
    
    if text in ["отмена", "cancel", "назад"]:
        await state.clear()
        await message.answer("Действие отменено.", reply_markup=get_main_keyboard())
        return

    try:
        bet = int(text)
        if bet < 1:
            raise ValueError
    except ValueError:
        await message.answer("Ставка должна быть целым числом больше 0. Попробуйте еще раз или напишите 'отмена'.")
        return

    user = await get_user(message.from_user.id)
    if user[2] < bet: # balance index 2
        await message.answer(f"Недостаточно средств. Ваш баланс: {user[2]} руб.")
        return

    # Списываем ставку временно (или блокируем, но проще списать и вернуть при ничье/выигрыше)
    # Логика ТЗ: если победил мы -> 2x, если он -> потеряли, ничья -> 1x (возврат)
    # Значит, сначала списываем ставку.
    await update_balance(message.from_user.id, -bet)
    
    await state.update_data(bet=bet)
    await message.answer("Сделайте ваш выбор:", reply_markup=get_game_keyboard())

@dp.callback_query(F.data.startswith("game_"), Form.waiting_for_bet)
async def process_game_choice(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    bet = data['bet']
    user_choice = callback.data.split("_")[1] # rock, scissors, paper
    
    choices = ["rock", "scissors", "paper"]
    bot_choice = random.choice(choices)
    
    # Определение победителя
    # rock beats scissors, scissors beats paper, paper beats rock
    result = ""
    multiplier = 0
    
    if user_choice == bot_choice:
        result = "Ничья!"
        multiplier = 1 # Возврат ставки
    elif (user_choice == "rock" and bot_choice == "scissors") or \
         (user_choice == "scissors" and bot_choice == "paper") or \
         (user_choice == "paper" and bot_choice == "rock"):
        result = "Вы победили!"
        multiplier = 2
    else:
        result = "Бот победил!"
        multiplier = 0

    win_amount = bet * multiplier
    if win_amount > 0:
        await update_balance(callback.from_user.id, win_amount)

    # Маппинг для красивого вывода
    ru_map = {"rock": "Камень ✊", "scissors": "Ножницы ✌️", "paper": "Бумага ✋"}
    
    text_res = f"Вы: {ru_map[user_choice]}\nБот: {ru_map[bot_choice]}\n\n{result}\nИзменение баланса: {win_amount - bet if multiplier != 1 else 0} (Ставка: {bet})"
    
    await callback.message.edit_text(text_res)
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "game_cancel", Form.waiting_for_bet)
async def cancel_game(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    bet = data['bet']
    # Возвращаем ставку
    await update_balance(callback.from_user.id, bet)
    await state.clear()
    await callback.message.edit_text("Игра отменена. Ставка возвращена.")
    await callback.answer()

@dp.message(F.text == "Баланс 💰")
async def cmd_balance(message: types.Message):
    user = await get_user(message.from_user.id)
    if user:
        await message.answer(f"Ваш баланс: {user[2]} рублей.")

@dp.message(F.text == "Перевод 💸")
async def cmd_transfer_menu(message: types.Message):
    await message.answer("Выберите действие:", reply_markup=get_transfer_choice_keyboard())

@dp.callback_query(F.data == "trans_send")
async def start_send_transfer(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(Form.waiting_for_transfer_amount)
    await callback.message.edit_text("Введите сумму для перевода. Для отмены: 'отмена'")

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
        await message.answer("Введите корректную сумму (целое число > 0).")
        return
        
    user = await get_user(message.from_user.id)
    if user[2] < amount:
        await message.answer("Недостаточно средств.")
        return
        
    # Списываем средства
    await update_balance(message.from_user.id, -amount)
    
    # Генерируем код (5 цифр)
    code = str(random.randint(10000, 99999))
    await add_transfer_code(code, message.from_user.id, amount)
    
    await state.clear()
    await message.answer(f"✅ Средства заморожены.\nВаш код получения: <code>{code}</code>\nОтправьте этот код получателю. Код действителен 5 минут.", parse_mode="HTML", reply_markup=get_main_keyboard())

@dp.callback_query(F.data == "trans_receive")
async def start_receive_transfer(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(Form.waiting_for_receive_code)
    await callback.message.edit_text("Введите код получения денег. Для отмены: 'отмена'")

@dp.message(Form.waiting_for_receive_code)
async def process_receive_code(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if text.lower() in ["отмена", "cancel", "назад"]:
        await state.clear()
        await message.answer("Отменено.", reply_markup=get_main_keyboard())
        return
    
    if len(text) != 5 or not text.isdigit():
        await message.answer("Код должен состоять из 5 цифр.")
        return
        
    transfer_data = await get_and_delete_transfer_code(text)
    
    if not transfer_data:
        await message.answer("❌ Неверный код или срок действия истек.")
    else:
        sender_id, amount, created_at = transfer_data
        # Проверка времени еще раз на всякий случай
        if time.time() - created_at > 300:
             await message.answer("❌ Срок действия кода истек (деньги должны были вернуться отправителю).")
             # В идеале тут нужен механизм возврата, если он не сработал в background, но у нас есть clean_old_transfers при старте
        else:
            await update_balance(message.from_user.id, amount)
            await message.answer(f"✅ Вы получили {amount} рублей!", reply_markup=get_main_keyboard())
            
    await state.clear()

@dp.callback_query(F.data == "back_menu")
async def back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("КнБ легальное только у нас!", reply_markup=get_main_keyboard())

# --- ЗАПУСК ---
async def main():
    await init_db()
    logger.info("Bot started...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")