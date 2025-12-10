# ======================================================================
# ФАЙЛ: eraXChange.py (ПОЛНЫЙ КОД С ИНТЕГРАЦИЕЙ GEMINI)
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
from google.genai.errors import APIError  # Для обработки ошибок API

# Настройка логирования
logger = telebot.logger
telebot.logger.setLevel(logging.INFO)

# --- КОНФИГУРАЦИЯ И ЗАГРУЗКА КЛЮЧЕЙ ---
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_KEY = os.getenv("EXCHANGE_RATE_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")  # <-- Новый ключ
API_BASE_URL = f"https://v6.exchangerate-api.com/v6/{API_KEY}/latest/"

# Критическая проверка токенов
if not BOT_TOKEN or not API_KEY:
    raise ValueError("❌ Ошибка: Ключи BOT_TOKEN или EXCHANGE_RATE_API_KEY не загружены.")

# Инициализация клиента Gemini
gemini_client = None
if GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        print("✅ Клиент Gemini API загружен. Функции НЛП активны.")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации клиента Gemini: {e}")
        print("⚠️ Ошибка инициализации клиента Gemini. Функции НЛП будут недоступны.")
else:
    print("⚠️ Ключ GEMINI_API_KEY отсутствует. Функция НЛП будет недоступна.")

# --- КЭШИРОВАНИЕ ДАННЫХ ---
RATE_CACHE = {}
CACHE_EXPIRY = 3600

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)


# ======================================================================
# 2. ФУНКЦИИ УТИЛИТ И ЛОГИКА
# ======================================================================

def get_server_url():
    # ... (функция остается без изменений)
    server_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    if server_host:
        return server_host
    else:
        return "YOUR-RENDER-DOMAIN.onrender.com"


def get_exchange_rate(from_currency: str, to_currency: str):
    # ... (функция остается без изменений)
    cache_key = f"{from_currency}_{to_currency}"
    current_time = time.time()
    # ... (логика кэша и API) ...
    url = f"{API_BASE_URL}{from_currency.upper()}"
    try:
        response = requests.get(url, timeout=10)
        # ... (остальной код API) ...
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
    """Использует Gemini для извлечения параметров конвертации из текста."""
    if not gemini_client:
        return None, "API_KEY_MISSING"

    # Улучшенный промпт для надежного парсинга
    prompt = f"""
    Задача: Извлечь числовую сумму (amount), исходную валюту (from) и целевую валюту (to) из текста.
    Правила:
    1. Ответ должен быть ТОЛЬКО в чистом JSON-формате, без дополнительного текста или пояснений.
    2. Валюты должны быть в кодах ISO 4217 (USD, EUR, KZT, RUB и т.д.).
    3. Если целевая валюта не указана, используй 'KZT' по умолчанию.
    4. Если сумма не найдена, используй 0.

    Пример ожидаемого формата: {{ "amount": 100, "from": "USD", "to": "KZT" }}

    Запрос пользователя: "{text}"
    """

    try:
        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',  # Модель Gemini для быстрых задач
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                # Указываем, что ждем ответ в JSON
                response_mime_type="application/json",
            )
        )

        json_data = response.text.strip()  # Получаем чистый JSON-текст

        # Иногда Gemini оборачивает ответ в Markdown-блок, удалим его
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
        logger.error(f"❌ Неизвестная ошибка ИИ: {e}")
        return None, "LLM_ERROR"


# ======================================================================
# 3. НАСТРОЙКА АДРЕСОВ И ПУТЕЙ
# ... (остается без изменений) ...

# ======================================================================
# 4. FLASK API (МАРШРУТЫ)
# ... (остается без изменений) ...


# ======================================================================
# 5. TELEGRAM WEBHOOKS И ОБРАБОТЧИКИ
# ... (webhook, send_menu остаются без изменений) ...


@bot.message_handler(content_types=['text'])
def handle_text_query(message):
    """Обрабатывает текстовые запросы пользователя с помощью Gemini."""
    if not gemini_client:
        bot.send_message(message.chat.id, "❌ Функция текстового запроса недоступна: отсутствует ключ Gemini.")
        return

    chat_id = message.chat.id
    query_text = message.text

    bot.send_chat_action(chat_id, 'typing')

    params, error = parse_currency_query(query_text)

    # Добавляем обработку новых ошибок
    if error in ["LLM_PARSE_ERROR", "GEMINI_API_ERROR"]:
        bot.send_message(chat_id,
                         "Извините, Gemini не смог обработать запрос или произошла ошибка API. Попробуйте перефразировать.")
        return
    if error == "LLM_ERROR" or params is None:
        bot.send_message(chat_id, "Извините, ИИ не смог обработать ваш запрос. Попробуйте перефразировать.")
        return

    try:
        amount = float(params.get('amount'))
        from_currency = params.get('from', 'USD').upper()
        to_currency = params.get('to', 'KZT').upper()
    except (ValueError, TypeError):
        bot.send_message(chat_id, "Не могу распознать сумму. Убедитесь, что запрос четкий (например: '100 USD в KZT').")
        return

    rate, conv_error = get_exchange_rate(from_currency, to_currency)

    if conv_error:
        bot.send_message(chat_id, f"❌ Не удалось получить курс для {from_currency} к {to_currency}.")
        return

    result = amount * rate

    response_text = (
        f"🤖 Расчет по запросу (через Gemini):\n"
        f"**{amount:,.2f} {from_currency}** = **{result:,.2f} {to_currency}**\n"
        f"Текущий курс: 1 {from_currency} = {rate:,.4f} {to_currency}"
    )
    bot.send_message(chat_id, response_text, parse_mode='Markdown')


# ======================================================================
# 6. ЗАПУСК И НАСТРОЙКА WEBHOOKS
# ... (остается без изменений) ...
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