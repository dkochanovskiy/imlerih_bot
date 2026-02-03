#!/usr/bin/env python3
import os
import sys
import json
import time
import random
import subprocess
import requests  # ← Добавить этот импорт

# проверка жизнеспособности основного бота
def check_main_bot_status():
    status_file = "/var/www/imlerih_bot/main_bot_status.json"
    
    if not os.path.exists(status_file):
        return False  # Файла нет → основной бот НЕ работает
    
    try:
        with open(status_file, 'r') as f:
            data = json.load(f)
        
        return data.get("status", "unknown") == "running"
        
    except Exception as e:
        return False  # Ошибка чтения → основной бот НЕ работает

def create_clone_with_full_menu(token, clone_id):
    """Создает клон с полным меню как у основного бота"""
    
    clone_dir = f"/var/www/imlerih_bot/clones/{clone_id}"
    os.makedirs(clone_dir, exist_ok=True)
    os.makedirs(f"{clone_dir}/logs", exist_ok=True)
    os.makedirs(f"{clone_dir}/txt", exist_ok=True)
    
    with open(f"{clone_dir}/txt/token.txt", 'w') as f:
        f.write(token)
    
    script = f'''#!/usr/bin/env python3
import asyncio
import logging
import json
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = "{token}"
CLONE_ID = "{clone_id}"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - CLONE - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("{clone_dir}/logs/bot.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ========= ФУНКЦИЯ ПРОВЕРКИ СТАТУСА ОСНОВНОГО БОТА ========
def check_main_bot_status():
    status_file = "/var/www/imlerih_bot/main_bot_status.json"
    logger.info(f"Checking main bot status from file: {{status_file}}")
    
    if not os.path.exists(status_file):
        logger.warning(f"Status file not found: {{status_file}}")
        return False  # Основной бот не работает
    
    try:
        with open(status_file, 'r') as f:
            data = json.load(f)
        
        logger.info(f"Status file content: {{data}}")
        
        status = data.get("status", "unknown")
        logger.info(f"Main bot status: {{status}}")
        
        # Проверяем статус - если "running", то бот работает
        return status == "running"
        
    except Exception as e:
        logger.error(f"Error checking main bot status: {{e}}", exc_info=True)
        return False  # Основной бот не работает

# ========= ФУНКЦИЯ СОЗДАНИЯ МЕНЮ С УЧЕТОМ СТАТУСА ========
def create_main_menu():
    main_bot_running = check_main_bot_status()
    logger.info(f"Creating menu. Main bot running: {{main_bot_running}}")
    
    if main_bot_running:
        # Основной бот работает - Профиль и Клон бота неактивны
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⛔ Профиль (основной бот работает)", callback_data="profile_disabled"), 
             InlineKeyboardButton(text="⛔ Клон бота (основной бот работает)", callback_data="clone_disabled")],
            [InlineKeyboardButton(text="Оформить заказ", callback_data="place_order"), 
             InlineKeyboardButton(text="Менеджер", callback_data="manager")],
            [InlineKeyboardButton(text="Назад", callback_data="back_to_welcome")]
        ])
    else:
        # Основной бот не работает - все кнопки активны
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Профиль", callback_data="profile"), 
             InlineKeyboardButton(text="Клон бота - защита", callback_data="clone")],
            [InlineKeyboardButton(text="Оформить заказ", callback_data="place_order"), 
             InlineKeyboardButton(text="Менеджер", callback_data="manager")],
            [InlineKeyboardButton(text="Назад", callback_data="back_to_welcome")]
        ])

# ========= БАЗОВЫЕ КНОПКИ ========
menu_button = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Меню", callback_data="menu")]
])

back_button = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="◀️ Назад", callback_data="menu")]
])

clone_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Создать резервного бота", callback_data="create_clone")],
    [InlineKeyboardButton(text="◀️ Назад", callback_data="menu")]
])

create_bot_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="◀️ Назад", callback_data="clone")]
])

# ========= БАЗОВЫЕ ФУНКЦИИ ========
def get_db_connection():
    try:
        import psycopg2
        return psycopg2.connect(
            host="localhost",
            database="karantir_bot",
            user="karantir_user",
            password="karantir_pass",
            port=5432
        )
    except Exception as e:
        logger.error(f"DB error: {{e}}")
        return None

def get_message_by_id(message_id):
    """Получить текст из БД"""
    try:
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT text_message FROM interaction WHERE id_message = %s", (message_id,))
            row = cursor.fetchone()
            conn.close()
            if row and row[0]:
                return row[0]
    except Exception as e:
        logger.error(f"DB query error: {{e}}")
    
    # Fallback тексты
    fallback = {{
        "welcome": "🌴 <b>ДОБРО ПОЖАЛОВАТЬ В СЕРВИС ИНСПЕКТОРА СЭМА</b>",
        "profile": "👤 <b>Профиль</b>",
        "clone": "🤖 <b>Клон бота - защита</b>",
        "place_order": "🛒 <b>Оформить заказ</b>",
        "manager": "👨‍💼 <b>Менеджер</b>",
        "guide_create_clone": "📝 <b>Создание резервного клона</b>"
    }}
    return fallback.get(message_id, "Текст не найден")

# ========= ОБРАБОТЧИКИ КОМАНД ========
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    logger.info(f"Start from {{message.from_user.id}}")
    text = get_message_by_id("welcome")
    await message.answer(text, reply_markup=menu_button, parse_mode="HTML")

@dp.message(Command("menu"))
async def menu_command_handler(message: types.Message):
    logger.info(f"Menu command from {{message.from_user.id}}")
    main_menu = create_main_menu()
    main_bot_running = check_main_bot_status()
    
    if main_bot_running:
        text = "📋 <b>Меню</b>\\n⚠️ <b>Основной бот работает</b>\\nФункции Профиль и Клон бота временно недоступны"
        await message.answer(text, reply_markup=main_menu, parse_mode="HTML")
    else:
        await message.answer("📋 <b>Меню</b>", reply_markup=main_menu, parse_mode="HTML")

@dp.message(Command("status"))
async def status_handler(message: types.Message):
    """Команда для проверки статуса (для отладки)"""
    main_bot_status = check_main_bot_status()
    status_file = "/var/www/imlerih_bot/main_bot_status.json"
    
    try:
        if os.path.exists(status_file):
            with open(status_file, 'r') as f:
                data = json.load(f)
            file_info = f"\\n📄 Файл статуса: {{json.dumps(data, ensure_ascii=False, indent=2)}}"
        else:
            file_info = "\\n📄 Файл статуса: не найден"
    except Exception as e:
        file_info = f"\\n📄 Ошибка чтения файла: {{e}}"
    
    status_text = "работает ✅" if main_bot_status else "не работает ❌"
    
    await message.answer(
        f"🔍 <b>Статус системы</b>\\n"
        f"🤖 Основной бот: {{status_text}}\\n"
        f"🆔 Этот клон: {{CLONE_ID}}\\n"
        f"🔑 Токен: {{BOT_TOKEN[:10]}}...\\n"
        f"{{file_info}}",
        parse_mode="HTML"
    )

@dp.message(Command("clone_info"))
async def clone_info_handler(message: types.Message):
    main_bot_status = "работает ✅" if check_main_bot_status() else "не работает ❌"
    await message.answer(
        f"📊 <b>Информация о клоне</b>\\n"
        f"🤖 ID: {{CLONE_ID}}\\n"
        f"🔑 Токен: {{BOT_TOKEN[:10]}}...\\n"
        f"⚙️ PID: {{os.getpid()}}\\n"
        f"📡 Основной бот: {{main_bot_status}}",
        parse_mode="HTML"
    )

# ========= ОБРАБОТЧИКИ КНОПОК ========
@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    action = callback.data
    logger.info(f"Button pressed: {{action}} from user {{callback.from_user.id}}")
    
    if action == "menu":
        logger.info(f"Menu button pressed, checking main bot status...")
        main_menu = create_main_menu()
        main_bot_running = check_main_bot_status()
        
        if main_bot_running:
            text = "📋 <b>Меню</b>\\n⚠️ <b>Основной бот работает</b>\\nФункции Профиль и Клон бота временно недоступны"
            await callback.message.edit_text(text, reply_markup=main_menu, parse_mode="HTML")
        else:
            await callback.message.edit_text("📋 <b>Меню</b>", reply_markup=main_menu, parse_mode="HTML")
            
    elif action == "profile_disabled" or action == "clone_disabled":
        logger.info(f"Disabled button pressed: {{action}}")
        await callback.answer("⚠️ Эта функция недоступна пока основной бот работает", show_alert=True)
        return
        
    elif action == "profile":
        logger.info(f"Profile button pressed, checking if available...")
        if check_main_bot_status():
            await callback.answer("⚠️ Эта функция недоступна пока основной бот работает", show_alert=True)
            return
        text = get_message_by_id("profile")
        await callback.message.edit_text(text, reply_markup=back_button)
        
    elif action == "clone":
        logger.info(f"Clone button pressed, checking if available...")
        if check_main_bot_status():
            await callback.answer("⚠️ Эта функция недоступна пока основной бот работает", show_alert=True)
            return
        text = get_message_by_id("clone")
        extra = "\\n\\n🤖 <b>Это резервный клон!</b>\\nСоздайте своего клона для дополнительной защиты."
        await callback.message.edit_text(text + extra, reply_markup=clone_menu, parse_mode="HTML")
        
    elif action == "create_clone":
        logger.info(f"Create clone button pressed, checking if available...")
        if check_main_bot_status():
            await callback.answer("⚠️ Эта функция недоступна пока основной бот работает", show_alert=True)
            return
        text = get_message_by_id("guide_create_clone")
        full_text = text + "\\n\\n📝 <b>Создание резервного клона</b>\\n\\nОтправьте мне токен нового бота.\\n\\nПример токена:\\n<code>1234567890:ABCdefGHIjklmNoPQRsTUVwxyZ-1234567890</code>"
        await callback.message.edit_text(full_text, reply_markup=create_bot_menu, parse_mode="HTML")
        
    elif action == "place_order":
        text = get_message_by_id("place_order")
        await callback.message.edit_text(text, reply_markup=back_button)
        
    elif action == "manager":
        text = get_message_by_id("manager")
        await callback.message.edit_text(text, reply_markup=back_button)
        
    elif action == "back_to_welcome":
        text = get_message_by_id("welcome")
        await callback.message.edit_text(text, reply_markup=menu_button, parse_mode="HTML")
    
    await callback.answer()

@dp.message()
async def echo_handler(message: types.Message):
    # Добавляем команду для отладки
    if message.text.lower() == "/debug_status":
        main_bot_running = check_main_bot_status()
        await message.answer(f"Debug: main_bot_running = {{main_bot_running}}")
    else:
        await message.answer(f"Клон получил: {{message.text}}")

async def main():
    logger.info(f"Starting clone {{CLONE_ID}} with full menu")
    logger.info(f"Initial main bot status check: {{check_main_bot_status()}}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
'''
    
    script_path = f"{clone_dir}/bot.py"
    with open(script_path, 'w') as f:
        f.write(script)
    
    os.chmod(script_path, 0o755)
    return clone_dir, script_path

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 full_menu_launcher.py <token>")
        sys.exit(1)
    
    token = sys.argv[1].strip()
    
    if ':' not in token:
        print("❌ Invalid token")
        sys.exit(1)
    
    clone_id = f"clone_{int(time.time())}_{random.randint(1000, 9999)}"
    
    try:
        print(f"🚀 Creating clone with full menu: {clone_id}")
        clone_dir, script_path = create_clone_with_full_menu(token, clone_id)
        
        process = subprocess.Popen(
            ["python3", script_path],
            cwd=clone_dir,
            stdout=open(f"{clone_dir}/logs/bot.log", 'a'),
            stderr=subprocess.STDOUT
        )
        
        print(f"✅ Clone created: {clone_id}")
        print(f"📊 PID: {process.pid}")
        print(f"📁 Directory: {clone_dir}")
        
        time.sleep(2)
        
        # Сохраняем информацию
        processes_file = "/var/www/imlerih_bot/clone_processes.json"
        processes = {}
        if os.path.exists(processes_file):
            try:
                with open(processes_file, 'r') as f:
                    processes = json.load(f)
            except:
                pass
        
        processes[clone_id] = {
            "pid": process.pid,
            "clone_dir": clone_dir,
            "token_preview": token[:10] + "...",
            "menu": "full",
            "status": "running"
        }
        
        with open(processes_file, 'w') as f:
            json.dump(processes, f, indent=2)
        
        print("\\n📌 Available buttons:")
        print("   • Меню → Профиль, Клон бота, Заказ, Менеджер")
        print("   • Создать резервного бота (в меню Клон бота)")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()