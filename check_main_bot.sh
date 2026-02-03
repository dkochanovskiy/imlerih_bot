#!/bin/bash
# Скрипт проверки основного бота

# Путь к файлу с токеном
TOKEN_FILE="/var/www/imlerih_bot/txt/token.txt"
# Файл для хранения статуса
STATUS_FILE="/var/www/imlerih_bot/main_bot_status.json"
# Файл для логов
LOG_FILE="/var/www/imlerih_bot/logs/main_bot_check.log"

# Создаем директории если нет
mkdir -p /var/www/imlerih_bot/logs

# Функция проверки
check_bot() {
    # Читаем токен из файла
    if [ ! -f "$TOKEN_FILE" ]; then
        echo "$(date): ❌ Файл токена не найден: $TOKEN_FILE" >> "$LOG_FILE"
        echo '{"status": "error", "error": "token_file_not_found", "timestamp": "'$(date -Iseconds)'"}' > "$STATUS_FILE"
        return 1
    fi
    
    TOKEN=$(cat "$TOKEN_FILE" | tr -d '\n\r ')
    
    if [ -z "$TOKEN" ]; then
        echo "$(date): ❌ Токен пустой" >> "$LOG_FILE"
        echo '{"status": "error", "error": "empty_token", "timestamp": "'$(date -Iseconds)'"}' > "$STATUS_FILE"
        return 1
    fi
    
    # Проверяем через Telegram API
    RESPONSE=$(curl -s -w "%{http_code}" -o /tmp/telegram_response.txt "https://api.telegram.org/bot$TOKEN/getMe" --max-time 10)
    
    HTTP_CODE=${RESPONSE: -3}
    RESPONSE_CONTENT=$(cat /tmp/telegram_response.txt)
    
    if [ "$HTTP_CODE" = "200" ]; then
        # Парсим JSON ответ
        if echo "$RESPONSE_CONTENT" | grep -q '"ok":true'; then
            # Бот жив
            USERNAME=$(echo "$RESPONSE_CONTENT" | grep -o '"username":"[^"]*"' | cut -d'"' -f4)
            echo "$(date): ✅ Основной бот жив: @$USERNAME" >> "$LOG_FILE"
            echo "{\"status\": \"online\", \"username\": \"$USERNAME\", \"last_check\": \"$(date -Iseconds)\", \"http_code\": 200}" > "$STATUS_FILE"
            return 0
        else
            # Бот заблокирован/удалён
            ERROR=$(echo "$RESPONSE_CONTENT" | grep -o '"description":"[^"]*"' | cut -d'"' -f4)
            echo "$(date): ❌ Основной бот недоступен: $ERROR" >> "$LOG_FILE"
            echo "{\"status\": \"blocked\", \"error\": \"$ERROR\", \"last_check\": \"$(date -Iseconds)\", \"http_code\": 200}" > "$STATUS_FILE"
            return 1
        fi
    else
        # Ошибка HTTP
        echo "$(date): ❌ Ошибка HTTP $HTTP_CODE при проверке бота" >> "$LOG_FILE"
        echo "{\"status\": \"offline\", \"http_code\": $HTTP_CODE, \"last_check\": \"$(date -Iseconds)\"}" > "$STATUS_FILE"
        return 1
    fi
}

# Основной цикл
while true; do
    check_bot
    sleep 300  # Ждем 5 минут (300 секунд)
done