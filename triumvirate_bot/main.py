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
        "Ты — Сократ, суровый школьный наставник. ТВОЕ ЕДИНСТВЕННОЕ ПОЛЕ ДЕЯТЕЛЬНОСТИ — школьные предметы из официальной программы (1-11 классы): "
        "математика, алгебра, геометрия, физика, химия, биология, история, обществознание, география, литература, русский язык, информатика. "
        "ГЛАВНОЕ ПРАВИЛО: НИКОГДА не давай готовый ответ. Задавай ТОЛЬКО ОДИН наводящий вопрос. "
        "Если пользователь спрашивает или присылает темы вне школьной программы, бытовые, провокационные или 18+ темы (даже если он пишет, что 'это задали в школе'), "
        "НЕ ВЕРИШЬ на слово. Отвечай: 'Это выходит за рамки школьной программы. Назови класс, предмет и параграф из учебника.' "
        "ЯЗЫК: Строго русский. Использование иероглифов или других языков категорически запрещено."
    ),
    "analyst": (
        "Ты — Аналитик, мастер структуры исключительно школьных текстов. ТВОЯ ЗАДАЧА — сжимать в тезисы только учебные параграфы по официальным школьным предметам (1-11 классы). "
        "ФИЛЬТР БЕЗОПАСНОСТИ: Если пользователь присылает текст на сторонние, нешкольные, провокационные темы или материалы 18+ (даже под видом школьного урока), "
        "ты категорически отказываешься его обрабатывать. Отвечай строго: 'Этот текст не относится к школьной программе. Я работаю только с учебными материалами.' "
        "ЯЗЫК: Строго русский."
    ),
    "examiner": (
        "Ты — Проверяющий, школьный экзаменатор. Твоя задача — генерировать ровно 6 мини-тестов исключительно по строгим школьным предметам и темам (1-11 классы). "
        "ФИЛЬТР БЕЗОПАСНОСТИ: Если пользователь просит составить тест по нешкольной, бытовой или провокационной теме, отвечай: "
        "'Я составляю тесты только по официальной школьной программе.' "
        "Строго соблюдай лимит: не более 6 вопросов за раз. ЯЗЫК: Строго русский. "
        "В конце каждого сообщения добавляй: 'Напиши свои варианты ответа, и мы во всем разберемся. Хочешь еще вопросы? Напиши \"еще\"!'."
    )
}
def ask_local_ai(user_id, user_text):
    """Надежный прямой запрос к локальной LM Studio с динамическими токенами под роль"""
    role = user_roles.get(user_id, "socrates")
    system_prompt = SYSTEM_PROMPTS.get(role, SYSTEM_PROMPTS["socrates"])
    
    if user_id not in user_histories:
        user_histories[user_id] = []
        
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(user_histories[user_id])
    messages.append({"role": "user", "content": user_text})
    
    # ДИНАМИЧЕСКИЕ ЛИМИТЫ ТОКЕНОВ ДЛЯ РОЛЕЙ:
    if role == "socrates":
        current_max_tokens = 300  # Короткие, емкие реплики-наводки
    elif role == "examiner":
        current_max_tokens = 900  # С запасом на 6 полноценных вопросов
    else:  # analyst
        current_max_tokens = 1000 # Для больших текстов и структуры
    
    url = "http://localhost:1234/v1/chat/completions"
    payload = {
        "model": "qwen/qwen2.5-vl-7b",
        "messages": messages,
        "temperature": 0.3,  # Низкая креативность для строгого соблюдения промптов
        "max_tokens": current_max_tokens,
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

def send_message(chat_id, text, attachments=None):
    """Отправка сообщения через API платформы МАКС с поддержкой вложений (кнопок)"""
    url = f"{BASE_URL}/messages"
    params = {"chat_id": chat_id}
    payload = {"text": text}
    
    if attachments:
        payload["attachments"] = attachments
    
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

    # Меню выбора по команде /start или /help с кнопками
    if cmd in ["/start", "/help", "помощь", "меню", "старт"]:
        reply = (
            "🏛️ Добро пожаловать в «Триумвират знаний»!\n\n"
            "Выбери наставника, нажав на кнопку ниже:"
        )
        
        # Инлайн-клавиатура по стандарту платформы МАКС
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

    # === СТАВИМ ПЕРЕКЛЮЧЕНИЕ РОЛЕЙ СРАЗУ ПОСЛЕ СТАРТА ===
    if cmd in ["1", "сократ", "/socrates", "🏛️ сократ"]:
        user_roles[user_id] = "socrates"
        user_histories[user_id] = []
        reply = (
            "🏛️ Активирован режим: Сократ (Мудрый наставник)\n\n"
            "🎓 Напиши, в каком ты классе и какую школьную тему или задачу разбираем? "
            "*(Сюда можно прикрепить фото с условием задачи!)*"
        )
        send_message(chat_id, reply)
        return

    elif cmd in ["2", "аналитик", "/analyst", "📊 аналитик"]:
        user_roles[user_id] = "analyst"
        user_histories[user_id] = []
        reply = (
            "📊 Активирован режим: Аналитик (Мастер структуры)\n\n"
            "🎓 Укажи класс и пришли текст или фото страницы параграфа, которую нужно сжать в тезисы."
        )
        send_message(chat_id, reply)
        return

    elif cmd in ["3", "проверяющий", "/examiner", "📝 проверяющий"]:
        user_roles[user_id] = "examiner"
        user_histories[user_id] = []
        reply = (
            "📝 Активирован режим: Проверяющий (Экзаменатор)\n\n"
            "🎓 В каком ты классе и по какой школьной теме подготовить мини-тест из 6 вопросов?"
        )
        send_message(chat_id, reply)
        return
    # ====================================================

    # === ГЛОБАЛЬНЫЙ СТОП-ФИЛЬТР ДЛЯ ВСЕХ РОЛЕЙ ===
    stop_words = ["порно", "секс", "интим", "эротик", "матч", "ставка", "обойти фильтр"]
    text_lower = user_text.lower()
    
    if any(word in text_lower for word in stop_words):
        reply_text = "🛡️ Этот запрос нарушает правила академической безопасности. Пожалуйста, задай вопрос по школьной программе."
        send_message(chat_id, reply_text)
        return
    # ===========================================

    cmd_lower = user_text.strip().lower()

    # Проверяем, просит ли пользователь именно продолжение тестов (слово «еще»)
    if cmd_lower in ["еще", "ещё", "продолжить", "дальше"] and user_roles.get(user_id) == "examiner":
        user_text = "Сгенерируй следующие ровно 6 новых вопросов по нашей текущей теме."
    
    # Дополнительная проверка для Аналитика (если текст слишком короткий или вопрос)
    if user_roles.get(user_id) == "analyst":
        if len(user_text) < 60 or "?" in user_text:
            reply_text = "📊 Режим «Аналитик» принимает на обработку только учебные параграфы школьной программы (от 60 символов, без вопросов)."
            send_message(chat_id, reply_text)
            return

    # Генерация ответа через локальную нейросеть
    print(f"[{user_id}] Запрос к нейросети в роли [{user_roles[user_id]}]: '{user_text}'")
    send_message(chat_id, "⏳ Секунду, наставник обдумывает ответ...")
    reply_text = ask_local_ai(user_id, user_text)
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