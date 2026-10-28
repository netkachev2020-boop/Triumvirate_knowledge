import requests
import urllib3
from openai import OpenAI
from config import BASE_URL, HEADERS

# Отключаем предупреждения SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Подключаемся к локальному серверу LM Studio ( OpenAI-совместимый API )
client = OpenAI(
    base_url="http://localhost:1234/v1",
    api_key="not-needed"  # Для локальной LM Studio ключ не нужен
)

# --- ХРАНИЛИЩЕ СОСТОЯНИЙ ---
user_histories = {}  # {user_id: [{"role": "user/assistant", "content": "..."}]}
user_roles = {}      # {user_id: "socrates" | "analyst" | "examiner"}
MAX_HISTORY_LENGTH = 6

# --- СИСТЕМНЫЕ ПРОМПТЫ ДЛЯ РОЛЕЙ ---
SYSTEM_PROMPTS = {
    "socrates": (
        "Ты — Сократ, мудрый наставник. Если ученик присылает сложную задачу или вопрос, "
        "не давай ему готовый ответ. Задавай простые наводящие вопросы, которые шаг за шагом "
        "подталкивают ученика к правильному выводу. Отвечай коротко и по делу на русском языке."
    ),
    "analyst": (
        "Ты — Аналитик, мастер структуры. Твоя задача — брать длинный сложный текст или параграф, "
        "который присылает пользователь, и сжимать его до четкой краткой сводки из главных тезисов "
        "в виде маркерного списка. Отвечай на русском языке."
    ),
   "examiner": (
        "Ты — Проверяющий, интерактивный экзаменатор. По запросу пользователя (теме или понятию) "
        "генерируй ровно 6 мини-тестов и карточек для самопроверки за один раз. "
        "Пиши лаконично. В самом конце обязательно добавь фразу: 'Хочешь еще вопросы? Напиши \"еще\"!'. "
        "Отвечай на русском языке."
    )
}

def ask_local_ai(user_id, user_text):
    """Надежный прямой запрос к локальной LM Studio через HTTP"""
    role = user_roles.get(user_id, "socrates")
    system_prompt = SYSTEM_PROMPTS.get(role, SYSTEM_PROMPTS["socrates"])
    
    if user_id not in user_histories:
        user_histories[user_id] = []
        
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(user_histories[user_id])
    messages.append({"role": "user", "content": user_text})
    
    url = "http://localhost:1234/v1/chat/completions"
    payload = {
        "model": "qwen/qwen2.5-vl-7b",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 600,
        "stream": False
    }
    
    try:
        print("⏳ Шлем HTTP-запрос в LM Studio...")
        response = requests.post(url, json=payload, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            reply_text = data["choices"][0]["message"]["content"]
            print("✅ Ответ успешно получен!")
            
            user_histories[user_id].append({"role": "user", "content": user_text})
            user_histories[user_id].append({"role": "assistant", "content": reply_text})
            
            if len(user_histories[user_id]) > MAX_HISTORY_LENGTH * 2:
                user_histories[user_id] = user_histories[user_id][-MAX_HISTORY_LENGTH * 2:]
                
            return reply_text
        else:
            print(f"❌ Ошибка ответа сервера: {response.status_code} - {response.text}")
            return "⚠️ Ошибка сервера нейросети."
            
    except Exception as e:
        print(f"❌ Ошибка соединения: {e}")
        return "⚠️ Не удалось связаться с локальной нейросетью."

# --- API МЕТОДЫ MAX ---

def send_message(chat_id, text):
    """Отправка сообщения через API платформы MAX"""
    url = f"{BASE_URL}/messages"
    params = {"chat_id": chat_id}
    payload = {"text": text}
    
    try:
        response = requests.post(url, headers=HEADERS, params=params, json=payload, verify=False)
        print(f"Статус отправки: {response.status_code}")
    except Exception as e:
        print(f"Ошибка при отправке: {e}")

def get_updates(marker=None):
    """Получение событий через Long Polling"""
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

def process_message(user_id, chat_id, user_text):
    """Обработка команд и генерация ответа через нейросеть"""
    if user_id not in user_roles:
        user_roles[user_id] = "socrates"

    cmd = user_text.strip().lower()

    # Меню выбора по команде /start или /help
    if cmd in ["/start", "/help", "помощь", "меню", "старт"]:
        reply = (
            "🏛️ **Добро пожаловать в «Триумвират знаний»!**\n\n"
            "Выбери наставника, с которым хочешь продолжить работу:\n\n"
            "1️⃣ **Сократ** — мудрый наставник, помогает найти ответ наводящими вопросами.\n"
            "2️⃣ **Аналитик** — мастер структуры, сжимает длинные параграфы в тезисы.\n"
            "3️⃣ **Проверяющий** — экзаменатор, генерирует тесты и карточки.\n\n"
            "✍️ *Просто отправь цифру (1, 2, 3) или название (Сократ, Аналитик, Проверяющий)!*"
        )
        send_message(chat_id, reply)
        return

    # Переключение ролей
    if cmd in ["1", "сократ", "/socrates"]:
        user_roles[user_id] = "socrates"
        user_histories[user_id] = []  # Сбрасываем историю при смене роли
        reply = "🏛️ **Активирован режим: Сократ (Мудрый наставник)**\nОтправь условие задачи, и мы начнем поиск решения!"
        send_message(chat_id, reply)
        return

    elif cmd in ["2", "аналитик", "/analyst"]:
        user_roles[user_id] = "analyst"
        user_histories[user_id] = []
        reply = "📊 **Активирован режим: Аналитик (Мастер структуры)**\nПришли длинный параграф, и я сделаю краткую сводку."
        send_message(chat_id, reply)
        return

    elif cmd in ["3", "проверяющий", "/examiner"]:
        user_roles[user_id] = "examiner"
        user_histories[user_id] = []
        reply = "📝 **Активирован режим: Проверяющий (Экзаменатор)**\nНапиши тему, и я подготовлю мини-тест для самопроверки."
        send_message(chat_id, reply)
        return
    cmd_lower = user_text.strip().lower()

    # Обработка запроса на продолжение теста
    if cmd_lower in ["еще", "ещё", "продолжить", "дальше"]:
        user_text = "Сгенерируй следующие ровно 6 новых вопросов по нашей текущей теме."
        
   # Генерация ответа через локальную нейросеть
    print(f"[{user_id}] Запрос к нейросети в роли [{user_roles[user_id]}]: '{user_text}'")
    
    # Сразу отправляем пользователю весточку, что бот начал работу
    send_message(chat_id, "⏳ Секунду, наставник обдумывает ответ...")
    
    # Получаем ответ от локальной нейросети
    reply_text = ask_local_ai(user_id, user_text)
    
    # Отправляем готовый ответ
    send_message(chat_id, reply_text)

def poll_updates():
    marker = None
    print("Запуск инициализации бота «Триумвират знаний» с локальной нейросетью...")
    try:
        me_resp = requests.get(f"{BASE_URL}/me", headers=HEADERS, verify=False)
        if me_resp.status_code == 200:
            print(f"Бот успешно запущен: @{me_resp.json().get('username')}")
    except Exception as e:
        print(f"Ошибка инициализации: {e}")

    print("Бот слушает входящие сообщения...\n")
    
    while True:
        data = get_updates(marker)
        if "marker" in data:
            marker = data["marker"]
            
        for update in data.get("updates", []):
            if update.get("update_type") == "message_created":
                msg_data = update.get("message", {})
                chat_id = msg_data.get("recipient", {}).get("chat_id")
                user_id = msg_data.get("sender", {}).get("user_id")
                user_text = msg_data.get("body", {}).get("text", "")

                if user_id and user_text:
                    process_message(user_id, chat_id, user_text)

if __name__ == "__main__":
    poll_updates()