import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
USERS_PATH = BASE_DIR / "users.json"
COOLDOWN_SECONDS = 10
NICKNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,16}$")


def load_json(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path, data):
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def load_config():
    config = load_json(CONFIG_PATH, {})
    required_keys = ["telegram_bot_token", "mirides_url", "online_url"]
    missing = [key for key in required_keys if not config.get(key)]
    if missing:
        raise RuntimeError("В config.json не заполнены обязательные поля: " + ", ".join(missing))

    config.setdefault("poll_timeout_seconds", 30)
    config.setdefault("mirides_method", "POST")
    config.setdefault("online_method", "GET")
    config.setdefault("mirides_token", "")
    config.setdefault("online_token", "")
    config.setdefault("mirides_token_field", "token")
    config.setdefault("online_token_field", "token")
    config.setdefault("mirides_message_field", "message")
    config.setdefault("mirides_nickname_field", "nickname")
    config.setdefault("telegram_id_field", "telegram_id")
    config.setdefault("mirides_success_message", "Сообщение отправлено в игровой чат.")
    config.setdefault("online_response_path", "online")
    return config


def load_users():
    users = load_json(USERS_PATH, {})
    return users if isinstance(users, dict) else {}


def save_users(users):
    save_json(USERS_PATH, users)


def ensure_runtime_files():
    if not USERS_PATH.exists():
        save_json(USERS_PATH, {})


def telegram_request(token, method, params=None):
    params = params or {}
    data = urllib.parse.urlencode(params).encode("utf-8")
    url = f"https://api.telegram.org/bot{token}/{method}"
    request = urllib.request.Request(url, data=data)

    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not payload.get("ok"):
        raise RuntimeError(payload.get("description", f"Telegram API error in {method}"))
    return payload["result"]


def send_message(token, chat_id, text):
    telegram_request(token, "sendMessage", {"chat_id": str(chat_id), "text": text})


def delete_message(token, chat_id, message_id):
    try:
        telegram_request(
            token,
            "deleteMessage",
            {
                "chat_id": str(chat_id),
                "message_id": str(message_id),
            },
        )
    except Exception:
        pass


def send_http_request(url, method="GET", params=None):
    params = params or {}
    method = method.upper()

    if method == "GET":
        query = urllib.parse.urlencode(params)
        request_url = url if not query else f"{url}?{query}"
        request = urllib.request.Request(request_url, method="GET")
    else:
        data = urllib.parse.urlencode(params).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)

    with urllib.request.urlopen(request, timeout=20) as response:
        raw_body = response.read().decode("utf-8")
        content_type = response.headers.get("Content-Type", "")

    if "application/json" in content_type.lower():
        return json.loads(raw_body)

    try:
        return json.loads(raw_body)
    except json.JSONDecodeError:
        return raw_body.strip()


def extract_value(payload, path):
    if not path:
        return payload

    current = payload
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def build_help_text():
    return (
        "Команды:\n"
        "/nick ваш_ник - сохранить ник игрока\n"
        "/mynick - показать сохраненный ник\n"
        "/mirides текст - отправить сообщение в игровой чат\n"
        "/online - показать онлайн\n"
        "/help - помощь\n\n"
        "Сначала обязательно укажи ник через /nick.\n"
        f"Кулдаун на /mirides и /online: {COOLDOWN_SECONDS} секунд."
    )


def validate_nickname(nickname):
    if not NICKNAME_PATTERN.fullmatch(nickname):
        raise ValueError("Ник должен быть как в Minecraft: 3-16 символов, только английские буквы, цифры и _.")


def check_cooldown(last_usage, telegram_id):
    now = time.time()
    last_used = last_usage.get(telegram_id, 0)
    seconds_left = int(COOLDOWN_SECONDS - (now - last_used))
    if seconds_left > 0:
        return False, seconds_left
    last_usage[telegram_id] = now
    return True, 0


def handle_nick(config, users, chat_id, telegram_id, text):
    parts = text.split(" ", 1)
    if len(parts) < 2 or not parts[1].strip():
        raise ValueError("Использование: /nick ваш_ник")

    nickname = parts[1].strip()
    validate_nickname(nickname)

    users[telegram_id] = {"nickname": nickname}
    save_users(users)
    send_message(config["telegram_bot_token"], chat_id, f"Ник сохранен: {nickname}")


def handle_mynick(config, users, chat_id, telegram_id):
    user = users.get(telegram_id, {})
    nickname = str(user.get("nickname", "")).strip()
    if not nickname:
        send_message(config["telegram_bot_token"], chat_id, "Ник еще не сохранен. Используй /nick ваш_ник")
        return
    send_message(config["telegram_bot_token"], chat_id, f"Твой ник: {nickname}")


def handle_mirides(config, users, chat_id, telegram_id, text):
    user = users.get(telegram_id, {})
    nickname = str(user.get("nickname", "")).strip()
    if not nickname:
        raise ValueError("Сначала добавь ник игрока через /nick ваш_ник")

    parts = text.split(" ", 1)
    if len(parts) < 2 or not parts[1].strip():
        raise ValueError("Использование: /mirides всем привет")

    message = parts[1].strip()
    params = {
        config["mirides_message_field"]: message,
        config["mirides_nickname_field"]: nickname,
        config["telegram_id_field"]: telegram_id,
    }
    if config["mirides_token"]:
        params[config["mirides_token_field"]] = config["mirides_token"]

    response = send_http_request(config["mirides_url"], config["mirides_method"], params)
    if isinstance(response, dict):
        if response.get("ok") is False:
            raise RuntimeError(response.get("error", "Не удалось отправить сообщение"))
        if response.get("message"):
            send_message(config["telegram_bot_token"], chat_id, str(response["message"]))
            return

    send_message(config["telegram_bot_token"], chat_id, config["mirides_success_message"])


def handle_online(config, chat_id):
    params = {}
    if config["online_token"]:
        params[config["online_token_field"]] = config["online_token"]

    response = send_http_request(config["online_url"], config["online_method"], params)
    online_value = extract_value(response, config["online_response_path"])
    if online_value is None or online_value == "":
        raise RuntimeError("Сервер не вернул онлайн")

    if isinstance(online_value, (dict, list)):
        text = json.dumps(online_value, ensure_ascii=False)
    else:
        text = str(online_value)

    send_message(config["telegram_bot_token"], chat_id, f"Онлайн: {text}")


def process_message(config, users, message, last_usage):
    token = config["telegram_bot_token"]
    chat_id = message["chat"]["id"]
    telegram_id = str(message["from"]["id"])
    message_id = message["message_id"]
    text = message.get("text", "").strip()
    lowered = text.lower()

    if not text:
        return

    if lowered in {"/start", "/help", "help", "помощь"}:
        send_message(token, chat_id, build_help_text())
        delete_message(token, chat_id, message_id)
        return

    if text.startswith("/nick") or lowered.startswith("nick ") or lowered.startswith("ник "):
        handle_nick(config, users, chat_id, telegram_id, text)
        delete_message(token, chat_id, message_id)
        return

    if lowered in {"/mynick", "mynick", "мойник", "nick"}:
        handle_mynick(config, users, chat_id, telegram_id)
        delete_message(token, chat_id, message_id)
        return

    if text.startswith("/mirides") or lowered.startswith("mirides "):
        allowed, seconds_left = check_cooldown(last_usage, telegram_id)
        if not allowed:
            send_message(token, chat_id, f"Подожди {seconds_left} сек. перед следующей командой.")
            delete_message(token, chat_id, message_id)
            return
        command_text = text if text.startswith("/mirides") else "/mirides " + text.split(" ", 1)[1]
        handle_mirides(config, users, chat_id, telegram_id, command_text)
        delete_message(token, chat_id, message_id)
        return

    if lowered in {"/online", "online", "онлайн"}:
        allowed, seconds_left = check_cooldown(last_usage, telegram_id)
        if not allowed:
            send_message(token, chat_id, f"Подожди {seconds_left} сек. перед следующей командой.")
            delete_message(token, chat_id, message_id)
            return
        handle_online(config, chat_id)
        delete_message(token, chat_id, message_id)
        return

    send_message(token, chat_id, build_help_text())


def main():
    ensure_runtime_files()
    config = load_config()
    users = load_users()
    token = config["telegram_bot_token"]
    offset = 0
    last_usage = {}

    while True:
        try:
            updates = telegram_request(
                token,
                "getUpdates",
                {"timeout": int(config["poll_timeout_seconds"]), "offset": offset},
            )
            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message")
                if not message:
                    continue
                try:
                    process_message(config, users, message, last_usage)
                except ValueError as exc:
                    send_message(token, message["chat"]["id"], str(exc))
                except urllib.error.HTTPError as exc:
                    send_message(token, message["chat"]["id"], f"Ошибка HTTP: {exc.code}")
                except Exception as exc:
                    send_message(token, message["chat"]["id"], f"Ошибка: {exc}")
        except Exception as exc:
            print(f"Bot loop error: {exc}")
            time.sleep(5)


if __name__ == "__main__":
    main()
