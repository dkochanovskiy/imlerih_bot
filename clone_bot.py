#!/usr/bin/env python3
# /var/www/imlerih_bot/clone_bot.py

import asyncio
import sys
import os
import logging
import subprocess
import json
import time
import requests
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import psycopg2
from psycopg2.extras import DictCursor

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Константы
MAIN_BOT_TOKEN = None
try:
    with open("/var/www/imlerih_bot/txt/token.txt", "r", encoding="utf-8") as f:
        MAIN_BOT_TOKEN = f.read().strip()
except FileNotFoundError:
    logger.warning("⚠️ Основной токен не найден")

STATE_FILE = "/var/www/imlerih_bot/clone_state.json"
HEALTH_FILE = "/var/www/imlerih_bot/health_status.json"

def load_token():
    """Загрузка токена для текущего клона"""
    # 1. Проверяем, стал ли клон основным
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
                if state.get("is_main", False):
                    promoted_token = state.get("promoted_token")
                    if promoted_token:
                        logger.info(f"🚀 Клон стал основным! Токен: {promoted_token[:10]}...")
                        return promoted_token
        except Exception as e:
            logger.error(f"❌ Ошибка чтения состояния: {e}")
    
    # 2. Прямой токен из переменной окружения
    token = os.environ.get('TOKEN')
    if token:
        logger.info(f"🔑 Токен из переменной TOKEN: {token[:10]}...")
        return token.strip()
    
    # 3. Токен из файла
    token_file = os.environ.get('TOKEN_FILE')
    if token_file and os.path.exists(token_file):
        try:
            with open(token_file, 'r') as f:
                token = f.read().strip()
                if token:
                    logger.info(f"📁 Токен из файла {token_file}: {token[:10]}...")
                    return token
        except Exception as e:
            logger.error(f"❌ Ошибка чтения файла {token_file}: {e}")
    
    # 4. Ищем .token файл в папке clones
    clones_dir = "/var/www/imlerih_bot/clones"
    if os.path.exists(clones_dir):
        for filename in os.listdir(clones_dir):
            if filename.endswith('.token'):
                token_file = os.path.join(clones_dir, filename)
                try:
                    with open(token_file, 'r') as f:
                        token = f.read().strip()
                        if token:
                            logger.info(f"📂 Токен из {filename}: {token[:10]}...")
                            return token
                except:
                    continue
    
    logger.error("❌ Не удалось загрузить токен!")
    return None

def is_valid_token(token: str) -> bool:
    """Проверка формата токена Telegram"""
    import re
    if not token:
        return False
    return bool(re.match(r"^\d+:[A-Za-z0-9_-]{35,}$", token))

def check_webhook_status() -> dict:
    """Проверка вебхука основного бота"""
    try:
        # Проверяем, слушает ли порт 8080
        result = subprocess.run(
            ["ss", "-tlnp"],  # или "netstat -tlnp" для старых систем
            capture_output=True,
            text=True
        )
        
        if ":8080" in result.stdout:
            # Порт занят - проверяем ответ
            try:
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex(('127.0.0.1', 8080))
                sock.close()
                
                if result == 0:
                    return {"status": "port_open", "webhook": True}
                else:
                    return {"status": "port_closed", "webhook": False}
            except:
                return {"status": "port_check_error", "webhook": False}
        else:
            return {"status": "port_not_listening", "webhook": False}
            
    except Exception as e:
        return {"status": "error", "error": str(e), "webhook": False}

def check_main_bot_status() -> dict:
    """Проверка статуса основного бота - МНОГОУРОВНЕВАЯ ПРОВЕРКА"""
    
    # Уровень 1: Проверяем, запущен ли systemd сервис
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "imlerih_bot"],
            capture_output=True,
            text=True,
            timeout=5
        )
        systemd_status = result.stdout.strip()
        
        if systemd_status != "active":
            return {
                "status": "systemd_inactive",
                "error": f"Systemd: {systemd_status}",
                "timestamp": datetime.now().isoformat(),
                "level": "systemd"
            }
    except Exception as e:
        logger.error(f"❌ Ошибка проверки systemd: {e}")
    
    # Уровень 2: Проверяем процесс
    try:
        result = subprocess.run(
            ["pgrep", "-f", "imlerih_bot.py"],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:  # Процесс не найден
            return {
                "status": "process_not_found",
                "error": "Процесс не найден",
                "timestamp": datetime.now().isoformat(),
                "level": "process"
            }
    except Exception as e:
        logger.error(f"❌ Ошибка проверки процесса: {e}")
    
    # Уровень 3: Проверяем Telegram API (только если предыдущие проверки прошли)
    if not MAIN_BOT_TOKEN:
        return {"status": "unknown", "error": "No main token", "timestamp": datetime.now().isoformat()}
    
    try:
        start_time = time.time()
        url = f"https://api.telegram.org/bot{MAIN_BOT_TOKEN}/getMe"
        response = requests.get(url, timeout=10)
        response_time = time.time() - start_time
        
        if response.status_code == 200 and response.json().get("ok", False):
            return {
                "status": "online",
                "response_time": response_time,
                "timestamp": datetime.now().isoformat(),
                "level": "api"
            }
        else:
            return {
                "status": "api_error",
                "error": f"API error: {response.status_code}",
                "timestamp": datetime.now().isoformat(),
                "level": "api"
            }
    except requests.exceptions.Timeout:
        return {
            "status": "api_timeout",
            "error": "API timeout",
            "timestamp": datetime.now().isoformat(),
            "level": "api"
        }
    except requests.exceptions.ConnectionError:
        return {
            "status": "api_connection_error",
            "error": "API connection failed",
            "timestamp": datetime.now().isoformat(),
            "level": "api"
        }
    except Exception as e:
        return {
            "status": "api_error",
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
            "level": "api"
        }

def save_health_status(status: dict):
    """Сохранение статуса здоровья"""
    try:
        with open(HEALTH_FILE, 'w') as f:
            json.dump(status, f, indent=2)
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения статуса: {e}")

def promote_to_main(current_token: str):
    """Повышение клона до основного бота"""
    try:
        state = {
            "is_main": True,
            "promoted_token": current_token,
            "promoted_at": datetime.now().isoformat(),
            "original_main_token": MAIN_BOT_TOKEN
        }
        
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
        
        logger.info(f"🎉 Клон повышен до основного бота! Токен: {current_token[:10]}...")
        
        # Обновляем токен в основном файле
        with open("/var/www/imlerih_bot/txt/token.txt", "w") as f:
            f.write(current_token)
        
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка повышения клона: {e}")
        return False

def create_clone_via_manager(token: str) -> tuple[bool, str]:
    """Создание нового клона через менеджер"""
    try:
        result = subprocess.run(
            ["python3", "/var/www/imlerih_bot/clone_manager.py", "create_simple", token],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            return True, result.stdout
        else:
            return False, result.stderr
    except subprocess.TimeoutExpired:
        return False, "Таймаут при создании клона"
    except Exception as e:
        return False, str(e)

# ============ МОНИТОРИНГ ЗДОРОВЬЯ ============

class HealthMonitor:
    """Монитор здоровья основного бота - УЛУЧШЕННАЯ ВЕРСИЯ"""
    
    def __init__(self, bot_instance, token: str, is_main: bool):
        self.bot = bot_instance
        self.token = token
        self.is_main = is_main
        self.failure_count = 0
        self.max_failures = 2  # Уменьшили до 2 проверок
        self.check_interval = 30  # Увеличили частоту проверки до 30 сек
        self.last_status = None
        self.running = False
        
    async def start(self):
        """Запуск мониторинга"""
        if self.is_main:
            logger.info("🎉 Это основной бот - мониторинг не требуется")
            return
        
        self.running = True
        logger.info(f"🩺 Запуск УЛУЧШЕННОГО мониторинга (проверка каждые {self.check_interval} сек)")
        
        while self.running:
            try:
                await asyncio.sleep(self.check_interval)
                
                # ПРОВЕРКА 1: Systemd статус
                systemd_status = await self.check_systemd()
                
                # ПРОВЕРКА 2: Процесс
                process_status = await self.check_process()
                
                # ПРОВЕРКА 3: Telegram API (только если предыдущие OK)
                api_status = None
                if systemd_status["status"] == "active" and process_status["status"] == "found":
                    api_status = check_main_bot_status()  # Используем старую функцию для API
                
                # Анализируем результаты
                overall_status = self.analyze_status(systemd_status, process_status, api_status)
                
                logger.info(f"📊 Статус основного бота: {overall_status['status']} "
                          f"(systemd: {systemd_status['status']}, "
                          f"process: {process_status['status']})")
                
                if overall_status["status"] == "healthy":
                    if self.last_status != "healthy":
                        logger.info("✅ Основной бот ЗДОРОВ")
                        self.failure_count = 0
                    self.last_status = "healthy"
                    
                else:  # Проблема обнаружена
                    self.failure_count += 1
                    logger.warning(f"⚠️ Проблема с основным ботом ({self.failure_count}/{self.max_failures}): "
                                 f"{overall_status['status']} - {overall_status.get('error', '')}")
                    
                    # Если проблемы 2 проверки подряд
                    if self.failure_count >= self.max_failures:
                        logger.error(f"🚨 Основной бот НЕ РАБОТАЕТ {self.max_failures} раза подряд!")
                        await self.notify_admin(overall_status)
                        self.failure_count = 0  # Сброс после уведомления
                        
            except Exception as e:
                logger.error(f"❌ Ошибка в мониторе здоровья: {e}")
    
    async def check_systemd(self) -> dict:
        """Проверка systemd статуса"""
        try:
            result = subprocess.run(
                ["systemctl", "is-active", "imlerih_bot"],
                capture_output=True,
                text=True,
                timeout=5
            )
            status = result.stdout.strip()
            
            return {
                "status": "active" if status == "active" else "inactive",
                "details": status,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    async def check_process(self) -> dict:
        """Проверка процесса"""
        try:
            result = subprocess.run(
                ["pgrep", "-f", "imlerih_bot.py"],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                pids = result.stdout.strip().split()
                return {
                    "status": "found",
                    "pid_count": len(pids),
                    "pids": pids,
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {
                    "status": "not_found",
                    "error": "Процесс не найден",
                    "timestamp": datetime.now().isoformat()
                }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    def analyze_status(self, systemd: dict, process: dict, api: dict = None) -> dict:
        """Анализ всех статусов"""
        
        # Критичные проблемы
        if systemd["status"] == "inactive":
            return {
                "status": "systemd_inactive",
                "error": f"Systemd: {systemd.get('details', 'unknown')}",
                "critical": True
            }
        
        if process["status"] == "not_found":
            return {
                "status": "process_not_found",
                "error": "Процесс не запущен",
                "critical": True
            }
        
        # Проблемы с API (менее критичные)
        if api and api["status"] != "online":
            return {
                "status": f"api_{api['status']}",
                "error": api.get("error", "API проблема"),
                "critical": False
            }
        
        # Всё хорошо
        return {
            "status": "healthy",
            "critical": False
        }

# ============ СОЗДАНИЕ ЭКЗЕМПЛЯРА БОТА ============

def create_bot_instance(token: str):
    """Создание экземпляра бота с указанным токеном"""
    bot = Bot(token=token)
    dp = Dispatcher(storage=MemoryStorage())
    
    # Определяем, является ли этот бот основным
    is_main_bot = False
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
                if state.get("promoted_token") == token:
                    is_main_bot = True
        except:
            pass
    
    # Хранилище для пользователей, ожидающих ввод токена
    waiting_for_token = set()
    
    # Функция для получения текста из БД
    def get_message_by_id(message_id: str) -> str:
        """Получение текста из БД"""
        try:
            conn = psycopg2.connect(
                host="localhost",
                database="karantir_bot",
                user="karantir_user",
                password="karantir_pass"
            )
            cursor = conn.cursor(cursor_factory=DictCursor)
            cursor.execute("SELECT text_message FROM interaction WHERE id_message = %s", (message_id,))
            row = cursor.fetchone()
            conn.close()
            return row["text_message"] if row else "Текст не найден."
        except Exception as e:
            logger.error(f"❌ Ошибка при запросе к БД: {e}")
            return "Ошибка загрузки текста."
    
    # Кнопки
    menu_button = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Меню", callback_data="menu")]
    ])
    
    main_menu = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Профиль", callback_data="profile"), 
         InlineKeyboardButton(text="Клон", callback_data="clone")],
        [InlineKeyboardButton(text="Оформить заказ", callback_data="place_order"), 
         InlineKeyboardButton(text="Менеджер", callback_data="manager")],
        [InlineKeyboardButton(text="Проверить основной бот", callback_data="check_main")],
        [InlineKeyboardButton(text="Назад", callback_data="back_to_welcome")]
    ])
    
    back_button = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu")]
    ])
    
    clone_menu = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Создать резервного бота", callback_data="create_clone")],
        [InlineKeyboardButton(text="Стать основным", callback_data="become_main")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu")]
    ])
    
    create_bot_menu = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="clone")]
    ])
    
    # Обработчики команд
    @dp.message(Command("start"))
    async def start_handler(message: types.Message):
        logger.info(f"🚀 {'Основной' if is_main_bot else 'Клон'} бот: /start от {message.from_user.id}")
        
        # Проверяем статус основного бота при старте (если не основной)
        if not is_main_bot:
            status = check_main_bot_status()
            if status["status"] != "online":
                logger.warning(f"⚠️ Основной бот не отвечает: {status.get('error', 'unknown')}")
                text = get_message_by_id("welcome")
                extra_text = f"\n\n⚠️ <b>Внимание!</b> Основной бот не отвечает ({status['status']}).\nВы можете сделать этого бота основным через меню 'Клон' → 'Стать основным'"
                await message.answer(text + extra_text, reply_markup=menu_button, parse_mode="HTML")
                return
        
        text = get_message_by_id("welcome")
        await message.answer(text, reply_markup=menu_button)
    
    @dp.message(Command("status"))
    async def status_handler(message: types.Message):
        """Статус системы"""
        if message.from_user.id != 291178183:  # Только для админа
            return
        
        status = check_main_bot_status()
        
        status_text = (
            f"🤖 <b>Статус системы</b>\n\n"
            f"📱 Этот бот: {'🎉 <b>ОСНОВНОЙ</b>' if is_main_bot else '🤖 Клон'}\n"
            f"🔑 Токен: {token[:10]}...\n\n"
            f"📊 <b>Основной бот:</b>\n"
            f"• Статус: {status['status'].upper()}\n"
        )
        
        if status["status"] == "online":
            status_text += f"• Время ответа: {status.get('response_time', 0):.2f}с\n"
        elif status.get("error"):
            status_text += f"• Ошибка: {status['error']}\n"
        
        status_text += f"• Проверено: {status['timestamp'][11:19]}\n\n"
        
        if is_main_bot:
            status_text += "🎉 <b>Вы основной бот!</b>\nМожете создавать резервных клонов."
        else:
            status_text += "🤖 <b>Вы резервный клон</b>\nПри падении основного бота можете стать основным."
        
        await message.answer(status_text, parse_mode="HTML")
    
    @dp.message(Command("promote"))
    async def promote_handler(message: types.Message):
        """Стать основным ботом (команда)"""
        if message.from_user.id != 291178183:
            await message.answer("❌ Доступ запрещён")
            return
        
        if is_main_bot:
            await message.answer("🎉 Вы уже основной бот!")
            return
        
        status = check_main_bot_status()
        if status["status"] == "online":
            await message.answer(
                f"⚠️ Основной бот работает (статус: {status['status']}).\n"
                f"Повышение не требуется.",
                parse_mode="HTML"
            )
            return
        
        success = promote_to_main(token)
        if success:
            await message.answer(
                "🎉 <b>Поздравляем! Вы стали основным ботом!</b>\n\n"
                "Теперь вы можете:\n"
                "• Создавать резервных клонов\n"
                "• Получать все команды\n"
                "• Управлять системой\n\n"
                "<i>Перезапустите бота для применения изменений.</i>",
                parse_mode="HTML"
            )
        else:
            await message.answer("❌ Ошибка при повышении статуса")
    
    @dp.message(Command("test_crash"))
    async def test_crash_handler(message: types.Message):
        """Тестирование падения основного бота"""
        if message.from_user.id != 291178183:
            await message.answer("❌ Доступ запрещён")
            return
        
        if is_main_bot:
            await message.answer("🎉 Вы основной бот, тестирование не требуется")
            return
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧪 Симитировать падение", callback_data="simulate_crash")],
            [InlineKeyboardButton(text="✅ Проверить сейчас", callback_data="check_main")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="menu")]
        ])
        
        await message.answer(
            "🧪 <b>Тестирование отказоустойчивости</b>\n\n"
            "Опции:\n"
            "1. <b>Симитировать падение</b> - временно 'уронить' основной бот для теста\n"
            "2. <b>Проверить сейчас</b> - проверить текущий статус\n\n"
            "<i>Для реального теста остановите основной бот командой:</i>\n"
            "<code>sudo systemctl stop imlerih_bot</code>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    
    # Обработка текстовых сообщений
    @dp.message()
    async def text_handler(message: types.Message):
        user_id = message.from_user.id
        
        if user_id in waiting_for_token:
            new_token = message.text.strip()
            waiting_for_token.discard(user_id)
            
            logger.info(f"📩 Получение токена от {user_id}")
            
            if is_valid_token(new_token):
                success, result = create_clone_via_manager(new_token)
                
                if success:
                    await message.answer(
                        "✅ <b>Резервный клон создан и запущен!</b>\n\n"
                        "Теперь этот бот:\n"
                        "1. Работает независимо\n"
                        "2. Может стать основным при падении\n"
                        "3. Имеет полный функционал\n\n"
                        "Сохраните токен в надёжном месте!",
                        parse_mode="HTML",
                        reply_markup=main_menu
                    )
                    logger.info(f"✅ Создан резервный клон: {new_token[:10]}...")
                else:
                    await message.answer(f"❌ Ошибка при создании клона:\n{result}", reply_markup=main_menu)
            else:
                await message.answer(
                    "❌ Неверный формат токена.\n\n"
                    "Пример:\n<code>123456:ABCdefGHIjklmNoPQRsTUVwxyZ</code>\n\n"
                    "Попробуйте ещё раз или вернитесь в меню.",
                    parse_mode="HTML",
                    reply_markup=main_menu
                )
    
    # Callback обработчики
    @dp.callback_query(lambda c: c.data == "menu")
    async def show_menu(callback: types.CallbackQuery):
        await callback.message.edit_text("Меню", reply_markup=main_menu)
        await callback.answer()
    
    @dp.callback_query(lambda c: c.data == "back_to_welcome")
    async def back_to_welcome(callback: types.CallbackQuery):
        text = get_message_by_id("welcome")
        await callback.message.edit_text(text, reply_markup=menu_button)
        await callback.answer()
    
    @dp.callback_query(lambda c: c.data == "profile")
    async def profile(callback: types.CallbackQuery):
        text = get_message_by_id("profile")
        await callback.message.edit_text(text, reply_markup=back_button)
        await callback.answer()
    
    @dp.callback_query(lambda c: c.data == "clone")
    async def clone(callback: types.CallbackQuery):
        text = get_message_by_id("clone")
        
        # Добавляем информацию о статусе
        if is_main_bot:
            status_info = "\n\n🎉 <b>Вы основной бот!</b>\nМожете создавать резервных клонов."
        else:
            status = check_main_bot_status()
            if status["status"] == "online":
                status_info = f"\n\n🤖 <b>Вы резервный клон</b>\nОсновной бот: 🟢 работает"
            else:
                status_info = f"\n\n⚠️ <b>Основной бот не отвечает!</b>\nВы можете стать основным."
        
        await callback.message.edit_text(text + status_info, reply_markup=clone_menu, parse_mode="HTML")
        await callback.answer()
    
    @dp.callback_query(lambda c: c.data == "check_main")
    async def check_main_callback(callback: types.CallbackQuery):
        """Проверка статуса основного бота"""
        status = check_main_bot_status()
        
        if status["status"] == "online":
            message_text = (
                f"✅ <b>Основной бот работает!</b>\n\n"
                f"Статус: {status['status']}\n"
                f"Время ответа: {status.get('response_time', 0):.2f}сек\n"
                f"Проверено: {status['timestamp'][11:19]}"
            )
        else:
            message_text = (
                f"⚠️ <b>Основной бот не отвечает!</b>\n\n"
                f"Статус: неактивен\n"
                f"Проверено: {status['timestamp'][11:19]}\n\n"
                f"Вы можете сделать этого бота основным."
            )
        
        await callback.message.edit_text(message_text, reply_markup=back_button, parse_mode="HTML")
        await callback.answer()
    
    @dp.callback_query(lambda c: c.data == "become_main")
    async def become_main(callback: types.CallbackQuery):
        if is_main_bot:
            await callback.message.edit_text(
                "🎉 Вы уже основной бот!\n"
                "Можете создавать резервных клонов.",
                reply_markup=back_button
            )
            await callback.answer()
            return
        
        status = check_main_bot_status()
        if status["status"] == "online":
            await callback.message.edit_text(
                f"✅ <b>Основной бот работает</b>\n\n"
                f"Статус: {status['status']}\n"
                f"Время ответа: {status.get('response_time', 0):.2f}сек\n\n"
                f"Повышение не требуется.",
                reply_markup=back_button,
                parse_mode="HTML"
            )
            await callback.answer()
            return
        
        # Предлагаем стать основным
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, стать основным", callback_data="confirm_promote")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="clone")]
        ])
        
        await callback.message.edit_text(
            f"⚠️ <b>Основной бот не отвечает!</b>\n\n"
            f"Статус: неактивен\n"
            f"Хотите сделать этого бота основным?\n\n"
            f"После этого вы сможете:\n"
            "• Создавать резервных клонов\n"
            "• Получать все команды\n"
            "• Управлять системой",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback.answer()
    
    @dp.callback_query(lambda c: c.data == "confirm_promote")
    async def confirm_promote(callback: types.CallbackQuery):
        success = promote_to_main(token)
        if success:
            await callback.message.edit_text(
                "🎉 <b>Поздравляем! Вы стали основным ботом!</b>\n\n"
                "Теперь вы можете:\n"
                "• Создавать резервных клонов\n"
                "• Получать все команды\n"
                "• Управлять системой\n\n"
                "⚠️ <b>Требуется перезапуск!</b>\n"
                "Используйте команду для перезапуска.",
                reply_markup=back_button,
                parse_mode="HTML"
            )
        else:
            await callback.message.edit_text(
                "❌ <b>Ошибка при повышении статуса</b>\n\n"
                "Попробуйте позже или обратитесь к администратору.",
                reply_markup=back_button,
                parse_mode="HTML"
            )
        await callback.answer()
    
    @dp.callback_query(lambda c: c.data == "create_clone")
    async def create_clone(callback: types.CallbackQuery):
        if not is_main_bot:
            # Проверяем статус основного бота
            status = check_main_bot_status()
            if status["status"] == "online":
                await callback.message.edit_text(
                    "⚠️ <b>Основной бот работает</b>\n\n"
                    "Создавать резервных клонов может только основной бот.\n"
                    "Если основной бот упадет, вы сможете стать основным и создавать своих клонов.",
                    reply_markup=back_button,
                    parse_mode="HTML"
                )
                await callback.answer()
                return
        
        text = get_message_by_id("guide_create_clone")
        
        # Добавляем инструкцию
        full_text = text + "\n\n📝 <b>Создание резервного клона</b>\n\nОтправьте мне токен нового бота."
        
        await callback.message.edit_text(full_text, reply_markup=create_bot_menu, parse_mode="HTML")
        waiting_for_token.add(callback.from_user.id)
        await callback.answer()
    
    @dp.callback_query(lambda c: c.data == "simulate_crash")
    async def simulate_crash(callback: types.CallbackQuery):
        """Симуляция падения основного бота"""
        # Сохраняем флаг симуляции
        with open("/var/www/imlerih_bot/test_crash_mode.json", "w") as f:
            json.dump({
                "simulated_crash": True,
                "simulated_at": datetime.now().isoformat(),
                "original_main": MAIN_BOT_TOKEN
            }, f)
        
        await callback.message.edit_text(
            "⚠️ <b>Симуляция падения активна!</b>\n\n"
            "Основной бот теперь считается 'упавшим'.\n"
            "Проверьте:\n"
            "1. Меню 'Клон' → 'Стать основным'\n"
            "2. Команду /status\n\n"
            "Чтобы отключить симуляцию:\n"
            "<code>/test_recovery</code>",
            parse_mode="HTML",
            reply_markup=back_button
        )
        await callback.answer()
    
    @dp.message(Command("test_recovery"))
    async def test_recovery_handler(message: types.Message):
        """Отключение симуляции падения"""
        if message.from_user.id != 291178183:
            await message.answer("❌ Доступ запрещён")
            return
        
        # Удаляем флаг симуляции
        import os
        if os.path.exists("/var/www/imlerih_bot/test_crash_mode.json"):
            os.remove("/var/www/imlerih_bot/test_crash_mode.json")
        
        await message.answer(
            "✅ <b>Симуляция отключена</b>\n\n"
            "Основной бот теперь считается 'работающим'.",
            parse_mode="HTML"
        )
    
    @dp.callback_query(lambda c: c.data == "place_order")
    async def place_order(callback: types.CallbackQuery):
        text = get_message_by_id("place_order")
        await callback.message.edit_text(text, reply_markup=back_button)
        await callback.answer()
    
    @dp.callback_query(lambda c: c.data == "manager")
    async def manager(callback: types.CallbackQuery):
        text = get_message_by_id("manager")
        await callback.message.edit_text(text, reply_markup=back_button)
        await callback.answer()
    
    return bot, dp, is_main_bot

# ============ ОСНОВНАЯ ФУНКЦИЯ ============

async def main():
    """Основная функция запуска клона"""
    token = load_token()
    
    if not token:
        logger.error("❌ Не удалось загрузить токен")
        sys.exit(1)
    
    if not is_valid_token(token):
        logger.error(f"❌ Неверный формат токена: {token[:20]}...")
        sys.exit(1)
    
    logger.info(f"🚀 Запуск бота с токеном: {token[:10]}...")
    
    try:
        bot, dp, is_main_bot = create_bot_instance(token)
        
        # Создаем и запускаем монитор здоровья (если не основной бот)
        monitor = None
        if not is_main_bot:
            monitor = HealthMonitor(bot, token, is_main_bot)
            monitor_task = asyncio.create_task(monitor.start())
        
        if is_main_bot:
            logger.info("🎉 Этот бот работает в режиме ОСНОВНОГО бота")
        else:
            logger.info("🤖 Этот бот работает в режиме резервного клона")
            logger.info("🩺 Мониторинг здоровья основного бота запущен")
        
        logger.info(f"🟢 Бот запущен и готов к работе")
        
        try:
            await dp.start_polling(
                bot,
                allowed_updates=dp.resolve_used_update_types(),
                close_bot_session=True
            )
        finally:
            # Останавливаем мониторинг при остановке бота
            if monitor:
                monitor.stop()
                if 'monitor_task' in locals():
                    monitor_task.cancel()
        
    except Exception as e:
        logger.error(f"❌ Ошибка запуска бота: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())