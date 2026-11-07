import base64
import io
import logging
import requests
import urllib3
from PIL import Image
from openai import OpenAI

# Импортируем настройки и промпты из config.py
from config import (
    BASE_URL, 
    HEADERS, 
    LM_STUDIO_URL, 
    REQUEST_TIMEOUT, 
    STOP_WORDS, 
    SYSTEM_PROMPTS
)

# Настройка логирования по стандарту PEP8
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# Отключаем предупреждения SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Подключаемся к локальному серверу LM Studio (OpenAI-совместимый API)
client = OpenAI(
    base_url="http://host.docker.internal:1234/v1",
    api_key="not-needed"  # Для локальной LM Studio ключ не нужен
)

# --- ХРАНИЛИЩЕ СОСТОЯНИЙ ---
user_histories = {}  # {user_id: [{"role": "user/assistant", "content": "..."}]}
user_roles = {}      # {user_id: "socrates" | "analyst" | "examiner"}
MAX_HISTORY_LENGTH = 6


def download_image_as_base64(url):
    """Скачивание изображения, конвертация в JPEG и перевод в base64."""
    try:
        resp = requests.get(url, headers=HEADERS, verify=False, timeout=15)
        if resp.status_code == 200:
            image = Image.open(io.BytesIO(resp.content)).convert("RGB")
            buffered = io.BytesIO()
            image.save(buffered, format="JPEG")
            return base64.b64encode(buffered.getvalue()).decode('utf-8')
    except Exception as e:
        logger.error(f"Ошибка конвертации картинки: {e}")
    return None


def ask_local_ai(user_id, user_text, image_base64=None):
    """Запрос к локальной LM Studio с поддержкой текста и изображений."""
    role = user_roles.get(user_id, "socrates")
    system_prompt = SYSTEM_PROMPTS.get(role, SYSTEM_PROMPTS["socrates"])
    
    if user_id not in user_histories:
        user_histories[user_id] = []
        
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(user_histories[user_id])
    
    if image_base64:
        user_content = [
            {"type": "text", "text": user_text if user_text else "Посмотри на это изображение и помоги разобраться."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
        ]
    else:
        user_content = user_text

    messages.append({"role": "user", "content": user_content})
    
    if role == "socrates":
        current_max_tokens = 300
    elif role == "examiner":
        current_max_tokens = 900
    else:
        current_max_tokens = 1000
    
    payload = {
        "model": "qwen/qwen2.5-vl-7b",
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": current_max_tokens,
        "stream": False
    }
    
    try:
        logger.info("⏳ Отправка запроса с медиа в LM Studio...")
        response = requests.post(LM_STUDIO_URL, json=payload, timeout=REQUEST_TIMEOUT)
        
        if response.status_code == 200:
            data = response.json()
            reply_text = data["choices"][0]["message"]["content"]
            logger.info("✅ Ответ по картинке успешно получен!")
            
            user_histories[user_id].append({"role": "user", "content": user_text or "[Картинка с задачей]"})
            user_histories[user_id].append({"role": "assistant", "content": reply_text})
            
            if len(user_histories[user_id]) > MAX_HISTORY_LENGTH * 2:
                user_histories[user_id] = user_histories[user_id][-MAX_HISTORY_LENGTH * 2:]
                
            return reply_text
        else:
            logger.error(f"❌ Ошибка сервера нейросети: {response.status_code}")
            return (
                "🔍 **Не удалось разобрать изображение.**\n\n"
                "Возможно, фотография слишком размыта или почерк неразборчив. "
                "Пожалуйста, сделайте более четкое фото при хорошем освещении или отправьте задание текстом!"
            )
            
    except Exception as e:
        logger.error(f"❌ Ошибка соединения: {e}")
        return (
            "📷 **Ой, не получилось прочитать фото.**\n\n"
            "К сожалению, не удалось обработать картинку. "
            "Попробуйте отправить фото повторно или сфотографировать фрагмент крупнее."
        )


# --- API МЕТОДЫ MAX ---

def send_message(chat_id, text, attachments=None):
    """Отправка сообщения через API МАКС с поддержкой Markdown."""
    url = f"{BASE_URL}/messages"
    params = {"chat_id": chat_id}
    
    payload = {
        "text": text,
        "format": "markdown"
    }
    
    if attachments:
        payload["attachments"] = attachments
    
    try:
        response = requests.post(url, headers=HEADERS, params=params, json=payload, verify=False)
        logger.info(f"Статус отправки: {response.status_code}")
    except Exception as e:
        logger.error(f"Ошибка при отправке: {e}")


def get_updates(marker=None):
    """Получение событий через Long Polling."""
    url = f"{BASE_URL}/updates"
    params = {"marker": marker} if marker else {}
        
    try:
        response = requests.get(url, headers=HEADERS, params=params, verify=False, timeout=30)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return {}


# --- ОСНОВНАЯ ЛОГИКА ---

def process_message(user_id, chat_id, user_text, image_base64=None):
    """Обработка команд и генерация ответа через нейросеть."""
    if user_id not in user_roles:
        user_roles[user_id] = "socrates"

    cmd = user_text.strip().lower()

    if cmd in ["/start", "/help", "помощь", "меню", "старт"]:
        reply = (
            "🏛️ **Добро пожаловать в «Триумвират знаний»!**\n\n"
            "Выбери наставника, нажав на кнопку ниже:"
        )
        attachments = [
            {
                "type": "inline_keyboard",
                "payload": {
                    "buttons": [
                        [
                            {"type": "message", "text": "🏛️ Сократ", "payload": "1"},
                            {"type": "message", "text": "📊 Аналитик", "payload": "2"}
                        ],
                        [
                            {"type": "message", "text": "📝 Проверяющий", "payload": "3"}
                        ]
                    ]
                }
            }
        ]
        send_message(chat_id, reply, attachments=attachments)
        return

    if cmd in ["1", "сократ", "/socrates", "🏛️ сократ"]:
        user_roles[user_id] = "socrates"
        user_histories[user_id] = []
        reply = (
            "🏛️ Активирован режим: **Сократ** (Мудрый наставник)\n\n"
            "🎓 Напиши, в каком ты классе и какую школьную тему или задачу разбираем? "
            "*(Сюда можно прикрепить фото с условием задачи!)*"
        )
        send_message(chat_id, reply)
        return

    elif cmd in ["2", "аналитик", "/analyst", "📊 аналитик"]:
        user_roles[user_id] = "analyst"
        user_histories[user_id] = []
        reply = (
            "📊 Активирован режим: **Аналитик** (Мастер структуры)\n\n"
            "🎓 Укажи класс и пришли текст или фото страницы параграфа, которую нужно сжать в тезисы."
        )
        send_message(chat_id, reply)
        return

    elif cmd in ["3", "проверяющий", "/examiner", "📝 проверяющий"]:
        user_roles[user_id] = "examiner"
        user_histories[user_id] = []
        reply = (
            "📝 Активирован режим: **Проверяющий** (Экзаменатор)\n\n"
            "🎓 В каком ты классе и по какой школьной теме подготовить мини-тест из 6 вопросов?"
        )
        send_message(chat_id, reply)
        return

    # Глобальный стоп-фильтр
    text_lower = user_text.lower()
    if any(word in text_lower for word in STOP_WORDS):
        reply_text = "🛡️ Этот запрос нарушает правила академической безопасности. Пожалуйста, задай вопрос по школьной программе."
        send_message(chat_id, reply_text)
        return

    if cmd in ["еще", "ещё", "продолжить", "дальше"] and user_roles.get(user_id) == "examiner":
        user_text = "Сгенерируй следующие ровно 6 новых вопросов по нашей текущей теме."
    
    if user_roles.get(user_id) == "analyst":
        if not image_base64 and (len(user_text) < 60 or "?" in user_text):
            reply_text = "📊 Режим «Аналитик» принимает на обработку только учебные параграфы школьной программы (от 60 символов, без вопросов) или фотографии страниц."
            send_message(chat_id, reply_text)
            return

    logger.info(f"[{user_id}] Запрос к нейросети в роли [{user_roles[user_id]}]: текст='{user_text}', есть фото={bool(image_base64)}")
    send_message(chat_id, "⏳ Секунду, наставник изучает материал...")
    
    reply_text = ask_local_ai(user_id, user_text, image_base64)
    send_message(chat_id, reply_text)


def poll_updates():
    marker = None
    logger.info("Запуск инициализации бота «Триумвират знаний» с локальной нейросетью...")
    try:
        me_resp = requests.get(f"{BASE_URL}/me", headers=HEADERS, verify=False)
        if me_resp.status_code == 200:
            logger.info(f"Бот успешно запущен: @{me_resp.json().get('username')}")
    except Exception as e:
        logger.error(f"Ошибка инициализации: {e}")

    logger.info("Бот слушает входящие сообщения...\n")
    
    while True:
        data = get_updates(marker)
        if "marker" in data:
            marker = data["marker"]
            
        for update in data.get("updates", []):
            if update.get("update_type") == "message_created":
                msg_data = update.get("message", {})
                chat_id = msg_data.get("recipient", {}).get("chat_id")
                user_id = msg_data.get("sender", {}).get("user_id")
                
                body = msg_data.get("body", {})
                user_text = body.get("text", "")
                
                image_base64 = None
                attachments = msg_data.get("attachments", []) or body.get("attachments", [])
                
                for att in attachments:
                    if att.get("type") in ["photo", "image"]:
                        photo_url = att.get("payload", {}).get("url") or att.get("url")
                        if photo_url:
                            logger.info("📷 Обнаружена фотография, скачиваем и конвертируем...")
                            image_base64 = download_image_as_base64(photo_url)
                            if not image_base64:
                                send_message(
                                    chat_id, 
                                    "⚠️ **Не удалось загрузить изображение.** Пожалуйста, отправьте фото еще раз."
                                )
                                return
                            if not user_text:
                                user_text = "Вот условие задачи на картинке. Помоги мне её разобрать."
                            break

                if user_id and (user_text or image_base64):
                    process_message(user_id, chat_id, user_text, image_base64)


if __name__ == "__main__":
    poll_updates()