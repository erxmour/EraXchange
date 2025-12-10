# ======================================================================
# ФАЙЛ: main.py (или eraXchange.py)
# Версия для Продакшен на Render (Webhooks)
# ======================================================================

import os
import requests
import telebot
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify
import time

# --- КОНФИГУРАЦИЯ ---
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_KEY = os.getenv("EXCHANGE_RATE_API_KEY")
API_BASE_URL = f"https://v6.exchangerate-api.com/v6/{API_KEY}/latest/"

if not BOT_TOKEN or not API_KEY:
    raise ValueError("❌ Ошибка: Ключи BOT_TOKEN или API_KEY не загружены из .env")

# --- КЭШИРОВАНИЕ ДАННЫХ (для оптимизации API-запросов) ---
RATE_CACHE = {}
CACHE_EXPIRY = 3600  # 1 час в секундах

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)


# ======================================================================
# 2. ФУНКЦИИ УТИЛИТ
# ======================================================================

def get_server_url():
    """Автоматически определяет адрес хостинга Render или использует запасной вариант."""
    # Render предоставляет этот URL через системную переменную
    server_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")

    if server_host:
        # На Render: возвращает чистый домен (например, 'myapp.onrender.com')
        return server_host
    else:
        # Локальный тест: ВАЖНО - УКАЖИТЕ ЗДЕСЬ СВОЙ РЕАЛЬНЫЙ ДОМЕН RENDER
        # (ИЛИ '127.0.0.1:5000' для локального теста с Ngrok)
        # Мы оставляем домен для удобства, чтобы не менять код при локальной отладке Webhook
        return "https://eraxchangex.onrender.com"


def get_exchange_rate(from_currency: str, to_currency: str):
    """Получает курс обмена, используя кэш."""
    cache_key = f"{from_currency}_{to_currency}"
    current_time = time.time()

    # 1. Проверка кэша
    if cache_key in RATE_CACHE:
        timestamp, rate = RATE_CACHE[cache_key]
        if current_time - timestamp < CACHE_EXPIRY:
            print(f"✅ Используем кэшированный курс для {cache_key}")
            return rate, None

    # 2. Запрос к API
    url = f"{API_BASE_URL}{from_currency.upper()}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("result") != "success":
            return None, "API_ERROR"

        rate = data["conversion_rates"].get(to_currency.upper())

        if rate is None:
            return None, "CURRENCY_NOT_FOUND"

        # 3. Обновление кэша
        RATE_CACHE[cache_key] = (current_time, rate)
        return rate, None

    except requests.exceptions.RequestException as e:
        print(f"❌ Ошибка при запросе к API: {e}")
        return None, "NETWORK_ERROR"


# ======================================================================
# 3. НАСТРОЙКА АДРЕСОВ И ПУТЕЙ
# ======================================================================

# Динамически получаем адрес сервера
SERVER_HOST = get_server_url()

# Адрес, который Telegram будет использовать для отправки обновлений
WEBHOOK_PATH = f"/{BOT_TOKEN}"
WEBHOOK_URL = f"https://{SERVER_HOST}{WEBHOOK_PATH}"

# Адрес, который бот будет использовать для открытия TMA
HOSTING_URL = f"https://{SERVER_HOST}"


# ======================================================================
# 4. FLASK API (МАРШРУТЫ)
# ======================================================================

# Маршрут для открытия самого мини-приложения
@app.route('/')
def serve_web_app():
    return render_template('index.html')


# API-маршрут для обработки конвертации
@app.route('/api/exchange', methods=['POST'])
def exchange_api():
    data = request.json
    try:
        amount = float(data.get('amount', 0))
        from_currency = data.get('from', 'USD').upper()
        to_currency = data.get('to', 'KZT').upper()
        if amount <= 0:
            return jsonify({'error': 'Неверная сумма'}), 400
    except Exception:
        return jsonify({'error': 'Неверный формат данных'}), 400

    rate, error = get_exchange_rate(from_currency, to_currency)

    if error:
        error_msg = {
            "NETWORK_ERROR": "Ошибка сети при получении курса.",
            "API_ERROR": "Ошибка API-сервиса.",
            "CURRENCY_NOT_FOUND": f"Курс {from_currency} к {to_currency} не найден."
        }.get(error, "Неизвестная ошибка.")
        return jsonify({'error': error_msg}), 500

    result = amount * rate

    return jsonify({
        'success': True,
        'result': f"{result:,.2f}",
        'rate': f"{rate:,.4f}",
        'from': from_currency,
        'to': to_currency
    })


# ======================================================================
# 5. TELEGRAM WEBHOOKS И ОБРАБОТЧИКИ
# ======================================================================

# Маршрут, куда Telegram будет отправлять обновления
@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        return '', 403


# Обработчик команды /start
@bot.message_handler(commands=['start', 'menu'])
def send_menu(message):
    markup = telebot.types.InlineKeyboardMarkup()
    # Кнопка открывает Mini App по HOSTING_URL
    web_app_info = telebot.types.WebAppInfo(HOSTING_URL)

    markup.add(
        telebot.types.InlineKeyboardButton(
            text="🚀 Открыть Валютообменник",
            web_app=web_app_info
        )
    )

    bot.send_message(
        message.chat.id,
        "Нажмите кнопку ниже, чтобы открыть мини-приложение для конвертации.",
        reply_markup=markup
    )


# ======================================================================
# 6. ЗАПУСК
# ======================================================================

if __name__ == '__main__':
    # Эта часть выполняется ТОЛЬКО при локальном запуске (для тестов!)
    # Для продакшена Render использует Gunicorn

    # 1. Сброс старых вебхуков и установка нового
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
    print(f"🤖 Бот настроен на Webhook: {WEBHOOK_URL}")

    # 2. Запуск Flask
    # ВНИМАНИЕ: Для локального запуска может понадобиться Ngrok и адрес '127.0.0.1:5000'
    app.run(host='0.0.0.0', port=os.environ.get('PORT', 5000))