#!/usr/bin/env python3
# /var/www/imlerih_bot/imlerih_bot.py - ИСПРАВЛЕННАЯ ВЕРСИЯ

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

import os
import sys
import socket

def check_duplicate_services():
    """Проверяет, не запущены ли дублирующие службы"""
    service_files = [
        '/etc/systemd/system/imlerih_bot_screen.service',
        '/lib/systemd/system/imlerih_bot_screen.service',
        '/etc/systemd/system/imlerih_bot@.service',
        '/lib/systemd/system/imlerih_bot@.service'
    ]
    
    for service_file in service_files:
        if os.path.exists(service_file):
            print(f"⚠️ ВНИМАНИЕ: Найдена лишняя служба: {service_file}")
            print("   Удалите ее командой:")
            print(f"   sudo rm -f {service_file}")
            print("   sudo systemctl daemon-reload")
    
    # Проверяем, сколько процессов бота запущено
    import subprocess
    result = subprocess.run(['pgrep', '-f', 'imlerih_bot.py'], 
                           capture_output=True, text=True)
    pids = result.stdout.strip().split()
    
    current_pid = os.getpid()
    other_pids = [pid for pid in pids if pid != str(current_pid)]
    
    if len(other_pids) > 0:
        print(f"❌ ОШИБКА: Найдены другие процессы бота: {other_pids}")
        print("   Остановите их командой:")
        print("   sudo systemctl stop imlerih_bot")
        print("   sudo pkill -f 'imlerih_bot'")
        print("   Затем запустите заново:")
        print("   sudo systemctl start imlerih_bot")
        sys.exit(1)

# Вызываем проверку
check_duplicate_services()

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
OWNER_CLONES_FILE = "/var/www/imlerih_bot/owner_clones.json"
CLONE_PROCESSES_FILE = "/var/www/imlerih_bot/clone_processes.json"

# ========= ЗАЩИТА ОТ СПАМА ========
captcha_storage = {}
user_activity = defaultdict(list)
CAPTCHA_LIFETIME = 300
SPAM_TIME_WINDOW = 10
SPAM_MESSAGE_LIMIT = 5

def generate_captcha() -> tuple[str, int]:
    a = random.randint(1, 10)
    b = random.randint(1, 10)
    operation = random.choice(['+', '-', '*'])
    
    if operation == '+':
        answer = a + b
        text = f"{a} + {b}"
    elif operation == '-':
        if a < b:
            a, b = b, a
        answer = a - b
        text = f"{a} - {b}"
    else:
        a = random.randint(1, 5)
        b = random.randint(1, 5)
        answer = a * b
        text = f"{a} × {b}"
    
    return text, answer

def requires_captcha(user_id: int) -> bool:
    if user_id in captcha_storage:
        return True
    
    current_time = time.time()
    user_activity[user_id] = [t for t in user_activity[user_id] 
                             if current_time - t < SPAM_TIME_WINDOW]
    user_activity[user_id].append(current_time)
    
    if len(user_activity[user_id]) > SPAM_MESSAGE_LIMIT:
        logging.warning(f"⚠️ Обнаружен возможный спам от пользователя {user_id}")
        return True
    
    return False

def cleanup_old_captchas():
    current_time = time.time()
    expired_users = []
    
    for user_id, captcha_data in captcha_storage.items():
        if current_time - captcha_data["timestamp"] > CAPTCHA_LIFETIME:
            expired_users.append(user_id)
    
    for user_id in expired_users:
        captcha_storage.pop(user_id, None)

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
                content = f.read().strip()
                if content:
                    tokens = json.loads(content)
        
        if token not in tokens:
            tokens.append(token)
            with open(BACKUP_TOKENS_FILE, 'w') as f:
                json.dump(tokens, f, indent=2)
            logging.info(f"✅ Токен сохранен в резервные: {token[:10]}...")
            save_owner_clone_info(token)
            return True
    except Exception as e:
        logging.error(f"❌ Ошибка сохранения токена: {e}")
        try:
            with open(BACKUP_TOKENS_FILE, 'w') as f:
                json.dump([token], f, indent=2)
            logging.info(f"✅ Создан новый файл с токеном: {token[:10]}...")
            return True
        except:
            return False
    return False

def save_clone_process_info(clone_id: str, pid: int, token: str):
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
    """Создание простого работающего клона - УПРОЩЕННАЯ РАБОЧАЯ ВЕРСИЯ"""
    try:
        logging.info(f"🔄 Начинаю создание простого клона с токеном: {token[:10]}...")
        
        # 1. Создаем уникальный ID для клона
        clone_id = f"clone_{int(time.time())}_{random.randint(1000, 9999)}"
        logging.info(f"✅ Создан ID клона: {clone_id}")
        
        # 2. Создаем СУПЕР ПРОСТОЙ скрипт БЕЗ сложных f-строк
        # Используем format() вместо f-строк для избежания ошибок
        
        script_template = '''#!/usr/bin/env python3
"""
ПРОСТОЙ РЕЗЕРВНЫЙ КЛОН БОТА
ID: {clone_id}
"""

import asyncio
import os
import sys

# Отключаем apport
os.environ['APPORT_DISABLE'] = '1'

# Токен клона
BOT_TOKEN = "{token}"

# ID клона
CLONE_ID = "{clone_id}"

print("=" * 50)
print("🌟 ЗАПУСК КЛОНА БОТА")
print("🆔 ID: " + CLONE_ID)
print("🔑 Токен: " + BOT_TOKEN[:10] + "...")
print("=" * 50)

try:
    from aiogram import Bot, Dispatcher, types
    from aiogram.filters import Command
    from aiogram.fsm.storage.memory import MemoryStorage
    print("✅ aiogram импортирован успешно")
except ImportError as e:
    print("❌ Ошибка импорта aiogram: " + str(e))
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    print("🎉 Клон получил /start от " + str(message.from_user.id))
    await message.answer(
        "🤖 <b>Я резервный клон!</b>\\n"
        "ID: <code>" + CLONE_ID + "</code>\\n"
        "Токен: <code>" + BOT_TOKEN[:10] + "...</code>\\n\\n"
        "Отправьте любое сообщение для теста.",
        parse_mode="HTML"
    )

@dp.message(Command("ping"))
async def ping_cmd(message: types.Message):
    await message.answer("🏓 Pong! Клон работает")

@dp.message()
async def echo(message: types.Message):
    if message.text:
        await message.answer("📨 Echo: " + message.text)

async def main():
    print("🔄 Запуск polling для клона " + CLONE_ID + "...")
    await bot.delete_webhook(drop_pending_updates=True)
    print("✅ Вебхук удален")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("👆 Остановка по Ctrl+C")
    except Exception as e:
        print("💥 Критическая ошибка запуска: " + str(e))
        import traceback
        traceback.print_exc()
'''
        
        # 3. Заполняем шаблон
        script_content = script_template.format(
            clone_id=clone_id,
            token=token
        )
        
        # 4. Сохраняем скрипт
        script_filename = f"/var/www/imlerih_bot/clones/bot_{clone_id}.py"
        os.makedirs("/var/www/imlerih_bot/clones", exist_ok=True)
        
        with open(script_filename, 'w') as f:
            f.write(script_content)
        
        os.chmod(script_filename, 0o755)
        logging.info(f"✅ Создан скрипт клона: {script_filename}")
        
        # 5. ПРОСТАЯ проверка - смотрим содержимое файла
        logging.info("🔍 Проверяю созданный скрипт...")
        with open(script_filename, 'r') as f:
            first_lines = ''.join(f.readlines()[:10])
            logging.info(f"📄 Первые 10 строк скрипта:\\n{first_lines}")
        
        # Проверяем что переменные подставились
        with open(script_filename, 'r') as f:
            content = f.read()
            if clone_id not in content:
                logging.error(f"❌ clone_id '{clone_id}' не найден в скрипте!")
                return False, f"❌ Ошибка: clone_id не подставился в скрипт"
            if token not in content:
                logging.error(f"❌ token не найден в скрипте!")
                return False, f"❌ Ошибка: token не подставился в скрипт"
        
        # 6. Запускаем клон
        log_file = f"/var/www/imlerih_bot/logs/clone_{clone_id}.log"
        os.makedirs("/var/www/imlerih_bot/logs", exist_ok=True)
        
        # Очищаем лог
        with open(log_file, 'w') as f:
            f.write(f"=== ЗАПУСК КЛОНА {clone_id} ===\\n")
        
        # Команда для запуска
        cmd = ["python3", script_filename]
        logging.info(f"🚀 Запускаю команду: {' '.join(cmd)}")
        
        # Запускаем процесс
        env = os.environ.copy()
        env['APPORT_DISABLE'] = '1'
        
        process = subprocess.Popen(
            cmd,
            stdout=open(log_file, 'a'),
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
            cwd="/var/www/imlerih_bot",
            env=env
        )
        
        pid = process.pid
        logging.info(f"✅ Клон {clone_id} запущен с PID: {pid}")
        save_clone_process_info(clone_id, pid, token)
        
        # 7. Ждем и проверяем
        time.sleep(10)  # Даем время на запуск
        
        # 8. Проверяем процесс
        try:
            os.kill(pid, 0)
            process_running = True
            logging.info(f"✅ Процесс {pid} жив")
        except OSError:
            process_running = False
            logging.warning(f"⚠️ Процесс {pid} не запущен")
        
        # 9. Проверяем лог
        log_content = ""
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                log_content = f.read(2000)
            
            logging.info(f"📄 Лог клона (первые 500 символов):\\n{log_content[:500]}")
            
            # Проверяем на ошибки
            if "ImportError" in log_content:
                return False, f"❌ Ошибка импорта aiogram в клоне"
            elif "NameError" in log_content or "not defined" in log_content:
                # Найдем конкретную ошибку
                lines = log_content.split('\\n')
                for line in lines:
                    if "NameError" in line or "not defined" in line:
                        return False, f"❌ Ошибка в коде клона: {line[:100]}"
                return False, f"❌ Ошибка NameError в клоне"
            elif "SyntaxError" in log_content:
                return False, f"❌ Синтаксическая ошибка в скрипте клона"
        
        # 10. Проверяем API бота
        api_check_passed = False
        api_username = "нет"
        try:
            import requests
            check_url = f"https://api.telegram.org/bot{token}/getMe"
            response = requests.get(check_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    api_check_passed = True
                    api_username = data['result'].get('username', 'нет')
                    logging.info(f"✅ API бота отвечает, username: @{api_username}")
        except Exception as e:
            logging.error(f"❌ Ошибка проверки API: {e}")
        
        # 11. Сохраняем токен
        save_backup_token(token)
        
        # 12. Генерируем ссылку
        bot_link = generate_clone_link(token)
        
        if process_running and api_check_passed:
            message_text = f"✅ Клон создан и запущен!\\n🆔 ID: {clone_id}\\n👤 @{api_username}\\n🔑 {token[:10]}...\\n📊 PID: {pid}"
            
            if bot_link:
                markup = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🔗 Открыть клона", url=bot_link)],
                        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu")]
                    ]
                )
            else:
                markup = InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="menu")]]
                )
            
            return True, (message_text, markup)
        else:
            # Читаем последние строки лога для диагностики
            error_info = ""
            if os.path.exists(log_file):
                with open(log_file, 'r') as f:
                    lines = f.readlines()
                    if lines:
                        last_lines = lines[-5:]  # Последние 5 строк
                        error_info = "\\n📄 Последние строки лога:\\n" + "".join(last_lines)
            
            return False, (
                f"⚠️ <b>Проблемы с созданием клона</b>\\n"
                f"🆔 ID: {clone_id}\\n"
                f"📊 Статус процесса: {'🟢 Запущен' if process_running else '🔴 Не запущен'}\\n"
                f"🌐 API: {'🟢 Отвечает' if api_check_passed else '🔴 Не отвечает'}"
                f"{error_info}"
            )
        
    except Exception as e:
        logging.error(f"❌ Исключение при создании клона: {e}")
        import traceback
        traceback.print_exc()
        return False, f"❌ Системная ошибка: {str(e)}"

def has_created_clones() -> bool:
    try:
        if os.path.exists(OWNER_CLONES_FILE):
            with open(OWNER_CLONES_FILE, 'r') as f:
                owner_data = json.load(f)
            owner_token = BOT_TOKEN
            if owner_token in owner_data:
                clones = owner_data[owner_token]
                return len(clones) > 0
        return False
    except Exception as e:
        logging.error(f"❌ Ошибка проверки созданных клонов: {e}")
        return False

def has_clones() -> bool:
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
    try:
        output_lines = ["📋 <b>Список клонов:</b>"]
        
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
        
        return "\n".join(output_lines)
        
    except Exception as e:
        return f"❌ Ошибка получения списка: {str(e)}"

# Глобальное состояние
waiting_for_token_main = set()

# ============ ОБРАБОТЧИКИ ОСНОВНОГО БОТА ============

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    logging.info(f"🎉 Основной бот: /start от {message.from_user.id}")
    
    cleanup_old_captchas()
    cleanup_old_activity()
    
    text = get_message_by_id("welcome")
    extra_text = "\n\n🎉 <b>Вы основной бот!</b>\nСоздайте резервного клона на случай сбоев.\n\n"
    
    await message.answer(text + extra_text, reply_markup=menu_button, parse_mode="HTML")

@dp.message(Command("debug_clone"))
async def debug_clone_handler(message: types.Message):
    """Отладка создания клона"""
    # Создаем простой тестовый скрипт
    clone_id = f"debug_{int(time.time())}"
    token = "1234567890:AAHsPk6k9Jp7m8YgZLvNn8_-Jx2qzx8X3Hk"  # Тестовый токен
    
    # Простой скрипт для проверки
    test_script = f'''#!/usr/bin/env python3
BOT_TOKEN = "{token}"
CLONE_ID = "{clone_id}"

print("Тест 1: Переменные определены")
print("BOT_TOKEN:", BOT_TOKEN[:10] + "...")
print("CLONE_ID:", CLONE_ID)

# Проверка aiogram
try:
    from aiogram import Bot
    print("Тест 2: aiogram импортирован")
    
    bot = Bot(token=BOT_TOKEN)
    print("Тест 3: Бот создан")
    
    print("✅ Все тесты пройдены!")
except Exception as e:
    print("❌ Ошибка:", str(e))
'''
    
    # Сохраняем
    script_file = f"/var/www/imlerih_bot/debug_{clone_id}.py"
    with open(script_file, 'w') as f:
        f.write(test_script)
    
    os.chmod(script_file, 0o755)
    
    # Запускаем
    result = subprocess.run(["python3", script_file], capture_output=True, text=True)
    
    response_text = f"🔄 Тест создания скрипта\\n🆔 ID: {clone_id}\\n\\n"
    
    if result.returncode == 0:
        response_text += f"✅ УСПЕХ:\\n{result.stdout}"
    else:
        response_text += f"❌ ОШИБКА:\\n{result.stderr}"
    
    # Показываем содержимое файла
    with open(script_file, 'r') as f:
        file_content = f.read(500)
        response_text += f"\\n\\n📄 Содержимое файла:\\n<code>{file_content}</code>"
    
    await message.answer(response_text, parse_mode="HTML")
    
    # Удаляем тестовый файл
    os.remove(script_file)

@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    action = callback.data
    logging.info(f"🔘 Основной бот: нажата кнопка '{action}'")

    user_id = callback.from_user.id
    
    if action == "menu":
        if requires_captcha(user_id):
            question, answer = generate_captcha()
            captcha_storage[user_id] = {
                "answer": answer,
                "timestamp": time.time()
            }
            
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
        
        await callback.message.edit_text("Меню", reply_markup=main_menu)
        await callback.answer()
        
    elif action == "back_to_welcome":
        text = get_message_by_id("welcome")
        extra_text = "\n\n🎉 <b>Вы основной бот!</b>\nСоздайте резервного клона на случай сбоев.\n\n"
        await callback.message.edit_text(text + extra_text, reply_markup=menu_button, parse_mode="HTML")
        await callback.answer()
        
    elif action == "profile":
        has_created = has_created_clones()
        status_emoji = "✅" if has_created else "⚪️"
        
        text = get_message_by_id("profile")
        full_text = f"{text}\n\nСтатус клона: {status_emoji}"
        
        await callback.message.edit_text(full_text, reply_markup=back_button)
        await callback.answer()
        
    elif action == "clone":
        text = get_message_by_id("clone")
        extra_text = "\n\n🎉 <b>Вы основной бот!</b>\nСоздайте резервного клона для надёжности."
        await callback.message.edit_text(text + extra_text, reply_markup=clone_menu, parse_mode="HTML")
        await callback.answer()
        
    elif action == "create_clone":
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
    
    cleanup_old_captchas()
    cleanup_old_activity()
    
    if user_id in captcha_storage:
        expected_answer = captcha_storage[user_id]["answer"]
        
        try:
            user_answer = int(text)
            if user_answer == expected_answer:
                captcha_storage.pop(user_id)
                await message.answer("✅ Капча пройдена успешно! Теперь вы можете продолжить.")
                
                if user_id in waiting_for_token_main:
                    await message.answer("Теперь отправьте токен бота.")
                else:
                    await message.answer("Меню", reply_markup=main_menu)
                return
            else:
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
            await message.answer("❌ Пожалуйста, ответьте числом на пример капчи.")
            return
    
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
    
    if user_id in waiting_for_token_main:
        token = text
        waiting_for_token_main.discard(user_id)
        
        if is_valid_token(token):
            await message.answer("🔄 Создаю резервного клона... Пожалуйста, подождите (это может занять до 60 секунд).", parse_mode="HTML")
            
            success, result = create_simple_clone(token)
            
            if success:
                if isinstance(result, tuple) and len(result) == 2:
                    message_text, reply_markup = result
                    await message.answer(
                        message_text,
                        reply_markup=reply_markup
                    )
                else:
                    await message.answer(
                        f"✅ Резервный клон создан и запущен!\n\n{result}",
                        parse_mode="HTML",
                        reply_markup=main_menu
                    )
                logging.info(f"✅ Создан резервный клон: {token[:10]}...")
            else:
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
    try:
        os.makedirs("/var/www/imlerih_bot/clones", exist_ok=True)
        os.makedirs("/var/www/imlerih_bot/logs", exist_ok=True)
        
        logging.info("✅ Проверены/созданы необходимые директории")
        
        await bot.delete_webhook(drop_pending_updates=True)
        logging.info("🗑️ Вебхук удален (если был)")
        
        logging.info("🔄 Запуск бота в polling-режиме...")
        logging.info(f"🔑 Токен: {BOT_TOKEN[:10]}...")
        logging.info("🔒 Защита от спама активирована")
        logging.info("💡 Отправьте /start в боте для проверки")
        
        await dp.start_polling(bot)
        
    except Exception as e:
        logging.error(f"❌ Критическая ошибка при запуске: {e}")
        raise
    finally:
        logging.info("⛔ Остановка бота...")
        await bot.session.close()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("/var/www/imlerih_bot/logs/bot.log"),
            logging.StreamHandler()
        ]
    )
    
    asyncio.run(main())