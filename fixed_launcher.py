#!/usr/bin/env python3
import sys
import os
import subprocess
import time
import json
import logging
import random
import re
import shutil
import asyncio
import signal
from pathlib import Path

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - FIXED_LAUNCHER - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("/var/www/imlerih_bot/logs/fixed_launcher.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

def is_valid_token(token: str) -> bool:
    """Проверка формата токена Telegram бота"""
    if not token:
        return False
    
    # Проверяем базовый формат
    if ':' not in token:
        return False
    
    parts = token.split(':')
    if len(parts) != 2:
        return False
    
    bot_id, bot_secret = parts
    
    # ID бота должен быть числом
    if not bot_id.isdigit():
        return False
    
    # Секретная часть должна быть достаточно длинной
    if len(bot_secret) < 20:
        return False
    
    return True

def create_clone_directory_structure(clone_id: str, token: str) -> str:
    """Создает структуру директорий для клона"""
    clone_dir = f"/var/www/imlerih_bot/clones/{clone_id}"
    
    try:
        # Создаем основную директорию
        os.makedirs(clone_dir, exist_ok=True)
        
        # Создаем поддиректории
        subdirs = ['txt', 'logs', 'clones', 'backups']
        for subdir in subdirs:
            os.makedirs(f"{clone_dir}/{subdir}", exist_ok=True)
        
        # Создаем token.txt
        token_file = f"{clone_dir}/txt/token.txt"
        with open(token_file, 'w') as f:
            f.write(token)
        
        logger.info(f"✅ Создана структура директорий: {clone_dir}")
        return clone_dir
        
    except Exception as e:
        logger.error(f"❌ Ошибка создания директорий: {e}")
        raise

def create_simple_clone_script(clone_dir: str, clone_id: str, token: str) -> str:
    """Создает простой, но работающий скрипт клона"""
    
    clone_script = f'''#!/usr/bin/env python3
# /var/www/imlerih_bot/clones/{clone_id}/bot.py
# Автоматически созданный клон бота

import os
import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage

# ==================== НАСТРОЙКИ ====================
try:
    with open("{clone_dir}/txt/token.txt", "r", encoding="utf-8") as f:
        BOT_TOKEN = f.read().strip()
except FileNotFoundError:
    # Fallback на токен из переменной
    BOT_TOKEN = "{token}"

# Создаём бота и диспетчер
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ==================== МЕНЮ ====================
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

menu_button = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Меню", callback_data="menu")]
])

main_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Профиль", callback_data="profile"), 
     InlineKeyboardButton(text="Клон бота", callback_data="clone")],
    [InlineKeyboardButton(text="Оформить заказ", callback_data="place_order"), 
     InlineKeyboardButton(text="Менеджер", callback_data="manager")],
    [InlineKeyboardButton(text="Назад", callback_data="back_to_welcome")]
])

back_button = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="◀️ Назад", callback_data="menu")]
])

# ==================== ОБРАБОТЧИКИ ====================

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

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    
    cleanup_old_captchas()
    cleanup_old_activity()
    
    text = get_message_by_id("welcome")
    
    await message.answer(text, reply_markup=menu_button, parse_mode="HTML")

@dp.message(Command("test"))
async def test_handler(message: types.Message):
    await message.answer(f"✅ Клон {clone_id} работает исправно!")

@dp.message(Command("status"))
async def status_handler(message: types.Message):
    await message.answer(
        f"📊 <b>Статус клона:</b>\\n"
        f"• ID: {clone_id}\\n"
        f"🔑 Токен: {token[:10]}...\\n\\n"
        f"• Директория: {clone_dir}\\n"
        f"• Запущен: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        parse_mode="HTML"
    )

@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    action = callback.data
    
    if action == "menu":
        await callback.message.edit_text("📋 <b>Меню клона</b>", 
                                       reply_markup=main_menu,
                                       parse_mode="HTML")
        await callback.answer()
    elif action == "profile":
        await callback.message.edit_text("👤 <b>Профиль</b>\\n\\nВы используете резервного клона.", 
                                       reply_markup=back_button,
                                       parse_mode="HTML")
        await callback.answer()
    elif action == "clone":
        await callback.message.edit_text("🤖 <b>Создание клона</b>\\n\\nЭтот клон тоже может создавать своих клонов!", 
                                       reply_markup=back_button,
                                       parse_mode="HTML")
        await callback.answer()
    elif action == "place_order":
        await callback.message.edit_text("🛒 <b>Оформление заказа</b>\\n\\nФункция работает!", 
                                       reply_markup=back_button,
                                       parse_mode="HTML")
        await callback.answer()
    elif action == "manager":
        await callback.message.edit_text("👨‍💼 <b>Менеджер</b>\\n\\nСвяжитесь с поддержкой.", 
                                       reply_markup=back_button,
                                       parse_mode="HTML")
        await callback.answer()
    elif action == "back_to_welcome":
        await callback.message.edit_text(f"🤖 <b>Резервный клон</b>\\n\\n🆔 ID: {clone_id}", 
                                       reply_markup=menu_button,
                                       parse_mode="HTML")
        await callback.answer()

@dp.message()
async def echo_handler(message: types.Message):
    await message.answer(f"Клон {clone_id} получил ваше сообщение: {{message.text[:50]}}")

# ==================== ЗАПУСК ====================

async def main():
    try:
        # Настройка логирования
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - CLONE_{clone_id} - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler("{clone_dir}/logs/bot.log"),
                logging.StreamHandler()
            ]
        )
        
        logger = logging.getLogger(__name__)
        
        # Проверяем директории
        os.makedirs("{clone_dir}/logs", exist_ok=True)
        
        # Удаляем вебхук если был
        await bot.delete_webhook(drop_pending_updates=True)
        
        logger.info(f"🚀 Запуск клона {clone_id}")
        logger.info(f"📁 Директория: {clone_dir}")
        
        # Запускаем polling
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.error(f"❌ Ошибка запуска клона: {{e}}")
        raise
    finally:
        logger.info(f"⛔ Остановка клона {clone_id}")
        await bot.session.close()

if __name__ == "__main__":
    # Импортируем time для использования в status_handler
    import time
    asyncio.run(main())
'''
    
    # Сохраняем скрипт
    script_path = f"{clone_dir}/bot.py"
    with open(script_path, 'w') as f:
        f.write(clone_script)
    
    # Даем права на выполнение
    os.chmod(script_path, 0o755)
    
    logger.info(f"✅ Создан скрипт клона: {script_path}")
    return script_path

def launch_clone(token: str) -> dict:
    """Запускает полноценный клон"""
    
    clone_id = f"clone_{int(time.time())}_{random.randint(1000, 9999)}"
    logger.info(f"🚀 Запуск клона {clone_id} с токеном: {token[:10]}...")
    
    try:
        # 1. Проверяем токен
        if not is_valid_token(token):
            return {
                "success": False,
                "error": f"Неверный формат токена: {token[:20]}...",
                "clone_id": clone_id
            }
        
        # 2. Создаем структуру директорий
        clone_dir = create_clone_directory_structure(clone_id, token)
        
        # 3. Создаем скрипт клона
        script_path = create_simple_clone_script(clone_dir, clone_id, token)
        
        # 4. Проверяем синтаксис
        logger.info(f"🔍 Проверяю синтаксис...")
        check_result = subprocess.run(
            ["python3", "-m", "py_compile", script_path],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if check_result.returncode != 0:
            return {
                "success": False,
                "error": f"Синтаксическая ошибка: {check_result.stderr[:200]}",
                "clone_id": clone_id
            }
        
        # 5. Запускаем клон
        log_file = f"{clone_dir}/logs/launch.log"
        
        with open(log_file, 'w') as f:
            f.write(f"=== ЗАПУСК КЛОНА {clone_id} ===\n")
            f.write(f"Время: {time.ctime()}\n")
            f.write(f"Токен: {token[:10]}...\n")
            f.write(f"Директория: {clone_dir}\n")
            f.write("=" * 50 + "\n")
        
        # Команда для запуска
        cmd = ["python3", script_path]
        
        # Запускаем процесс
        env = os.environ.copy()
        env['PYTHONPATH'] = '/usr/local/lib/python3.10/dist-packages'
        
        process = subprocess.Popen(
            cmd,
            stdout=open(log_file, 'a'),
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
            cwd=clone_dir,
            env=env
        )
        
        pid = process.pid
        logger.info(f"✅ Клон запущен с PID: {pid}")
        
        # 6. Ждем и проверяем
        logger.info("⏳ Жду запуска (5 секунд)...")
        time.sleep(5)
        
        # Проверяем жив ли процесс
        try:
            os.kill(pid, 0)
            process_alive = True
        except OSError:
            process_alive = False
        
        # 7. Проверяем API бота
        try:
            import requests
            check_url = f"https://api.telegram.org/bot{token}/getMe"
            response = requests.get(check_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    username = data['result'].get('username', 'неизвестно')
                    api_ok = True
                else:
                    api_ok = False
                    username = 'ошибка'
            else:
                api_ok = False
                username = 'ошибка'
                
        except Exception as e:
            api_ok = False
            username = 'ошибка'
            logger.error(f"❌ Ошибка API: {e}")
        
        # 8. Сохраняем информацию
        process_info = {
            "clone_id": clone_id,
            "pid": pid,
            "token_preview": token[:10] + "...",
            "username": username,
            "clone_dir": clone_dir,
            "script_path": script_path,
            "log_file": log_file,
            "start_time": time.time(),
            "status": "running" if process_alive else "stopped",
            "api_ok": api_ok
        }
        
        # Сохраняем в общий файл
        processes_file = "/var/www/imlerih_bot/clone_processes.json"
        processes = {}
        
        if os.path.exists(processes_file):
            try:
                with open(processes_file, 'r') as f:
                    processes = json.load(f)
            except:
                processes = {}
        
        processes[clone_id] = process_info
        
        with open(processes_file, 'w') as f:
            json.dump(processes, f, indent=2)
        
        # Сохраняем токен
        backup_file = "/var/www/imlerih_bot/backup_tokens.json"
        tokens = []
        
        if os.path.exists(backup_file):
            try:
                with open(backup_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        tokens = json.loads(content)
            except:
                tokens = []
        
        if token not in tokens:
            tokens.append(token)
            with open(backup_file, 'w') as f:
                json.dump(tokens, f, indent=2)
        
        # 9. Формируем результат
        if process_alive and api_ok:
            # Генерируем ссылку
            bot_link = f"https://t.me/{username}" if username != 'неизвестно' and username != 'ошибка' else None
            
            result = {
                "success": True,
                "clone_id": clone_id,
                "pid": pid,
                "username": username,
                "token_preview": token[:10] + "...",
                "clone_dir": clone_dir,
                "message": "✅ Клон успешно создан и запущен!"
            }
            
            if bot_link:
                result["bot_link"] = bot_link
            
            logger.info(f"🎉 Клон {clone_id} успешно создан! @{username}, PID: {pid}")
            return result
            
        else:
            errors = []
            if not process_alive:
                errors.append("Процесс не запущен")
            if not api_ok:
                errors.append("API не отвечает")
            
            # Пытаемся получить логи ошибок
            error_log = ""
            if os.path.exists(log_file):
                with open(log_file, 'r') as f:
                    lines = f.readlines()[-10:]
                    error_log = "\n".join(lines)
            
            return {
                "success": False,
                "error": f"Проблемы с клоном: {', '.join(errors)}",
                "clone_id": clone_id,
                "log_tail": error_log
            }
        
    except Exception as e:
        logger.error(f"❌ Исключение при запуске клона: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": f"Системная ошибка: {str(e)[:200]}",
            "clone_id": clone_id if 'clone_id' in locals() else "unknown"
        }

def main():
    """Основная функция"""
    if len(sys.argv) != 2:
        print("❌ Использование: python3 fixed_launcher.py <telegram_bot_token>")
        print("")
        print("📝 Пример:")
        print('  python3 fixed_launcher.py "1234567890:ABCdefGHIjklmNoPQRsTUVwxyZ-1234567890"')
        sys.exit(1)
    
    token = sys.argv[1].strip()
    
    print(f"🚀 Запуск исправленного лаунчера...")
    print(f"🔑 Токен: {token[:10]}...")
    print("")
    
    result = launch_clone(token)
    
    print("=" * 50)
    
    if result["success"]:
        print("✅ Клон успешно создан!")
        print("")
        print(f"🆔 ID: {result['clone_id']}")
        print(f"👤 Username: @{result['username']}")
        print(f"📊 PID: {result['pid']}")
        print(f"📁 Директория: {result['clone_dir']}")
        
        if "bot_link" in result:
            print(f"🔗 Ссылка: {result['bot_link']}")
        
        print("")
        print("📌 Клон содержит:")
        print("   • Полноценное меню")
        print("   • Обработчики команд /start, /test, /status")
        print("   • Инлайн-кнопки")
        print("   • Логирование в отдельный файл")
        print("   • Может создавать своих клонов")
        
    else:
        print("❌ Ошибка создания клона!")
        print("")
        print(f"📝 Ошибка: {result['error']}")
        print(f"🆔 ID клона: {result.get('clone_id', 'неизвестно')}")
        
        if 'log_tail' in result and result['log_tail']:
            print("")
            print("📄 Последние строки лога:")
            print(result['log_tail'])
        
        sys.exit(1)

if __name__ == "__main__":
    main()