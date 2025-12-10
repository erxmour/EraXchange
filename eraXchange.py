# ======================================================================
# ФАЙЛ: eraXChange.py (Currency Exchange Assistant с Gemini)
# ======================================================================

import os
import requests
import telebot
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify
import time
import json
import logging

# --- ИМПОРТ GEMINI ---
from google import genai
from google.genai.errors import APIError

# Настройка логирования
logger = telebot.logger
telebot.logger.setLevel(logging.INFO)

# --- КОНФИГУРАЦИЯ И ЗАГРУЗКА КЛЮЧЕЙ ---
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_KEY = os.getenv("EXCHANGE_RATE_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
API_BASE_URL = f"https://v6.exchangerate-api.com/v6/{API_KEY}/latest/"

# Критическая проверка токенов
if not BOT_TOKEN or not API_KEY:
    raise ValueError("❌ Ошибка: Ключи BOT_TOKEN или EXCHANGE_RATE_API_KEY не загружены.")

# Инициализация клиента Gemini
gemini_client = None
if GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        print("✅ Клиент Gemini API загружен. Функции ИИ активны.")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации клиента Gemini: {e}")
        print("⚠️ Ошибка инициализации клиента Gemini. Функции ИИ будут недоступны.")
else:
    print("⚠️ Ключ GEMINI_API_KEY отсутствует. Функция ИИ будет недоступна.")

# --- КЭШИРОВАНИЕ ДАННЫХ ---
RATE_CACHE = {}
CACHE_EXPIRY = 3600  # 1 час

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)


# ======================================================================
# 2. ФУНКЦИИ УТИЛИТ И ЛОГИКА
# ======================================================================

def get_server_url():
    """
    Автоматически определяет адрес хостинга Render.
    """
    server_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    if server_host:
        return server_host
    else:
        # ЗАМЕНИТЕ ЭТУ ЗАГЛУШКУ НА ВАШ РЕАЛЬНЫЙ ДОМЕН RENDER (БЕЗ https://)
        return "eraxchangex.onrender.com"


def get_exchange_rate(from_currency: str, to_currency: str):
    """Получает курс обмена, используя кэш."""
    cache_key = f"{from_currency}_{to_currency}"
    current_time = time.time()

    if cache_key in RATE_CACHE:
        timestamp, rate = RATE_CACHE[cache_key]
        if current_time - timestamp < CACHE_EXPIRY:
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
        logger.error(f"❌ Ошибка при запросе к API: {e}")
        return None, "NETWORK_ERROR"


def parse_currency_query(text):
    """Использует Gemini для извлечения параметров конвертации (JSON)."""
    if not gemini_client:
        return None, "API_KEY_MISSING"

    # Улучшенный промпт для надежного парсинга
    prompt = f"""
    Задача: Извлечь числовую сумму (amount), исходную валюту (from) и целевую валюту (to) из текста.
    Правила:
    1. Ответ должен быть ТОЛЬКО в чистом JSON-формате, без дополнительного текста или пояснений.
    2. Валюты должны быть в кодах ISO 4217 (USD, EUR, KZT, RUB и т.д.).
    3. Если целевая валюта не указана, используй 'KZT' по умолчанию.
    4. Если сумма не найдена или текст не имеет отношения к конвертации, используй amount: 0.

    Пример ожидаемого формата: {{ "amount": 100, "from": "USD", "to": "KZT" }}

    Запрос пользователя: "{text}"
    """

    try:
        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        )

        json_data = response.text.strip()
        # Удаление Markdown-блока, если Gemini его добавил
        if json_data.startswith('```json') and json_data.endswith('```'):
            json_data = json_data.strip('```json').strip('```').strip()

        return json.loads(json_data), None

    except APIError as e:
        logger.error(f"❌ Ошибка Gemini API: {e}")
        return None, "GEMINI_API_ERROR"
    except json.JSONDecodeError:
        logger.error(f"❌ Ошибка парсинга JSON от Gemini. Получен текст: {response.text}")
        return None, "LLM_PARSE_ERROR"
    except Exception as e:
        logger.error(f"❌ Неизвестная ошибка ИИ при парсинге: {e}")
        return None, "LLM_ERROR"


def get_chat_response(text):
    """Использует Gemini для генерации свободного ответа с контекстом Currency Exchange Assistant."""
    if not gemini_client:
        return "Извините, функция чата недоступна из-за отсутствия ключа Gemini."

    # Инструкция, задающая роль и контекст проекта
    system_prompt = (
        "Ты — дружелюбный и компетентный ассистент по обмену валют для мобильного приложения "
        "'Currency Exchange Assistant'. Твоя цель — помогать пользователям с общими вопросами о валюте, "
        "обмене и рекламировать удобство приложения. Отвечай кратко и информативно."
    )

    try:
        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[system_prompt, text]
        )

        return response.text

    except APIError as e:
        logger.error(f"❌ Ошибка Gemini API в режиме чата: {e}")
        return "Извините, произошла ошибка связи с Gemini API."
    except Exception as e:
        logger.error(f"❌ Неизвестная ошибка в режиме чата: {e}")
        return "Произошла внутренняя ошибка при обработке вашего запроса."


# ======================================================================
# 3. НАСТРОЙКА АДРЕСОВ И ПУТЕЙ
# ======================================================================

SERVER_HOST = get_server_url()
WEBHOOK_PATH = f"/{BOT_TOKEN}"
WEBHOOK_URL = f"https://{SERVER_HOST}{WEBHOOK_PATH}"
HOSTING_URL = f"https://{SERVER_HOST}"


# ======================================================================
# 4. FLASK API (МАРШРУТЫ)
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
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        return '', 403


@bot.message_handler(commands=['start', 'menu'])
def send_menu(message):
    markup = telebot.types.InlineKeyboardMarkup()
    web_app_info = telebot.types.WebAppInfo(HOSTING_URL)

    markup.add(
        telebot.types.InlineKeyboardButton(
            text="🚀 Открыть Калькулятор Валют",
            web_app=web_app_info
        )
    )

    bot.send_message(
        message.chat.id,
        "Привет! Я ваш помощник по обмену валют. Вы можете:\n"
        "1. Открыть мини-приложение для быстрой конвертации.\n"
        "2. Просто написать мне сумму и валюты (например: 100 долларов в тенге).\n"
        "3. Задать любой вопрос о валюте или обмене!",
        reply_markup=markup
    )


@bot.message_handler(content_types=['text'])
def handle_text_query(message):
    """
    Обрабатывает текстовые запросы: выполняет конвертацию или переключается в режим чата.
    """
    if not gemini_client:
        bot.send_message(message.chat.id, "❌ Функции ИИ недоступны.")
        return

    chat_id = message.chat.id
    query_text = message.text

    bot.send_chat_action(chat_id, 'typing')

    # Шаг 1: Попытка парсинга как конвертации
    params, error = parse_currency_query(query_text)

    is_conversion = False
    amount = 0.0

    if not error and params is not None:
        try:
            # Если сумма больше 0, считаем это конвертацией
            amount = float(params.get('amount', 0))
            is_conversion = amount > 0
        except:
            pass

    # Обработка ошибок API при парсинге
    if error in ["GEMINI_API_ERROR", "LLM_PARSE_ERROR"]:
        bot.send_message(chat_id,
                         "Извините, произошла ошибка связи с Gemini API или не удалось разобрать ответ. Попробуйте перефразировать.")
        return

    # --- РЕЖИМ КОНВЕРТАЦИИ ---
    if is_conversion:
        try:
            from_currency = params.get('from', 'USD').upper()
            to_currency = params.get('to', 'KZT').upper()

            rate, conv_error = get_exchange_rate(from_currency, to_currency)

            if conv_error:
                response_text = f"❌ Не удалось получить курс для {from_currency} к {to_currency}."
            else:
                result = amount * rate
                response_text = (
                    f"🤖 Расчет по запросу:\n"
                    f"**{amount:,.2f} {from_currency}** = **{result:,.2f} {to_currency}**\n"
                    f"Текущий курс: 1 {from_currency} = {rate:,.4f} {to_currency}"
                )

            bot.send_message(chat_id, response_text, parse_mode='Markdown')

        except Exception:
            # Если произошла ошибка при конвертации, переключаемся в режим чата
            is_conversion = False

            # --- РЕЖИМ ЧАТА (если это не конвертация, ошибка парсинга или общий вопрос) ---
    if not is_conversion:
        chat_response = get_chat_response(query_text)

        if chat_response:
            bot.send_message(chat_id, chat_response)
        else:
            bot.send_message(chat_id, "Извините, я не смог ответить. Возможно, произошла ошибка ИИ.")


# ======================================================================
# 6. ЗАПУСК И НАСТРОЙКА WEBHOOKS
# ======================================================================

def setup_webhook():
    """Настраивает вебхук для работы на Render."""
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"✅ Webhook установлен: {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"❌ Ошибка при настройке Webhook: {e}")


if __name__ == '__main__':
    # ЛОКАЛЬНОЕ ТЕСТИРОВАНИЕ (Polling)
    try:
        bot.remove_webhook()
    except Exception as e:
        logger.error(f"❌ Ошибка при удалении вебхука: {e}")

    print("🤖 Бот запущен в режиме Polling (локальный тест)...")
    bot.polling(non_stop=True, interval=0)

else:
    # ЗАПУСК НА RENDER (Gunicorn/Webhook)
    print("🚀 Приложение запущено на Render (Gunicorn). Настройка Webhook...")
    setup_webhook()