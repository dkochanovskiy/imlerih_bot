#!/usr/bin/env python3
import os
import sys
import json
import time
import random
import subprocess
import requests  # ← Добавить этот импорт

def get_main_token():
    try:
        with open("/var/www/imlerih_bot/txt/token.txt", 'r') as f:
            return f.read().strip()
    except:
        return None

main_bot_token = get_main_token()

# проверка жизнеспособности основного бота
def is_main_bot_deleted(main_bot_token):
    if not main_bot_token:
        print("❌ Токен основного бота не получен")
        return True  # считаем что бот удален если не можем получить токен
    
    try:
        url = f"https://api.telegram.org/bot{main_bot_token}/getMe"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("ok", False):
                print(f"✅ Основной бот жив")
                return False  # бот жив
            else:
                print(f"❌ Основной бот удален/заблокирован: {data.get('description', 'unknown')}")
                return True  # бот удален
        else:
            print(f"❌ Ошибка HTTP {response.status_code}")
            return True  # бот вероятно удален
    except Exception as e:
        print(f"❌ Ошибка соединения: {e}")
        return True  # если ошибка соединения


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

# ========= КНОПКИ (ТАКИЕ ЖЕ КАК В ОСНОВНОМ БОТЕ) ========
menu_button = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Меню", callback_data="menu")]
])

main_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Профиль", callback_data="profile"), 
     InlineKeyboardButton(text="Клон бота - защита", callback_data="clone")],
    [InlineKeyboardButton(text="Оформить заказ", callback_data="place_order"), 
     InlineKeyboardButton(text="Менеджер", callback_data="manager")],
    [InlineKeyboardButton(text="Назад", callback_data="back_to_welcome")]
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
    await message.answer("Меню", reply_markup=main_menu)

@dp.message(Command("clone_info"))
async def clone_info_handler(message: types.Message):
    import os
    await message.answer(
        f"📊 <b>Информация о клоне</b>\\n"
        f"🤖 ID: {{CLONE_ID}}\\n"
        f"🔑 Токен: {{BOT_TOKEN[:10]}}...\\n"
        f"⚙️ PID: {{os.getpid()}}",
        parse_mode="HTML"
    )

# ========= ОБРАБОТЧИКИ КНОПОК ========
@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    action = callback.data
    logger.info(f"Button pressed: {{action}}")
    
    if action == "menu":
        await callback.message.edit_text("Меню", reply_markup=main_menu)
        
    elif action == "profile":
        text = get_message_by_id("profile")
        await callback.message.edit_text(text, reply_markup=back_button)
        
    elif action == "clone":
        text = get_message_by_id("clone")
        extra = "\\n\\n🤖 <b>Это резервный клон!</b>\\nСоздайте своего клона для дополнительной защиты."
        await callback.message.edit_text(text + extra, reply_markup=clone_menu, parse_mode="HTML")
        
    elif action == "create_clone":
        text = get_message_by_id("guide_create_clone")
        full_text = text + "\\n\\n📝 <b>Создание резервного клона</b>\\n\\nОтправьте мне токен нового бота.\\n\\nПример токена:\\n<code>1234567890:ABCdefGHIjklmNoPQRsTUVwxyZ-1234567890</code>"
        await callback.message.edit_text(full_text, reply_markup=create_bot_menu, parse_mode="HTML")
        # Здесь можно добавить ожидание токена
        
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
    await message.answer(f"Клон получил: {{message.text}}")

async def main():
    logger.info(f"Starting clone {{CLONE_ID}} with full menu")
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
    if main_bot_token:
        print(f"📋 Получен токен основного бота: {main_bot_token[:15]}...")
        
        # Проверяем статус
        if is_main_bot_deleted(main_bot_token):
            print("🚨 Основной бот НЕДОСТУПЕН! Нужно активировать клона!")
        else:
            print("✅ Основной бот работает, клон в режиме ожидания")
    else:
        print("⚠️ Не удалось получить токен основного бота")