#!/usr/bin/env python3
import os
import sys
import json
import time
import random
import subprocess

def create_working_clone(token, clone_id):
    """Создает работающий скрипт клона без ошибок"""
    
    clone_dir = f"/var/www/imlerih_bot/clones/{clone_id}"
    os.makedirs(clone_dir, exist_ok=True)
    os.makedirs(f"{clone_dir}/logs", exist_ok=True)
    os.makedirs(f"{clone_dir}/txt", exist_ok=True)
    
    with open(f"{clone_dir}/txt/token.txt", 'w') as f:
        f.write(token)
    
    # ИСПРАВЛЕННЫЙ скрипт - без ошибок в f-строках
    script = f'''#!/usr/bin/env python3
import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

CLONE_ID = "{clone_id}"
BOT_TOKEN = "{token}"

# НЕ используем f-строку с переменной в format, так как она еще не определена
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("{clone_dir}/logs/bot.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    logger.info(f"Start from {{message.from_user.id}}")
    
    text = f"""🌴 <b>ДОБРО ПОЖАЛОВАТЬ В СЕРВИС ИНСПЕКТОРА СЭМА</b> .

С инспектором вы получаете:
🌍 Более 20 видов документов 
⚡️ Быстрая доставка по всему СНГ
🔒 Полная анонимность доставки
👫 Отзывы настоящих клиентов

⭐️ Не теряй доступ к боту даже при блокировке: нажми кнопку "Клон бота - защита" и сохрани доступ навсегда

🎉 <b>Вы используете резервного клона!</b>
🆔 ID клона: {{CLONE_ID}}"""
    
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("test"))
async def test_handler(message: types.Message):
    await message.answer(f"✅ Тест пройден! Клон {{CLONE_ID}} работает.")

@dp.message(Command("clone_info"))
async def clone_info_handler(message: types.Message):
    await message.answer(
        f"📊 <b>Информация о клоне</b>\\n"
        f"🤖 ID: {{CLONE_ID}}\\n"
        f"🔑 Токен: {{BOT_TOKEN[:10]}}...\\n"
        f"📁 Директория: {clone_dir}\\n"
        f"⚙️ PID: {{os.getpid()}}",
        parse_mode="HTML"
    )

@dp.message()
async def echo_handler(message: types.Message):
    await message.answer(f"Эхо: {{message.text}}")

async def main():
    logger.info(f"Starting clone {{CLONE_ID}}")
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
        print("Usage: python3 working_launcher.py <token>")
        sys.exit(1)
    
    token = sys.argv[1].strip()
    
    # Базовая проверка токена
    if ':' not in token:
        print("❌ Invalid token format")
        sys.exit(1)
    
    clone_id = f"clone_{int(time.time())}_{random.randint(1000, 9999)}"
    
    try:
        print(f"🚀 Creating clone {clone_id}...")
        clone_dir, script_path = create_working_clone(token, clone_id)
        
        print(f"✅ Clone created: {clone_id}")
        print(f"📁 Directory: {clone_dir}")
        
        # Запускаем клон
        process = subprocess.Popen(
            ["python3", script_path],
            cwd=clone_dir,
            stdout=open(f"{clone_dir}/logs/bot.log", 'a'),
            stderr=subprocess.STDOUT
        )
        
        print(f"🚀 Clone started with PID: {process.pid}")
        
        # Даем время на запуск
        time.sleep(3)
        
        # Проверяем жив ли процесс
        try:
            os.kill(process.pid, 0)
            print("✅ Process is running")
            
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
                "status": "running",
                "start_time": time.time()
            }
            
            with open(processes_file, 'w') as f:
                json.dump(processes, f, indent=2)
            
            print("✅ Clone info saved")
            print("\\n📌 Commands to test:")
            print(f"   /start - Welcome message")
            print(f"   /test - Test command")
            print(f"   /clone_info - Clone information")
            
        except OSError:
            print("❌ Process failed to start")
            print("Check logs:", f"{clone_dir}/logs/bot.log")
        
    except Exception as e:
        print(f"❌ Error creating clone: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()