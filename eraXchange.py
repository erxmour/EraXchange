# ======================================================================
# ФАЙЛ: eraXchange.py (или main.py)
# Версия для Продакшен на Render (Webhooks) с кэшированием И ИИ
# ======================================================================

import os
import requests
import telebot
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify
import time
# >>> ИЗМЕНЕНИЕ: Импорт для работы с ИИ
import openai
import json

# --- КОНФИГУРАЦИЯ ---
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_KEY = os.getenv("EXCHANGE_RATE_API_KEY")
# >>> ИЗМЕНЕНИЕ: Загрузка ключа OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
API_BASE_URL = f"https://v6.exchangerate-api.com/v6/{API_KEY}/latest/"

if not BOT_TOKEN or not API_KEY:
    raise ValueError("❌ Ошибка: Ключи BOT_TOKEN или EXCHANGE_RATE_API_KEY не загружены из .env")

# >>> ИЗМЕНЕНИЕ: Инициализация OpenAI
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY
    print("✅ Ключ OpenAI загружен.")
else:
    print("⚠️ Ключ OPENAI_API_KEY отсутствует. Функция НЛП будет недоступна.")

# --- КЭШИРОВАНИЕ ДАННЫХ ---
RATE_CACHE = {}
CACHE_EXPIRY = 3600  # 1 час в секундах

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)


# ======================================================================
# 2. ФУНКЦИИ УТИЛИТ И ЛОГИКА
# ======================================================================

def get_server_url():
    """Автоматически определяет адрес хостинга Render или использует запасной вариант."""
    server_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    if server_host:
        return server_host
    else:
        # ВАЖНО: Удаляем 'https://' из этого блока, чтобы избежать ошибки "https://https://"
        # SERVER_HOST должен быть чистым доменом!
        return "eraxchangex.onrender.com"


def get_exchange_rate(from_currency: str, to_currency: str):
    """Получает курс обмена, используя кэш."""
    # (Логика get_exchange_rate остается без изменений)
    cache_key = f"{from_currency}_{to_currency}"
    current_time = time.time()

    if cache_key in RATE_CACHE:
        timestamp, rate = RATE_CACHE[cache_key]
        if current_time - timestamp < CACHE_EXPIRY:
            print(f"✅ Используем кэшированный курс для {cache_key}")
            return rate, None

    url = f"{API_BASE_URL}{from_currency.upper()}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("result") != "success": return None, "API_ERROR"

        rate = data["conversion_rates"].get(to_currency.upper())

        if rate is None: return None, "CURRENCY_NOT_FOUND"

        RATE_CACHE[cache_key] = (current_time, rate)
        return rate, None

    except requests.exceptions.RequestException as e:
        print(f"❌ Ошибка при запросе к API: {e}")
        return None, "NETWORK_ERROR"


# >>> ИЗМЕНЕНИЕ: Новая функция для парсинга запроса через ИИ
def parse_currency_query(text):
    """Использует LLM для извлечения параметров конвертации из текста."""
    if not OPENAI_API_KEY:
        return None, "API_KEY_MISSING"

    prompt = f"""
    Извлеки сумму (amount), исходную валюту (from) и целевую валюту (to) из следующего запроса пользователя. 
    Используй коды ISO 4217 (USD, KZT, EUR). Если целевая валюта не указана, используй 'KZT' по умолчанию. 
    Ответ дай ТОЛЬКО в формате JSON, без пояснений:
    Запрос: "{text}"
    """

    try:
        # Убедитесь, что у вас установлена последняя библиотека openai
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )

        json_data = response.choices[0].message.content
        return json.loads(json_data), None

    except Exception as e:
        print(f"❌ Ошибка LLM при парсинге: {e}")
        return None, "LLM_ERROR"


# ======================================================================
# 3. НАСТРОЙКА АДРЕСОВ И ПУТЕЙ
# ======================================================================

SERVER_HOST = get_server_url()
WEBHOOK_PATH = f"/{BOT_TOKEN}"
WEBHOOK_URL = f"https://{SERVER_HOST}{WEBHOOK_PATH}"
HOSTING_URL = f"https://{SERVER_HOST}"


# ======================================================================
# 4. FLASK API (МАРШРУТЫ) - Без изменений
# ======================================================================

@app.route('/')
def serve_web_app():
    return render_template('index.html')


@app.route('/api/exchange', methods=['POST'])
def exchange_api():
    # ... (логика API остается без изменений)
    data = request.json
    try:
        amount = float(data.get('amount', 0))
        from_currency = data.get('from', 'USD').upper()
        to_currency = data.get('to', 'KZT').upper()
        if amount <= 0: return jsonify({'error': 'Неверная сумма'}), 400
    except Exception:
        return jsonify({'error': 'Неверный формат данных'}), 400

    rate, error = get_exchange_rate(from_currency, to_currency)

    if error:
        error_msg = {
            "NETWORK_ERROR": "Ошибка сети. Проверьте подключение.",
            "API_ERROR": "Ошибка внешнего API-сервиса.",
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

@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    # (логика вебхука остается без изменений)
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        return '', 403


@bot.message_handler(commands=['start', 'menu'])
def send_menu(message):
    # (логика команды /start остается без изменений)
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


# >>> ИЗМЕНЕНИЕ: Новый обработчик для любого текста (НЛП)
@bot.message_handler(content_types=['text'])
def handle_text_query(message):
    if not OPENAI_API_KEY:
        bot.send_message(message.chat.id, "❌ Функция текстового запроса недоступна: отсутствует ключ ИИ.")
        return

    chat_id = message.chat.id
    query_text = message.text

    bot.send_chat_action(chat_id, 'typing')  # Показываем, что бот "печатает"

    # 1. Парсинг запроса с помощью ИИ
    params, error = parse_currency_query(query_text)

    if error == "LLM_ERROR" or params is None:
        bot.send_message(chat_id, "Извините, ИИ не смог обработать ваш запрос. Попробуйте перефразировать.")
        return

    try:
        amount = float(params.get('amount'))
        from_currency = params.get('from', 'USD').upper()
        to_currency = params.get('to', 'KZT').upper()
    except:
        bot.send_message(chat_id,
                         "Не могу распознать сумму, исходную или целевую валюту. Убедитесь, что запрос четкий (например, '100 USD в KZT').")
        return

    # 2. Выполнение конвертации
    rate, conv_error = get_exchange_rate(from_currency, to_currency)

    if conv_error:
        bot.send_message(chat_id, f"❌ Не удалось получить курс для {from_currency} к {to_currency}.")
        return

    result = amount * rate

    # 3. Отправка результата
    response_text = f"🤖 Расчет по запросу:\n**{amount:,.2f} {from_currency}** = **{result:,.2f} {to_currency}**\nТекущий курс: 1 {from_currency} = {rate:,.4f} {to_currency}"
    bot.send_message(chat_id, response_text, parse_mode='Markdown')


# ======================================================================
# 6. ЗАПУСК - Без изменений
# ======================================================================

if __name__ == '__main__':
    # Эта часть выполняется ТОЛЬКО при локальном запуске (для тестов!)

    bot.remove_webhook()

    print("🤖 Бот запущен в режиме Polling (локальный тест)...")
    bot.polling(non_stop=True, interval=0)