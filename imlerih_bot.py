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
import requests
from collections import defaultdict
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import psycopg2
from psycopg2.extras import DictCursor

# ==================== НАСТРОЙКИ ====================

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
    current_time = time.time()
    for user_id in list(user_activity.keys()):
        user_activity[user_id] = [t for t in user_activity[user_id] 
                                 if current_time - t < 60]
        if not user_activity[user_id]:
            user_activity.pop(user_id, None)

# ========== ФУНКЦИЯ ДЛЯ ГЕНЕРАЦИИ ССЫЛКИ НА КЛОНА ==========

def get_bot_username(token: str) -> str:
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("ok") and "result" in data:
                username = data["result"].get("username")
                if username:
                    logging.info(f"✅ Получен username бота: @{username}")
                    return username
                else:
                    logging.warning(f"⚠️ У бота нет username")
                    return None
            else:
                logging.error(f"❌ API вернуло ошибку: {data}")
                return None
        else:
            logging.error(f"❌ Ошибка HTTP {response.status_code}: {response.text}")
            return None
            
    except requests.exceptions.Timeout:
        logging.error("⏰ Таймаут при получении username бота")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Ошибка соединения при получении username: {e}")
        return None
    except Exception as e:
        logging.error(f"❌ Неожиданная ошибка при получении username: {e}")
        return None

def generate_clone_link(token: str) -> str:
    try:
        username = get_bot_username(token)
        
        if username:
            bot_link = f"https://t.me/{username}"
            logging.info(f"✅ Сгенерирована ссылка на бота: {bot_link}")
            return bot_link
        else:
            logging.warning("⚠️ Не удалось получить username бота для формирования ссылки")
            return None
            
    except Exception as e:
        logging.error(f"❌ Ошибка генерации ссылки на клона: {e}")
        return None

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

clone_success_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🔗 Открыть клона", callback_data="open_clone")],
    [InlineKeyboardButton(text="◀️ Назад", callback_data="menu")]
])

def get_db_connection():
    return psycopg2.connect(
        host="localhost",
        database="karantir_bot",
        user="karantir_user",
        password="karantir_pass"
    )

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

def is_valid_token(token: str) -> bool:
    """Проверка формата токена телеграм бота"""
    if not token or ':' not in token:
        return False
    
    parts = token.split(':')
    if len(parts) != 2:
        return False
    
    bot_id, bot_secret = parts
    
    if not bot_id.isdigit():
        return False
    
    if len(bot_secret) < 30 or len(bot_secret) > 50:
        return False
    
    return True

def save_owner_clone_info(clone_token: str):
    """Сохранение информации о том, что текущий бот создал клона"""
    try:
        if os.path.exists(OWNER_CLONES_FILE):
            with open(OWNER_CLONES_FILE, 'r') as f:
                owner_data = json.load(f)
        else:
            owner_data = {}
        
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

def save_backup_token(token: str):
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

def create_simple_clone(token: str) -> tuple[bool, str]:
    """Создание простого работающего клона"""
    try:
        logging.info(f"🔄 Начинаю создание простого клона с токеном: {token[:10]}...")
        
        # 1. Создаем уникальный ID для клона
        clone_id = f"clone_{int(time.time())}_{random.randint(1000, 9999)}"
        logging.info(f"✅ Создан ID клона: {clone_id}")
        
        # 2. Создаем простой, но полнофункциональный скрипт клона
        clone_script = f'''#!/usr/bin/env python3
"""
ПРОСТОЙ РЕЗЕРВНЫЙ КЛОН БОТА
ID: {clone_id}
Токен: {token[:10]}...
"""

import asyncio
import logging
import sys
import os
import time

# Настройка логирования
log_file = f"/var/www/imlerih_bot/logs/clone_{clone_id}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - CLONE_{clone_id} - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Импорты должны быть после настройки логирования
try:
    from aiogram import Bot, Dispatcher, types
    from aiogram.filters import Command
    from aiogram.fsm.storage.memory import MemoryStorage
    logger.info("✅ Библиотеки aiogram импортированы")
except ImportError as e:
    logger.error(f"❌ Ошибка импорта aiogram: {{e}}")
    sys.exit(1)

# Токен клона
BOT_TOKEN = "{token}"

# Создаем бота и диспетчер
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    try:
        logger.info(f"🎉 Клон получил /start от {{message.from_user.id}}")
        await message.answer(
            f"🤖 <b>Я резервный клон!</b>\\n"
            f"ID: <code>{clone_id}</code>\\n"
            f"Токен: <code>{{token[:10]}}...</code>\\n\\n"
            f"🔄 <b>Режим работы:</b> Polling\\n"
            f"✅ <b>Статус:</b> Активен\\n\\n"
            f"Отправьте /help для списка команд",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"❌ Ошибка в start_handler: {{e}}")

@dp.message(Command("help"))
async def help_handler(message: types.Message):
    await message.answer(
        f"🔧 <b>Команды клона {clone_id}:</b>\\n\\n"
        f"/start - информация о клоне\\n"
        f"/status - статус клона\\n"
        f"/ping - проверка работы\\n"
        f"/token - показать часть токена\\n\\n"
        f"🆔 <b>ID:</b> <code>{clone_id}</code>",
        parse_mode="HTML"
    )

@dp.message(Command("status"))
async def status_handler(message: types.Message):
    await message.answer(
        f"📊 <b>Статус клона:</b>\\n"
        f"🟢 <b>Работает</b>\\n"
        f"🆔 ID: <code>{clone_id}</code>\\n"
        f"⏰ Запущен: {time.ctime()}\\n"
        f"🔑 Токен: {{token[:10]}}...\\n"
        f"🤖 Пользователей: 1",
        parse_mode="HTML"
    )

@dp.message(Command("ping"))
async def ping_handler(message: types.Message):
    await message.answer(f"🏓 <b>Pong!</b>\\nКлон {clone_id} активен", parse_mode="HTML")

@dp.message(Command("token"))
async def token_handler(message: types.Message):
    await message.answer(
        f"🔑 <b>Токен клона:</b>\\n"
        f"<code>{{token[:20]}}...</code>\\n\\n"
        f"🆔 <b>ID клона:</b> <code>{clone_id}</code>",
        parse_mode="HTML"
    )

@dp.message()
async def echo_handler(message: types.Message):
    """Эхо-обработчик для тестирования"""
    if message.text:
        await message.answer(
            f"📨 <b>Получено сообщение:</b>\\n"
            f"{{message.text}}\\n\\n"
            f"🤖 <b>Ответ от клона {clone_id}</b>",
            parse_mode="HTML"
        )

async def main():
    """Основная функция клона"""
    try:
        logger.info(f"🚀 Запуск резервного клона {clone_id}...")
        logger.info(f"🔑 Токен: {{token[:10]}}...")
        logger.info(f"📁 Лог файл: {{log_file}}")
        
        # Удаляем вебхук если был
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("🗑️ Вебхук удален (если был)")
        
        # Запускаем polling
        logger.info("🔄 Запуск polling...")
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в клоне: {{e}}")
        raise
    finally:
        logger.info(f"⛔ Остановка клона {clone_id}")
        await bot.session.close()

if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info(f"🌟 ЗАПУСК КЛОНА БОТА")
    logger.info(f"🆔 ID: {clone_id}")
    logger.info(f"🔑 Токен: {token[:10]}...")
    logger.info(f"⏰ Время: {time.ctime()}")
    logger.info("=" * 50)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👆 Остановка по Ctrl+C")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка запуска: {{e}}")
        sys.exit(1)
'''
        
        # 3. Сохраняем скрипт клона
        script_filename = f"/var/www/imlerih_bot/clones/bot_{clone_id}.py"
        
        # Создаем директорию если её нет
        os.makedirs("/var/www/imlerih_bot/clones", exist_ok=True)
        
        with open(script_filename, 'w') as f:
            f.write(clone_script)
        
        # 4. Даем права на выполнение
        os.chmod(script_filename, 0o755)
        logging.info(f"✅ Создан скрипт клона: {script_filename}")
        
        # 5. Запускаем клон как фоновый процесс с nohup
        log_file = f"/var/www/imlerih_bot/logs/clone_{clone_id}.log"
        
        # Используем nohup для запуска в фоне
        cmd = f"cd /var/www/imlerih_bot && nohup python3 {script_filename} > {log_file} 2>&1 & echo $!"
        
        logging.info(f"🚀 Запускаю команду: {cmd}")
        
        # Запускаем процесс
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0 and result.stdout.strip():
            pid = int(result.stdout.strip())
            logging.info(f"✅ Клон {clone_id} запущен с PID: {pid}")
            
            # Сохраняем информацию о процессе
            save_clone_process_info(clone_id, pid, token)
            
            # 6. Ждем и проверяем лог на ошибки
            time.sleep(3)
            
            # Проверяем лог файл
            log_content = ""
            if os.path.exists(log_file):
                with open(log_file, 'r') as f:
                    log_content = f.read(2000)
                logging.info(f"📄 Содержимое лога ({len(log_content)} символов): {log_content[:500]}...")
            
            # 7. Проверяем, жив ли процесс
            try:
                os.kill(pid, 0)
                process_running = True
                logging.info(f"✅ Процесс {pid} жив")
            except OSError:
                process_running = False
                logging.warning(f"⚠️ Процесс {pid} не запущен")
            
            # 8. Сохраняем токен
            save_backup_token(token)
            
            # 9. Генерируем ссылку на бота - теперь через API
            bot_link = generate_clone_link(token)
            
            # 10. Проверяем наличие ошибок в логе
            has_errors = "ImportError" in log_content or "ModuleNotFoundError" in log_content
            
            if process_running and not has_errors:
                # УПРОЩЕННОЕ СООБЩЕНИЕ ТОЛЬКО СО ССЫЛКОЙ
                message_text = f"✅ Резервный клон создан и запущен!"
                
                if bot_link:
                    # Создаем кнопку со ссылкой И кнопку Назад
                    open_clone_button = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="🔗 Открыть клона", url=bot_link)],
                            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu")]
                        ]
                    )
                    return True, (message_text, open_clone_button)
                else:
                    # Если не удалось получить username, все равно возвращаем успех с кнопкой Назад
                    open_clone_button = InlineKeyboardMarkup(
                        inline_keyboard=[[
                            InlineKeyboardButton(text="◀️ Назад в меню", callback_data="menu")
                        ]]
                    )
                    return True, (message_text, open_clone_button)
                    
            elif has_errors:
                return False, (
                    f"⚠️ <b>Клон создан, но есть ошибки импорта</b>\n\n"
                    f"<b>Ошибка:</b> Проблема с импортом aiogram\n"
                    f"<b>Решение:</b> Установите aiogram в системе\n"
                    f"<code>pip install aiogram</code>"
                )
            else:
                return False, (
                    f"⚠️ <b>Клон создан, но не запустился</b>\n\n"
                    f"<b>Проверьте:</b>\n"
                    f"1. Лог файл на наличие ошибок\n"
                    f"2. Доступность Python3 и aiogram\n"
                    f"3. Корректность токена бота"
                )
        else:
            error_msg = result.stderr if result.stderr else result.stdout
            logging.error(f"❌ Ошибка запуска клона: {error_msg}")
            return False, f"❌ Ошибка запуска клона: {error_msg}"
        
    except subprocess.TimeoutExpired:
        logging.error("⏰ Таймаут при запуске клона")
        return False, "Таймаут при запуске клона (превышено 30 секунд)"
    except Exception as e:
        logging.error(f"❌ Исключение при создании клона: {e}")
        return False, f"❌ Исключение при создании клона: {str(e)}"

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
        output_lines = ["📋 <b>Список клонов:</b>"]
        
        # Проверяем файл с процессами
        if os.path.exists(CLONE_PROCESSES_FILE):
            with open(CLONE_PROCESSES_FILE, 'r') as f:
                processes = json.load(f)
            
            if not processes:
                output_lines.append("\n📭 Активных клонов нет")
            else:
                for clone_id, info in processes.items():
                    pid = info.get("pid", 0)
                    token_preview = info.get("token", "unknown")
                    start_time = info.get("start_time", 0)
                    
                    # Проверяем, жив ли процесс
                    try:
                        os.kill(pid, 0)
                        process_status = "🟢 Запущен"
                        uptime = int(time.time() - start_time)
                        uptime_str = f"{uptime // 3600}ч {(uptime % 3600) // 60}м"
                    except OSError:
                        process_status = "🔴 Остановлен"
                        uptime_str = "неактивен"
                    
                    output_lines.append(f"\n• <b>{clone_id}</b>")
                    output_lines.append(f"  PID: {pid}, Статус: {process_status}")
                    output_lines.append(f"  Токен: {token_preview}")
                    output_lines.append(f"  Время работы: {uptime_str}")
        else:
            output_lines.append("\n📭 Файл процессов не найден")
        
        # Проверяем логи клонов
        try:
            logs_dir = "/var/www/imlerih_bot/logs"
            if os.path.exists(logs_dir):
                clone_logs = [f for f in os.listdir(logs_dir) if f.startswith("clone_")]
                if clone_logs:
                    output_lines.append(f"\n📁 <b>Лог файлы ({len(clone_logs)}):</b>")
                    for log in sorted(clone_logs)[-5:]:  # Последние 5 логов
                        log_path = os.path.join(logs_dir, log)
                        size = os.path.getsize(log_path) if os.path.exists(log_path) else 0
                        output_lines.append(f"  {log} ({size} байт)")
        except Exception as e:
            output_lines.append(f"\n⚠️ Ошибка проверки логов: {e}")
        
        return "\n".join(output_lines)
        
    except Exception as e:
        return f"❌ Ошибка получения списка: {str(e)}"

# Глобальное состояние
waiting_for_token_main = set()

# ============ ОБРАБОТЧИКИ ОСНОВНОГО БОТА ============

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    logging.info(f"🎉 Основной бот: /start от {message.from_user.id}")
    
    # Очищаем старые капчи при запуске
    cleanup_old_captchas()
    cleanup_old_activity()
    
    text = get_message_by_id("welcome")
    extra_text = "\n\n🎉 <b>Вы основной бот!</b>\nСоздайте резервного клона на случай сбоев.\n\n"
    
    await message.answer(text + extra_text, reply_markup=menu_button, parse_mode="HTML")

@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    action = callback.data
    logging.info(f"🔘 Основной бот: нажата кнопка '{action}'")

    user_id = callback.from_user.id
    
    if action == "menu":
        # ============ ДОБАВЛЕНА КАПЧА ПРИ ПЕРЕХОДЕ В МЕНУ ============
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
        extra_text = "\n\n🎉 <b>Вы основной бот!</b>\nСоздайте резервного клона на случай сбоев.\n\n"
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
    
    # ДОБАВЬТЕ ЭТУ СТРОКУ ДЛЯ ОТЛАДКИ
    print(f"📨 Получено сообщение от {user_id}: {text[:50]}...")
    
    # Очистка старых данных
    cleanup_old_captchas()
    cleanup_old_activity()
    
    # Проверка на активную капчу
    if user_id in captcha_storage:
        print(f"🔐 Пользователь {user_id} решает капчу...")  # ДОБАВЬТЕ
        expected_answer = captcha_storage[user_id]["answer"]
        
        try:
            user_answer = int(text)
            if user_answer == expected_answer:
                # Капча пройдена
                captcha_storage.pop(user_id)
                await message.answer("✅ Капча пройдена успешно! Теперь вы можете продолжить.")
                
                # Если пользователь ждал токена, продолжаем этот процесс
                if user_id in waiting_for_token_main:
                    print(f"🔑 Пользователь {user_id} прошел капчу и ждет токен")  # ДОБАВЬТЕ
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
        print(f"🚨 Пользователь {user_id} требует капчу (спам?)")  # ДОБАВЬТЕ
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
        print(f"🎯 Пользователь {user_id} отправил токен для клона: {text[:20]}...")  # ДОБАВЬТЕ
        token = text
        waiting_for_token_main.discard(user_id)
        
        if is_valid_token(token):
            print(f"✅ Токен валиден, начинаю создание клона...")  # ДОБАВЬТЕ
            # Показываем сообщение о начале создания клона
            await message.answer("🔄 Создаю резервного клона... Пожалуйста, подождите (это может занять до 60 секунд).", parse_mode="HTML")
            
            success, result = create_simple_clone(token)
            
            if success:
                print(f"✅ УСПЕХ: {result}")  # Уже есть
                if isinstance(result, tuple) and len(result) == 2:
                    # Новый формат с кнопкой
                    message_text, reply_markup = result
                    await message.answer(
                        message_text,
                        reply_markup=reply_markup
                    )
                else:
                    # Старый формат для обратной совместимости
                    await message.answer(
                        f"✅ Резервный клон создан и запущен!\n\n{result}",
                        parse_mode="HTML",
                        reply_markup=main_menu
                    )
                logging.info(f"✅ Создан резервный клон: {token[:10]}...")
            else:
                print(f"❌ ОШИБКА создания клона: {result}")  # ДОБАВЬТЕ
                await message.answer(
                    f"❌ <b>Ошибка при создании клона:</b>\n\n"
                    f"{result}\n\n"
                    f"<b>Что проверить:</b>\n"
                    f"1. Корректность токена\n"
                    f"2. Наличие прав для создания процессов\n"
                    f"3. Доступ к директории /var/www/imlerih_bot/clones\n"
                    f"4. Установлен ли aiogram в системе",
                    parse_mode="HTML",
                    reply_markup=main_menu
                )
        else:
            print(f"❌ Невалидный токен от пользователя {user_id}")  # ДОБАВЬТЕ
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