# main.py (Обновленная версия с Flask для TMA)

import os
import requests
import telebot
import threading
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify

# =====================================================================
# 1. КОНФИГУРАЦИЯ И ИНИЦИАЛИЗАЦИЯ
# =====================================================================

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_KEY = os.getenv("EXCHANGE_RATE_API_KEY")

if not BOT_TOKEN or not API_KEY:
    raise ValueError(
        "❌ Ошибка! Убедитесь, что файл .env существует и содержит ключи."
    )

API_BASE_URL = f"https://v6.exchangerate-api.com/v6/{API_KEY}/latest/"

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)  # Инициализация Flask
HOSTING_URL = "https://liturgical-elicia-rheumatically.ngrok-free.dev"  # !!! ВАЖНО: Замените на реальный адрес хостинга !!!


# ----------------------------------------------------------------------
# Функция получения курса (остается без изменений)
# ----------------------------------------------------------------------

def get_exchange_rate(from_currency: str, to_currency: str):
    url = f"{API_BASE_URL}{from_currency.upper()}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if data.get("result") != "success":
            return None, "API_ERROR"
        rate = data["conversion_rates"].get(to_currency.upper())
        return rate, None
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при запросе к API: {e}")
        return None, "NETWORK_ERROR"


# =====================================================================
# 2. FLASK API (ХОСТИНГ ВЕБ-ПРИЛОЖЕНИЯ И ОБРАБОТКА ЗАПРОСОВ)
# =====================================================================

# Маршрут для открытия самого мини-приложения
@app.route('/')
def serve_web_app():
    # Загружает HTML-шаблон из папки 'templates'
    return render_template('index.html')


# API-маршрут, который обрабатывает запрос конвертации от JS
@app.route('/api/exchange', methods=['POST'])
def exchange_api():
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
# 3. TELEGRAM BOT (ОТПРАВКА КНОПКИ ВЕБ-ПРИЛОЖЕНИЯ)
# =====================================================================

@bot.message_handler(commands=['start', 'menu'])
def send_menu(message):
    # Создаем кнопку, которая открывает наше веб-приложение
    markup = telebot.types.InlineKeyboardMarkup()
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


# ----------------------------------------------------------------------
# Функция для запуска Flask в отдельном потоке
# ----------------------------------------------------------------------
def run_flask():
    # '0.0.0.0' нужен, если вы будете хостить приложение в интернете
    print(f"🌐 Flask-сервер запущен: {HOSTING_URL}")
    app.run(host='0.0.0.0', port=5000)


# =====================================================================
# 4. ЗАПУСК
# =====================================================================

if __name__ == '__main__':
    # 1. Запускаем Flask в отдельном потоке, чтобы не блокировать бота
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

    # 2. Запускаем бота в главном потоке
    print("🤖 Бот запущен и ожидает сообщений...")
    bot.polling(non_stop=True)