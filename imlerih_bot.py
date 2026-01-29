#!/usr/bin/env python3
# /var/www/imlerih_bot/imlerih_bot.py

import asyncio
import logging
import subprocess
import json
import os
import random
import time
import re
import shutil
import signal
from collections import defaultdict
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import psycopg2
from psycopg2.extras import DictCursor

# =========== SYSTEMD SOCKET ACTIVATION ===========
import socket
import sys

def check_port_in_use(port=8080):
    """Проверка, занят ли порт (для совместимости)"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        return result == 0
    except:
        return False

# Проверяем, не запущен ли уже бот
if check_port_in_use():
    print("⚠️ Порт 8080 занят. Возможно, бот уже запущен.")
    # Можно выйти или продолжить в polling режиме

# ==================== НАСТРОЙКИ ====================

# Токен из файла
try:
    with open("/var/www/imlerih_bot/txt/token.txt", "r", encoding="utf-8") as f:
        BOT_TOKEN = f.read().strip()
except FileNotFoundError:
    print("❌ Файл /var/www/imlerih_bot/txt/token.txt не найден!")
    exit()

# Создаём основного бота и диспетчер
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Файлы состояния
STATE_FILE = "/var/www/imlerih_bot/clone_state.json"
BACKUP_TOKENS_FILE = "/var/www/imlerih_bot/backup_tokens.json"
OWNER_CLONES_FILE = "/var/www/imlerih_bot/owner_clones.json"  # Новый файл для связи владелец-клоны
CLONE_PROCESSES_FILE = "/var/www/imlerih_bot/clone_processes.json"  # Файл для хранения PID клонов

# ========= ЗАЩИТА ОТ СПАМА ========

# Словарь для хранения капч пользователей: {user_id: {"answer": число, "timestamp": время}}
captcha_storage = {}

# Словарь для отслеживания активности пользователей (для определения спама)
user_activity = defaultdict(list)  # {user_id: [timestamp1, timestamp2, ...]}

# Настройки защиты от спама
CAPTCHA_LIFETIME = 300  # 5 минут
SPAM_TIME_WINDOW = 10  # 10 секунд - окно для проверки спама
SPAM_MESSAGE_LIMIT = 5  # 5 сообщений за 10 секунд = спам

# Генерация простой математической капчи
def generate_captcha() -> tuple[str, int]:
    """Генерирует простую математическую задачу и возвращает (текст, ответ)"""
    a = random.randint(1, 10)
    b = random.randint(1, 10)
    operation = random.choice(['+', '-', '*'])
    
    if operation == '+':
        answer = a + b
        text = f"{a} + {b}"
    elif operation == '-':
        # Убедимся, что результат не отрицательный
        if a < b:
            a, b = b, a
        answer = a - b
        text = f"{a} - {b}"
    else:  # '*'
        # Для умножения используем маленькие числа
        a = random.randint(1, 5)
        b = random.randint(1, 5)
        answer = a * b
        text = f"{a} × {b}"
    
    return text, answer

# Проверка, требуется ли капча пользователю
def requires_captcha(user_id: int) -> bool:
    """Проверяет, нужно ли показывать капчу пользователю"""
    # Если у пользователя уже есть активная капча
    if user_id in captcha_storage:
        return True
    
    # Проверка на спам по количеству сообщений
    current_time = time.time()
    
    # Очищаем старые записи активности
    user_activity[user_id] = [t for t in user_activity[user_id] 
                             if current_time - t < SPAM_TIME_WINDOW]
    
    # Добавляем текущее время
    user_activity[user_id].append(current_time)
    
    # Если слишком много сообщений за короткое время - показываем капчу
    if len(user_activity[user_id]) > SPAM_MESSAGE_LIMIT:
        logging.warning(f"⚠️ Обнаружен возможный спам от пользователя {user_id}")
        return True
    
    return False

# Очистка старых капч
def cleanup_old_captchas():
    """Удаляет просроченные капчи"""
    current_time = time.time()
    expired_users = []
    
    for user_id, captcha_data in captcha_storage.items():
        if current_time - captcha_data["timestamp"] > CAPTCHA_LIFETIME:
            expired_users.append(user_id)
    
    for user_id in expired_users:
        captcha_storage.pop(user_id, None)

# Очистка старой активности пользователей
def cleanup_old_activity():
    """Удаляет старые записи активности"""
    current_time = time.time()
    for user_id in list(user_activity.keys()):
        # Оставляем только записи за последнюю минуту
        user_activity[user_id] = [t for t in user_activity[user_id] 
                                 if current_time - t < 60]
        # Если список пуст, удаляем пользователя
        if not user_activity[user_id]:
            user_activity.pop(user_id, None)

# ========= КНОПКИ ========

menu_button = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Меню", callback_data="menu")]])
main_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Профиль", callback_data="profile"), InlineKeyboardButton(text="Клон бота - защита", callback_data="clone")],
    [InlineKeyboardButton(text="Оформить заказ", callback_data="place_order"), InlineKeyboardButton(text="Менеджер", callback_data="manager")],
    [InlineKeyboardButton(text="Назад", callback_data="back_to_welcome")]
])
back_button = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="menu")]])
clone_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Создать резервного бота", callback_data="create_clone")],
    [InlineKeyboardButton(text="◀️ Назад", callback_data="menu")]
])
create_bot_menu = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="clone")]])

# Подключение к PostgreSQL
def get_db_connection():
    return psycopg2.connect(
        host="localhost",
        database="karantir_bot",
        user="karantir_user",
        password="karantir_pass"
    )

# Получение текста из БД
def get_message_by_id(message_id: str) -> str:
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)
        cursor.execute("SELECT text_message FROM interaction WHERE id_message = %s", (message_id,))
        row = cursor.fetchone()
        conn.close()
        return row["text_message"] if row else "Текст не найден."
    except Exception as e:
        logging.error(f"❌ Ошибка при запросе к БД: {e}")
        return "Ошибка загрузки текста."

# Проверка формата токена
def is_valid_token(token: str) -> bool:
    """Проверка формата токена телеграм бота"""
    if not token or ':' not in token:
        return False
    
    # Упрощенная проверка формата токена
    parts = token.split(':')
    if len(parts) != 2:
        return False
    
    bot_id, bot_secret = parts
    
    # Проверяем ID бота (должен быть числом)
    if not bot_id.isdigit():
        return False
    
    # Проверяем длину секрета (обычно 35 символов)
    if len(bot_secret) < 30 or len(bot_secret) > 50:
        return False
    
    return True

def save_owner_clone_info(clone_token: str):
    """Сохранение информации о том, что текущий бот создал клона"""
    try:
        # Загружаем существующие данные
        if os.path.exists(OWNER_CLONES_FILE):
            with open(OWNER_CLONES_FILE, 'r') as f:
                owner_data = json.load(f)
        else:
            owner_data = {}
        
        # Добавляем клон к списку созданных текущим ботом
        owner_token = BOT_TOKEN
        if owner_token not in owner_data:
            owner_data[owner_token] = []
        
        if clone_token not in owner_data[owner_token]:
            owner_data[owner_token].append(clone_token)
            with open(OWNER_CLONES_FILE, 'w') as f:
                json.dump(owner_data, f, indent=2)
            logging.info(f"✅ Информация о владельце сохранена: {owner_token[:10]}... -> {clone_token[:10]}...")
            return True
    except Exception as e:
        logging.error(f"❌ Ошибка сохранения информации о владельце: {e}")
    return False

def has_created_clones() -> bool:
    """Проверяет, создавал ли текущий бот клонов"""
    try:
        if os.path.exists(OWNER_CLONES_FILE):
            with open(OWNER_CLONES_FILE, 'r') as f:
                owner_data = json.load(f)
            
            # Проверяем, есть ли запись для текущего бота
            owner_token = BOT_TOKEN
            if owner_token in owner_data:
                clones = owner_data[owner_token]
                return len(clones) > 0
        return False
    except Exception as e:
        logging.error(f"❌ Ошибка проверки созданных клонов: {e}")
        return False

def save_backup_token(token: str):
    """Сохранение токена в список резервных"""
    try:
        tokens = []
        if os.path.exists(BACKUP_TOKENS_FILE):
            with open(BACKUP_TOKENS_FILE, 'r') as f:
                tokens = json.load(f)
        
        if token not in tokens:
            tokens.append(token)
            with open(BACKUP_TOKENS_FILE, 'w') as f:
                json.dump(tokens, f, indent=2)
            logging.info(f"✅ Токен сохранен в резервные: {token[:10]}...")
            
            # Сохраняем информацию о том, что текущий бот создал этого клона
            save_owner_clone_info(token)
            return True
    except Exception as e:
        logging.error(f"❌ Ошибка сохранения токена: {e}")
    return False

def save_clone_process_info(clone_id: str, pid: int, token: str):
    """Сохранение информации о процессе клона"""
    try:
        if os.path.exists(CLONE_PROCESSES_FILE):
            with open(CLONE_PROCESSES_FILE, 'r') as f:
                processes = json.load(f)
        else:
            processes = {}
        
        processes[clone_id] = {
            "pid": pid,
            "token": token[:10] + "...",
            "start_time": time.time(),
            "status": "running"
        }
        
        with open(CLONE_PROCESSES_FILE, 'w') as f:
            json.dump(processes, f, indent=2)
        
        logging.info(f"✅ Сохранена информация о процессе клона {clone_id}: PID={pid}")
        return True
    except Exception as e:
        logging.error(f"❌ Ошибка сохранения информации о процессе: {e}")
        return False

def create_clone_directly(token: str) -> tuple[bool, str]:
    """Создание резервного клона напрямую как фоновый процесс"""
    try:
        logging.info(f"🔄 Начинаю создание клона с токеном: {token[:10]}...")
        
        # 1. Создаем уникальный ID для клона
        clone_id = f"clone_{int(time.time())}_{random.randint(1000, 9999)}"
        logging.info(f"✅ Создан ID клона: {clone_id}")
        
        # 2. Создаем простой скрипт клона
        clone_script = f"""#!/usr/bin/env python3
# Клон бота {clone_id}

import asyncio
import logging
import sys
import os
import signal
import time

# Добавляем путь для импортов
sys.path.insert(0, '/var/www/imlerih_bot')

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# Токен клона
BOT_TOKEN = "{token}"

# Настройка логирования
log_file = f"/var/www/imlerih_bot/logs/clone_{{clone_id}}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await message.answer(f"🤖 Я резервный клон! ID: {clone_id}\\nТокен: {token[:10]}...")

@dp.message(Command("status"))
async def status_handler(message: types.Message):
    await message.answer(f"✅ Резервный клон работает!\\nID: {clone_id}\\nЗапущен: {time.ctime()}")

@dp.message(Command("ping"))
async def ping_handler(message: types.Message):
    await message.answer(f"🏓 Pong! Клон {clone_id} жив")

async def main():
    try:
        logger.info(f"🚀 Запуск резервного клона {{clone_id}}...")
        logger.info(f"🔑 Токен: {token[:10]}...")
        
        # Удаляем вебхук если был
        await bot.delete_webhook(drop_pending_updates=True)
        
        logger.info("🔄 Запуск polling...")
        await dp.start_polling(bot)
        
    except asyncio.CancelledError:
        logger.info("⛔ Получен сигнал остановки")
    except Exception as e:
        logger.error(f"❌ Ошибка в клоне: {{e}}")
        raise
    finally:
        logger.info(f"👋 Остановка клона {{clone_id}}")
        await bot.session.close()

def signal_handler(signum, frame):
    logger.info(f"📶 Получен сигнал {{signum}}, останавливаюсь...")
    raise asyncio.CancelledError

if __name__ == "__main__":
    # Регистрируем обработчики сигналов
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Запускаем бота
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👆 Остановка по Ctrl+C")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {{e}}")
        sys.exit(1)
"""
        
        # 3. Сохраняем скрипт клона во временную директорию
        script_filename = f"/var/www/imlerih_bot/clones/bot_{clone_id}.py"
        
        # Создаем директорию если её нет
        os.makedirs("/var/www/imlerih_bot/clones", exist_ok=True)
        
        with open(script_filename, 'w') as f:
            f.write(clone_script)
        
        # 4. Даем права на выполнение
        os.chmod(script_filename, 0o755)
        logging.info(f"✅ Создан скрипт клона: {script_filename}")
        
        # 5. Запускаем клон как фоновый процесс
        log_file = f"/var/www/imlerih_bot/logs/clone_{clone_id}.log"
        
        # Используем nohup для запуска в фоне
        cmd = f"nohup python3 {script_filename} > {log_file} 2>&1 & echo $!"
        
        logging.info(f"🚀 Запускаю команду: {cmd}")
        
        # Запускаем процесс
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0 and result.stdout.strip():
            pid = int(result.stdout.strip())
            logging.info(f"✅ Клон {clone_id} запущен с PID: {pid}")
            
            # Сохраняем информацию о процессе
            save_clone_process_info(clone_id, pid, token)
            
            # 6. Ждем немного и проверяем, запустился ли процесс
            time.sleep(2)
            
            # Проверяем, жив ли процесс
            try:
                os.kill(pid, 0)  # Проверка существования процесса
                process_running = True
            except OSError:
                process_running = False
                logging.warning(f"⚠️ Процесс {pid} не запущен после ожидания")
            
            # 7. Проверяем лог файл на наличие ошибок
            log_content = ""
            if os.path.exists(log_file):
                with open(log_file, 'r') as f:
                    log_content = f.read(1000)  # Читаем первые 1000 символов
            
            # 8. Сохраняем токен
            save_backup_token(token)
            
            if process_running:
                return True, f"✅ Резервный клон создан и запущен!\nID: {clone_id}\nPID: {pid}\nЛог: {log_file}\nСтатус: {'🟢 Запущен' if process_running else '🔴 Не запущен'}\n\nПервые строки лога:\n{log_content[:500]}"
            else:
                return False, f"⚠️ Клон создан, но возможно не запустился\nID: {clone_id}\nPID: {pid}\nПроверьте лог: {log_file}"
        
        else:
            error_msg = result.stderr if result.stderr else "Неизвестная ошибка"
            logging.error(f"❌ Ошибка запуска клона: {error_msg}")
            return False, f"Ошибка запуска клона: {error_msg}"
        
    except Exception as e:
        logging.error(f"❌ Исключение при создании клона: {e}")
        return False, f"Исключение при создании клона: {str(e)}"

def create_clone_via_manager(token: str) -> tuple[bool, str]:
    """Создание резервного клона через менеджер или напрямую"""
    try:
        manager_path = "/var/www/imlerih_bot/clone_manager.py"
        
        if os.path.exists(manager_path):
            # Используем менеджер клонов
            logging.info(f"🔄 Использую менеджер клонов для создания клона")
            
            result = subprocess.run(
                ["python3", manager_path, "create", token],
                capture_output=True,
                text=True,
                timeout=60,
                cwd="/var/www/imlerih_bot"
            )
            
            logging.info(f"📊 Результат менеджера:\nКод: {result.returncode}\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}")
            
            if result.returncode == 0:
                save_backup_token(token)
                return True, f"✅ Клон создан через менеджер\n{result.stdout}"
            else:
                # Если менеджер не сработал, пробуем напрямую
                logging.warning("⚠️ Менеджер клонов вернул ошибку, пробую создать напрямую")
                return create_clone_directly(token)
        else:
            # Менеджера нет, создаем напрямую
            logging.info("⚠️ Менеджер клонов не найден, создаю клон напрямую")
            return create_clone_directly(token)
            
    except subprocess.TimeoutExpired:
        logging.error("⏰ Таймаут при создании клона")
        return False, "Таймаут при создании клона"
    except Exception as e:
        logging.error(f"❌ Исключение при создании клона: {e}")
        return False, f"Исключение: {str(e)}"

def has_clones() -> bool:
    """Проверяет, есть ли созданные клон-боты (глобально)"""
    try:
        if os.path.exists(BACKUP_TOKENS_FILE):
            with open(BACKUP_TOKENS_FILE, 'r') as f:
                tokens = json.load(f)
                return len(tokens) > 0
        return False
    except Exception as e:
        logging.error(f"❌ Ошибка проверки клонов: {e}")
        return False

def get_clones_list() -> str:
    """Получение списка всех клонов"""
    try:
        # Проверяем активные процессы клонов
        output_lines = []
        
        # Проверяем файл с процессами
        if os.path.exists(CLONE_PROCESSES_FILE):
            with open(CLONE_PROCESSES_FILE, 'r') as f:
                processes = json.load(f)
            
            for clone_id, info in processes.items():
                pid = info.get("pid", 0)
                status = info.get("status", "unknown")
                token_preview = info.get("token", "unknown")
                
                # Проверяем, жив ли процесс
                try:
                    os.kill(pid, 0)
                    process_status = "🟢 Запущен"
                except OSError:
                    process_status = "🔴 Остановлен"
                
                output_lines.append(f"• {clone_id}: PID={pid}, {process_status}, токен={token_preview}")
        
        # Проверяем процессы через ps
        try:
            result = subprocess.run(
                ["ps", "aux", "|", "grep", "bot_clone_", "|", "grep", "-v", "grep"],
                shell=True,
                capture_output=True,
                text=True
            )
            
            if result.stdout:
                output_lines.append("\n📊 Активные процессы:")
                for line in result.stdout.strip().split('\n'):
                    if line:
                        output_lines.append(f"  {line[:100]}")
        except Exception as e:
            output_lines.append(f"\n⚠️ Ошибка проверки процессов: {e}")
        
        if not output_lines:
            return "📭 Активные клоны не найдены"
        
        return "\n".join(output_lines)
        
    except Exception as e:
        return f"❌ Ошибка получения списка: {str(e)}"

# Глобальное состояние
waiting_for_token_main = set()

# ============ ОБРАБОТЧИКИ ОСНОВНОГО БОТА ============

@dp.message(Command("help"))
async def help_command(message: types.Message):
    await message.answer(
        "🔧 Доступные команды:\n"
        "/start — начать\n"
        "/captcha — пройти тест капчи\n"
        "/status — статус системы (только админ)\n"
        "/debug_main — диагностика (только админ)\n"
        "/polling_info — информация о polling-режиме\n"
        "/test_clone — тест создания клона (только админ)\n"
        "/clones_list — список клонов (только админ)"
    )

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    logging.info(f"🎉 Основной бот: /start от {message.from_user.id}")
    
    # Очищаем старые капчи при запуске
    cleanup_old_captchas()
    cleanup_old_activity()
    
    text = get_message_by_id("welcome")
    extra_text = "\n\n🎉 <b>Вы основной бот!</b>\nСоздайте резервного клона на случай сбоев.\n\n<b>Режим работы: Polling</b>"
    
    await message.answer(text + extra_text, reply_markup=menu_button, parse_mode="HTML")

@dp.message(Command("test_clone"))
async def test_clone_command(message: types.Message):
    """Тест создания клона (только для админа)"""
    if message.from_user.id != 291178183:
        await message.answer("❌ Доступ запрещён")
        return
    
    try:
        # Используем тестовый токен (нужно заменить на реальный для теста)
        test_token = "1234567890:ABCdefGHIjklmNoPQRsTUVwxyZ-1234567890"
        
        await message.answer("🧪 <b>Тест создания клона...</b>\nИспользую тестовый токен.", parse_mode="HTML")
        
        success, result = create_clone_directly(test_token)
        
        if success:
            await message.answer(f"✅ <b>Тест успешен!</b>\n\n{result}", parse_mode="HTML")
        else:
            await message.answer(f"❌ <b>Тест не удался:</b>\n\n{result}", parse_mode="HTML")
            
    except Exception as e:
        await message.answer(f"❌ <b>Ошибка теста:</b>\n\n{str(e)}", parse_mode="HTML")

@dp.message(Command("clones_list"))
async def clones_list_command(message: types.Message):
    """Список всех клонов (только для админа)"""
    if message.from_user.id != 291178183:
        await message.answer("❌ Доступ запрещён")
        return
    
    clones_list = get_clones_list()
    
    await message.answer(
        f"📋 <b>Список клонов:</b>\n\n{clones_list}",
        parse_mode="HTML"
    )

@dp.message(Command("captcha"))
async def captcha_command(message: types.Message):
    """Команда для тестирования капчи (доступна всем)"""
    logging.info(f"📨 Получена команда /captcha от пользователя {message.from_user.id} ({message.from_user.username})")
    
    try:
        question, answer = generate_captcha()
        captcha_storage[message.from_user.id] = {
            "answer": answer,
            "timestamp": time.time()
        }
        
        logging.info(f"✅ Капча сгенерирована: {question} = {answer}")
        
        await message.answer(
            f"🧪 <b>Тест капчи</b>\n\n"
            f"Решите простой пример:\n"
            f"<b>{question} = ?</b>\n\n"
            f"Ответьте числом.\n\n"
            f"<i>Эта команда для тестирования защиты от спама.</i>",
            parse_mode="HTML"
        )
        logging.info(f"📤 Ответ отправлен пользователю {message.from_user.id}")
        
    except Exception as e:
        logging.error(f"❌ Ошибка в обработчике /captcha: {e}")
        await message.answer(f"❌ Произошла ошибка: {str(e)}")

@dp.message(Command("debug_main"))
async def debug_main_handler(message: types.Message):
    """Детальная диагностика основного бота"""
    if message.from_user.id != 291178183:
        return
    
    # Собираем информацию
    info_lines = []
    
    # 1. Systemd (если используется)
    try:
        result = subprocess.run(
            ["systemctl", "status", "imlerih_bot", "--no-pager"],
            capture_output=True,
            text=True
        )
        info_lines.append(f"<b>Systemd статус основного бота:</b>\n<pre>{result.stdout[:500]}</pre>")
    except Exception as e:
        info_lines.append(f"❌ Systemd ошибка: {e}")
    
    # 2. Процессы
    try:
        result = subprocess.run(
            ["ps", "aux", "|", "grep", "imlerih_bot", "|", "grep", "-v", "grep"],
            shell=True,
            capture_output=True,
            text=True
        )
        if result.stdout:
            info_lines.append(f"<b>Процессы:</b>\n<pre>{result.stdout}</pre>")
        else:
            info_lines.append("❌ Процессы не найдены")
    except Exception as e:
        info_lines.append(f"❌ Ошибка проверки процессов: {e}")
    
    # 3. Статус защиты от спама
    active_captchas = len(captcha_storage)
    active_users = len(user_activity)
    info_lines.append(f"<b>Защита от спама:</b>\nАктивных капч: {active_captchas}\nОтслеживаемых пользователей: {active_users}")
    
    # 4. Проверка файлов
    try:
        manager_exists = os.path.exists("/var/www/imlerih_bot/clone_manager.py")
        token_exists = os.path.exists("/var/www/imlerih_bot/txt/token.txt")
        clones_dir_exists = os.path.exists("/var/www/imlerih_bot/clones")
        processes_file_exists = os.path.exists(CLONE_PROCESSES_FILE)
        info_lines.append(f"<b>Файлы:</b>\nМенеджер: {'✅' if manager_exists else '❌'}\nТокен: {'✅' if token_exists else '❌'}\nДиректория клонов: {'✅' if clones_dir_exists else '❌'}\nФайл процессов: {'✅' if processes_file_exists else '❌'}")
    except Exception as e:
        info_lines.append(f"❌ Ошибка проверки файлов: {e}")
    
    # 5. Режим работы
    info_lines.append(f"<b>Режим работы:</b> Polling")
    
    # 6. Клоны
    clones_list = get_clones_list()
    info_lines.append(f"<b>Активные клоны:</b>\n{clones_list}")
    
    # Отправляем информацию
    await message.answer("\n\n".join(info_lines), parse_mode="HTML")

@dp.message(Command("status"))
async def status(message: types.Message):
    """Статус системы"""
    if message.from_user.id != 291178183:  # Только для админа
        return
    
    clones_list = get_clones_list()
    
    await message.answer(
        f"🎉 <b>Основной бот работает!</b>\n\n"
        f"🔑 Токен: {BOT_TOKEN[:10]}...\n"
        f"🔧 Режим: <b>Polling</b>\n\n"
        f"📊 Статус клонов:\n{clones_list}\n\n"
        f"💡 <b>Рекомендация:</b>\n"
        f"Создайте хотя бы одного резервного клона.",
        parse_mode="HTML"
    )

@dp.message(Command("polling_info"))
async def polling_info_command(message: types.Message):
    """Информация о polling-режиме (для админа)"""
    if message.from_user.id != 291178183:
        await message.answer("❌ Доступ запрещён")
        return
    
    try:
        info_text = (
            f"🔄 <b>Информация о Polling-режиме:</b>\n\n"
            f"• Режим: <b>Long Polling</b>\n"
            f"• Сервер: Telegram Bot API\n"
            f"• Соединение: HTTPS\n"
            f"• Таймаут запроса: 30 секунд\n\n"
            f"<i>Преимущества polling-режима:</i>\n"
            f"• Не требует веб-сервера\n"
            f"• Не требует статического IP\n"
            f"• Не требует открытых портов\n"
            f"• Проще в настройке\n\n"
            f"<i>Недостатки:</i>\n"
            f"• Немного медленнее, чем webhook\n"
            f"• Больше нагрузка на сервер"
        )
        
        await message.answer(info_text, parse_mode="HTML")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
        logging.error(f"Polling info error: {e}")

@dp.message(Command("create_backup"))
async def create_backup(message: types.Message):
    """Создать резервного клона (команда)"""
    if message.from_user.id != 291178183:
        await message.answer("❌ Доступ запрещён")
        return
    
    await message.answer(
        "📝 <b>Создание резервного клона</b>\n\n"
        "Отправьте мне токен нового бота.\n\n"
        "Резервный клон:\n"
        "• Будет работать независимо\n"
        "• Сможет стать основным при вашем падении\n"
        "• Имеет полный функционал\n\n"
        "Пример токена:\n<code>1234567890:ABCdefGHIjklmNoPQRsTUVwxyZ-1234567890</code>",
        parse_mode="HTML"
    )
    waiting_for_token_main.add(message.from_user.id)

@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    action = callback.data
    logging.info(f"🔘 Основной бот: нажата кнопка '{action}'")

    user_id = callback.from_user.id
    
    if action == "menu":
        # ============ ДОБАВЛЕНА КАПЧА ПРИ ПЕРЕХОДЕ В МЕНЮ ============
        if requires_captcha(user_id):
            question, answer = generate_captcha()
            captcha_storage[user_id] = {
                "answer": answer,
                "timestamp": time.time()
            }
            
            # Отправляем капчу отдельным сообщением
            await bot.send_message(
                user_id,
                f"🔒 <b>Проверка безопасности</b>\n\n"
                f"Решите простой пример, чтобы открыть меню:\n"
                f"<b>{question} = ?</b>\n\n"
                f"Ответьте числом в чат.",
                parse_mode="HTML"
            )
            await callback.answer("Требуется проверка безопасности")
            return
        
        # Если капча не требуется, показываем меню
        await callback.message.edit_text("Меню", reply_markup=main_menu)
        await callback.answer()
        
    elif action == "back_to_welcome":
        text = get_message_by_id("welcome")
        extra_text = "\n\n🎉 <b>Вы основной бот!</b>\nСоздайте резервного клона на случай сбоев.\n\n<b>Режим работы: Polling</b>"
        await callback.message.edit_text(text + extra_text, reply_markup=menu_button, parse_mode="HTML")
        await callback.answer()
        
    elif action == "profile":
        # Проверяем, создавал ли этот бот клонов
        has_created = has_created_clones()
        status_emoji = "✅" if has_created else "⚪️"
        
        # Получаем шаблон из БД
        text = get_message_by_id("profile")
        
        # Добавляем статус с галочкой в конце текста
        full_text = f"{text}\n\nСтатус клона: {status_emoji}"
        
        await callback.message.edit_text(full_text, reply_markup=back_button)
        await callback.answer()
        
    elif action == "clone":
        text = get_message_by_id("clone")
        extra_text = "\n\n🎉 <b>Вы основной бот!</b>\nСоздайте резервного клона для надёжности."
        await callback.message.edit_text(text + extra_text, reply_markup=clone_menu, parse_mode="HTML")
        await callback.answer()
        
    elif action == "create_clone":
        # Проверка на спам перед созданием клона
        user_id = callback.from_user.id
        if requires_captcha(user_id):
            question, answer = generate_captcha()
            captcha_storage[user_id] = {
                "answer": answer,
                "timestamp": time.time()
            }
            
            await callback.message.edit_text(
                f"🔒 <b>Проверка безопасности</b>\n\n"
                f"Прежде чем создать клона, решите пример:\n"
                f"<b>{question} = ?</b>\n\n"
                f"Ответьте числом в чат.",
                parse_mode="HTML",
                reply_markup=create_bot_menu
            )
            await callback.answer("Требуется проверка безопасности")
            return
        
        text = get_message_by_id("guide_create_clone")
        full_text = text + "\n\n📝 <b>Создание резервного клона</b>\n\nОтправьте мне токен нового бота.\n\nПример токена:\n<code>1234567890:ABCdefGHIjklmNoPQRsTUVwxyZ-1234567890</code>"
        await callback.message.edit_text(full_text, reply_markup=create_bot_menu, parse_mode="HTML")
        waiting_for_token_main.add(callback.from_user.id)
        await callback.answer()
        
    elif action == "system_status":
        clones_list = get_clones_list()
        await callback.message.edit_text(
            f"🎉 <b>Основной бот работает!</b>\n\n"
            f"📊 Статус системы:\n{clones_list}\n\n"
            f"💡 Создайте резервного клона для надёжности.",
            reply_markup=back_button,
            parse_mode="HTML"
        )
        await callback.answer()
        
    elif action == "place_order":
        text = get_message_by_id("place_order")
        await callback.message.edit_text(text, reply_markup=back_button)
        await callback.answer()
        
    elif action == "manager":
        text = get_message_by_id("manager")
        await callback.message.edit_text(text, reply_markup=back_button)
        await callback.answer()

@dp.message()
async def message_handler(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    # Очистка старых данных
    cleanup_old_captchas()
    cleanup_old_activity()
    
    # Проверка на активную капчу
    if user_id in captcha_storage:
        expected_answer = captcha_storage[user_id]["answer"]
        
        try:
            user_answer = int(text)
            if user_answer == expected_answer:
                # Капча пройдена
                captcha_storage.pop(user_id)
                await message.answer("✅ Капча пройдена успешно! Теперь вы можете продолжить.")
                
                # Если пользователь ждал токена, продолжаем этот процесс
                if user_id in waiting_for_token_main:
                    await message.answer("Теперь отправьте токен бота.")
                else:
                    # Если пользователь решал капчу для входа в меню, показываем меню
                    await message.answer("Меню", reply_markup=main_menu)
                return
            else:
                # Неверный ответ - генерируем новую капчу
                question, answer = generate_captcha()
                captcha_storage[user_id] = {
                    "answer": answer,
                    "timestamp": time.time()
                }
                
                await message.answer(
                    f"❌ Неверный ответ!\n\n"
                    f"Попробуйте ещё раз:\n"
                    f"<b>{question} = ?</b>\n\n"
                    f"Ответьте числом.",
                    parse_mode="HTML"
                )
                return
        except ValueError:
            # Пользователь отправил не число
            await message.answer("❌ Пожалуйста, ответьте числом на пример капчи.")
            return
    
    # Проверка на спам (если нужно)
    if requires_captcha(user_id):
        question, answer = generate_captcha()
        captcha_storage[user_id] = {
            "answer": answer,
            "timestamp": time.time()
        }
        
        await message.answer(
            f"🔒 <b>Проверка безопасности</b>\n\n"
            f"Решите простой пример, чтобы продолжить:\n"
            f"<b>{question} = ?</b>\n\n"
            f"Ответьте числом.",
            parse_mode="HTML"
        )
        return
    
    # Обработка ожидания токена
    if user_id in waiting_for_token_main:
        token = text
        waiting_for_token_main.discard(user_id)
        
        if is_valid_token(token):
            # Показываем сообщение о начале создания клона
            await message.answer("🔄 Создаю резервного клона... Пожалуйста, подождите (это может занять до 60 секунд).", parse_mode="HTML")
            
            success, result = create_clone_via_manager(token)
            
            if success:
                await message.answer(
                    f"✅ <b>Резервный клон создан и запущен!</b>\n\n"
                    f"{result}\n\n"
                    f"Теперь этот бот:\n"
                    f"1. Работает независимо\n"
                    f"2. Может стать основным при вашем падении\n"
                    f"3. Имеет полный функционал\n\n"
                    f"Сохраните токен в надёжном месте!",
                    parse_mode="HTML",
                    reply_markup=main_menu
                )
                logging.info(f"✅ Создан резервный клон: {token[:10]}...")
            else:
                await message.answer(
                    f"❌ <b>Ошибка при создании клона:</b>\n\n"
                    f"<code>{result[:500]}</code>\n\n"
                    f"<b>Что проверить:</b>\n"
                    f"1. Корректность токена\n"
                    f"2. Наличие прав для создания процессов\n"
                    f"3. Доступ к директории /var/www/imlerih_bot/clones\n"
                    f"4. Доступ к /var/www/imlerih_bot/logs/ для создания логов",
                    parse_mode="HTML",
                    reply_markup=main_menu
                )
        else:
            await message.answer(
                "❌ <b>Неверный формат токена.</b>\n\n"
                "Токен должен иметь формат:\n"
                "<code>1234567890:ABCdefGHIjklmNoPQRsTUVwxyZ-1234567890</code>\n\n"
                "Где:\n"
                "• Первая часть: цифровой ID бота (8-11 цифр)\n"
                "• Вторая часть: секретный ключ (30-50 символов)\n"
                "• Разделитель: двоеточие",
                parse_mode="HTML",
                reply_markup=main_menu
            )

# =========== POLLING ЗАПУСК ===========

async def main():
    """Основная функция запуска в polling-режиме"""
    try:
        # Создаем необходимые директории если их нет
        os.makedirs("/var/www/imlerih_bot/clones", exist_ok=True)
        os.makedirs("/var/www/imlerih_bot/logs", exist_ok=True)
        
        logging.info("✅ Проверены/созданы необходимые директории")
        
        # Удаляем вебхук, если был установлен ранее
        await bot.delete_webhook(drop_pending_updates=True)
        logging.info("🗑️ Вебхук удален (если был)")
        
        logging.info("🔄 Запуск бота в polling-режиме...")
        logging.info(f"🔑 Токен: {BOT_TOKEN[:10]}...")
        logging.info("🔒 Защита от спама активирована")
        logging.info("💡 Отправьте /start в боте для проверки")
        
        # Запускаем polling
        await dp.start_polling(bot)
        
    except Exception as e:
        logging.error(f"❌ Критическая ошибка при запуске: {e}")
        raise
    finally:
        logging.info("⛔ Остановка бота...")
        await bot.session.close()

if __name__ == "__main__":
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("/var/www/imlerih_bot/logs/bot.log"),
            logging.StreamHandler()
        ]
    )
    
    # Запуск бота в polling-режиме
    asyncio.run(main())
