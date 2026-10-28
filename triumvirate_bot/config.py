import os
from dotenv import load_dotenv

# Загружаем секреты из файла .env
load_dotenv()

# Базовый URL платформы MAX
BASE_URL = "https://platform-api2.max.ru"

# Берем токен из скрытой переменной окружения
BOT_TOKEN = os.getenv("MAX_BOT_TOKEN")

HEADERS = {
    "Authorization": BOT_TOKEN,
    "Content-Type": "application/json"
}