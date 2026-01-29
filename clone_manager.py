#!/usr/bin/env python3
# /var/www/imlerih_bot/clone_manager.py

import os
import sys
import subprocess
import re
import hashlib
import time
import json
import tempfile
from pathlib import Path

def is_valid_token(token: str) -> bool:
    """Проверка формата токена Telegram"""
    if not token:
        return False
    return bool(re.match(r"^\d+:[A-Za-z0-9_-]{35,}$", token))

class CloneManager:
    def __init__(self):
        self.clones_dir = Path("/var/www/imlerih_bot/clones")
        self.clones_dir.mkdir(exist_ok=True, mode=0o755)
    
    def create_clone_simple(self, token: str) -> tuple[bool, str]:
        """Упрощенное создание клона - запуск через screen"""
        if not is_valid_token(token):
            return False, "Неверный формат токена"
        
        try:
            clone_id = hashlib.md5(f"{token}_{time.time()}".encode()).hexdigest()[:8]
            clone_name = f"clone_{clone_id}"
            
            print(f"Создание клона: {clone_name}")
            
            # Сохраняем токен
            token_file = self.clones_dir / f"{clone_name}.token"
            with open(token_file, 'w') as f:
                f.write(token)
            os.chmod(token_file, 0o600)
            
            print(f"Токен сохранен в: {token_file}")
            
            # Запускаем через screen
            screen_cmd = [
                "screen", "-dmS", f"bot_{clone_name}",
                "python3", "/var/www/imlerih_bot/clone_bot.py"
            ]
            
            print(f"Команда запуска: {' '.join(screen_cmd)}")
            
            # Устанавливаем переменную окружения
            env = os.environ.copy()
            env['TOKEN_FILE'] = str(token_file)
            
            print("Запуск screen...")
            result = subprocess.run(
                screen_cmd,
                env=env,
                capture_output=True,
                text=True
            )
            
            print(f"Результат: код={result.returncode}, вывод={result.stdout}, ошибка={result.stderr}")
            
            if result.returncode == 0:
                # Даем время на запуск
                time.sleep(2)
                
                # Проверяем, запущен ли screen
                check_cmd = ["screen", "-list"]
                check_result = subprocess.run(check_cmd, capture_output=True, text=True)
                
                print(f"Проверка screen: {check_result.stdout[:100]}...")
                
                if f"bot_{clone_name}" in check_result.stdout:
                    return True, f"✅ Клон запущен через screen: {clone_name}\nУправление: screen -r bot_{clone_name}"
                else:
                    return True, f"⚠️ Клон создан, но требует проверки: {clone_name}"
            else:
                return False, f"❌ Ошибка запуска: {result.stderr}"
                
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            return False, f"❌ Ошибка: {str(e)}\nДетали: {error_details}"
    
    def list_clones(self) -> str:
        """Список клонов через screen"""
        try:
            # Проверяем screen сессии
            result = subprocess.run(
                ["screen", "-list"],
                capture_output=True,
                text=True
            )
            
            clones = []
            for line in result.stdout.split('\n'):
                if "bot_" in line:
                    clones.append(line.strip())
            
            if clones:
                return "Запущенные клоны:\n" + "\n".join(clones)
            else:
                return "🟢 Нет запущенных клонов"
                
        except Exception as e:
            return f"Ошибка: {str(e)}"
    
    def create_clone_systemd(self, token: str) -> tuple[bool, str]:
        """Создание клона с systemd (требует прав root)"""
        if not is_valid_token(token):
            return False, "Неверный формат токена"
        
        try:
            clone_id = hashlib.md5(f"{token}_{time.time()}".encode()).hexdigest()[:8]
            service_name = f"bot_clone_{clone_id}"
            
            # Сохраняем токен
            token_file = self.clones_dir / f"{service_name}.token"
            with open(token_file, 'w') as f:
                f.write(token)
            os.chmod(token_file, 0o600)
            
            # Создаем файл сервиса
            service_content = f"""[Unit]
Description=Telegram Bot Clone {service_name}
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/var/www/imlerih_bot
Environment=TOKEN_FILE={token_file}
ExecStart=/usr/bin/python3 /var/www/imlerih_bot/clone_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
            
            service_file = self.clones_dir / f"{service_name}.service"
            with open(service_file, 'w') as f:
                f.write(service_content)
            
            instructions = f"""
✅ Токен сохранен: {token_file}
✅ Файл сервиса создан: {service_file}

📋 Для завершения установки выполните команды от root:

sudo cp {service_file} /etc/systemd/system/
sudo chmod 644 /etc/systemd/system/{service_name}.service
sudo systemctl daemon-reload
sudo systemctl enable {service_name}.service
sudo systemctl start {service_name}.service

Или одной командой:
sudo bash -c "cp {service_file} /etc/systemd/system/ && chmod 644 /etc/systemd/system/{service_name}.service && systemctl daemon-reload && systemctl enable {service_name}.service && systemctl start {service_name}.service"
"""
            
            return True, instructions
                
        except Exception as e:
            return False, f"Ошибка: {str(e)}"

def restart_clone(service_name: str) -> tuple[bool, str]:
    """Перезапуск клона"""
    try:
        # Находим screen сессию
        check_cmd = ["screen", "-list"]
        check_result = subprocess.run(check_cmd, capture_output=True, text=True)
        
        if f"bot_{service_name}" in check_result.stdout:
            # Останавливаем старую сессию
            stop_cmd = ["screen", "-S", f"bot_{service_name}", "-X", "quit"]
            subprocess.run(stop_cmd, check=True)
        
        # Находим токен файл
        token_file = f"/var/www/imlerih_bot/clones/{service_name}.token"
        if os.path.exists(token_file):
            with open(token_file, 'r') as f:
                token = f.read().strip()
            
            # Перезапускаем
            return create_clone_simple(token)
        else:
            return False, f"❌ Файл токена не найден: {token_file}"
            
    except Exception as e:
        return False, f"❌ Ошибка перезапуска: {str(e)}"

def main():
    """Основная функция для запуска из командной строки"""
    if len(sys.argv) < 2:
        print("Использование: python3 clone_manager.py <команда> [параметры]")
        print("Команды:")
        print("  create_simple <токен> - создать клон через screen (рекомендуется)")
        print("  create_systemd <токен> - создать клон с systemd (требует root)")
        print("  list - список запущенных клонов")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    manager = CloneManager()
    
    if command == "create_simple":
        if len(sys.argv) < 3:
            print("Ошибка: для команды create_simple требуется токен")
            sys.exit(1)
        token = sys.argv[2]
        success, message = manager.create_clone_simple(token)
        print(message)
        sys.exit(0 if success else 1)
    
    elif command == "create_systemd":
        if len(sys.argv) < 3:
            print("Ошибка: для команды create_systemd требуется токен")
            sys.exit(1)
        token = sys.argv[2]
        success, message = manager.create_clone_systemd(token)
        print(message)
        sys.exit(0 if success else 1)
    
    elif command == "list":
        clones_list = manager.list_clones()
        print(clones_list)
        sys.exit(0)
    
    else:
        print(f"Неизвестная команда: {command}")
        sys.exit(1)

if __name__ == "__main__":
    main()