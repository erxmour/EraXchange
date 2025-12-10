# main.py (Адаптированный код для Render/Webhooks)

import os
import requests
import telebot
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify

# =====================================================================
# 1. КОНФИГУРАЦИЯ И ИНИЦИАЛИЗАЦИЯ
# =====================================================================

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_KEY = os.getenv("EXCHANGE_RATE_API_KEY")

if not BOT_TOKEN or not API_KEY:
    raise ValueError("❌ Ошибка: Ключи не загружены!")

# Render предоставит нам переменную среды для нашего домена
SERVER_URL = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if SERVER_URL is None:
    # Запасной вариант для локального теста, если Render_External_Hostname не установлен
    SERVER_URL = "https://your-app-name.onrender.com"

# Адрес, который Telegram будет использовать для отправки обновлений
WEBHOOK_PATH = f"/{BOT_TOKEN}"
WEBHOOK_URL = f"https://{SERVER_URL}{WEBHOOK_PATH}"

# Адрес, который бот будет использовать для открытия TMA
HOSTING_URL = f"https://{SERVER_URL}"  # Теперь это чистый адрес нашего хостинга

API_BASE_URL = f"https://v6.exchangerate-api.com/v6/{API_KEY}/latest/"

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)


# ----------------------------------------------------------------------
# Функция получения курса (Без изменений)
# ----------------------------------------------------------------------
def get_exchange_rate(from_currency: str, to_currency: str):
    url = f"{API_BASE_URL}{from_currency.upper()}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if data.get("result") != "success": return None, "API_ERROR"
        rate = data["conversion_rates"].get(to_currency.upper())
        return rate, None
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при запросе к API: {e}")
        return None, "NETWORK_ERROR"


# =====================================================================
# 2. FLASK API
# =====================================================================

# Маршрут для открытия самого мини-приложения
@app.route('/')
def serve_web_app():
    return render_template('index.html')


# API-маршрут для обработки конвертации
@app.route('/api/exchange', methods=['POST'])
def exchange_api():
    # ... (логика API-обмена остается без изменений)
    data = request.json
    try:
        amount = float(data['amount'])
        from_currency = data['from'].upper()
        to_currency = data['to'].upper()
    except Exception:
        return jsonify({'error': 'Неверный формат данных'}), 400

    rate, error = get_exchange_rate(from_currency, to_currency)

    if error or rate is None:
        return jsonify({'error': 'Не удалось получить курс валют. Проверьте коды.'}), 500

    result = amount * rate

    return jsonify({
        'success': True,
        'result': f"{result:,.2f}",
        'rate': f"{rate:,.4f}",
        'from': from_currency,
        'to': to_currency
    })


# =====================================================================
# 3. TELEGRAM WEBHOOKS
# =====================================================================

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
    web_app_info = telebot.types.WebAppInfo(HOSTING_URL)  # Используем HOSTING_URL Render

    markup.add(
        telebot.types.InlineKeyboardButton(
            text="🚀 Открыть Валютообменник",
            web_app=web_app_info
        )
    )

    bot.send_message(
        message.chat.id,
        "Нажмите кнопку ниже, чтобы открыть мини-приложение.",
        reply_markup=markup
    )


# =====================================================================
# 4. ЗАПУСК ДЛЯ ПРОДАКШЕНА
# =====================================================================

if __name__ == '__main__':
    # 1. Сначала настроим вебхук в Telegram
    bot.set_webhook(url=WEBHOOK_URL)

    # 2. Render запустит Flask через Gunicorn, но мы оставляем его для локального теста
    print(f"🤖 Бот настроен на Webhook: {WEBHOOK_URL}")
    app.run(host='0.0.0.0', port=5000)