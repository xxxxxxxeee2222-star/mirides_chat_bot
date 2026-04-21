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
ADMINS_PATH = BASE_DIR / "admins.json"
COOLDOWN_SECONDS = 10
CHAT_FEED_POLL_INTERVAL_SECONDS = 0.7
NICKNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,16}$")
JOIN_PREFIX_PATTERN = re.compile(r"^\[[^\]]+\]:\s*\+\s+([A-Za-z0-9_]{3,16})\s*$")
QUIT_PREFIX_PATTERN = re.compile(r"^\[[^\]]+\]:\s*-\s+([A-Za-z0-9_]{3,16})\s*$")
LOST_CONNECTION_PATTERN = re.compile(r"^\[[^\]]+\]:\s*([A-Za-z0-9_]{3,16})\[[^\]]+\]\s+lost connection:.*$")


def load_json(path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as file:
            raw = file.read().strip()
            if not raw:
                return default
            return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path, data):
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def ensure_runtime_files():
    if not USERS_PATH.exists():
        save_json(USERS_PATH, {})
    if not ADMINS_PATH.exists():
        save_json(ADMINS_PATH, {"admin_ids": []})


def load_config():
    config = load_json(CONFIG_PATH, {})
    required_keys = ["telegram_bot_token", "mirides_url", "online_url"]
    missing = [key for key in required_keys if not config.get(key)]
    if missing:
        raise RuntimeError("В config.json не заполнены обязательные поля: " + ", ".join(missing))

    config.setdefault("poll_timeout_seconds", 1)
    config.setdefault("mirides_method", "POST")
    config.setdefault("online_method", "GET")
    config.setdefault("playtime_top_url", config["online_url"].rsplit("/", 1)[0] + "/playtime-top")
    config.setdefault("playtime_top_method", "GET")
    config.setdefault("playtime_top_token", config.get("online_token", ""))
    config.setdefault("playtime_top_token_field", "token")
    config.setdefault("playtime_top_limit", 10)
    config.setdefault("mirides_token", "")
    config.setdefault("online_token", "")
    config.setdefault("mirides_token_field", "token")
    config.setdefault("online_token_field", "token")
    config.setdefault("mirides_message_field", "message")
    config.setdefault("mirides_nickname_field", "nickname")
    config.setdefault("telegram_id_field", "telegram_id")
    config.setdefault("online_response_path", "online")
    config.setdefault("chat_feed_url", "")
    config.setdefault("chat_feed_method", "GET")
    config.setdefault("chat_feed_token", "")
    config.setdefault("chat_feed_token_field", "token")
    config.setdefault("chat_feed_after_id", 0)
    config.setdefault("chat_forward_chat_id", "")
    config.setdefault("chat_forward_thread_id", "")
    config.setdefault("server_log_path", "/server/logs/latest.log")
    config.setdefault("forward_join_quit", True)
    return config


def save_config(config):
    persisted = {key: value for key, value in config.items() if not str(key).startswith("_")}
    save_json(CONFIG_PATH, persisted)


def load_users():
    users = load_json(USERS_PATH, {})
    return users if isinstance(users, dict) else {}


def save_users(users):
    save_json(USERS_PATH, users)


def load_admins():
    admins = load_json(ADMINS_PATH, {"admin_ids": []})
    if not isinstance(admins, dict):
        return {"admin_ids": []}
    admin_ids = admins.get("admin_ids", [])
    if not isinstance(admin_ids, list):
        admin_ids = []
    return {"admin_ids": [str(admin_id).strip() for admin_id in admin_ids if str(admin_id).strip()]}


def telegram_request(token, method, params=None):
    params = params or {}
    data = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=data)
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description", f"Telegram API error in {method}"))
    return payload["result"]


def send_message(token, chat_id, text, message_thread_id=""):
    params = {"chat_id": str(chat_id), "text": text}
    if str(message_thread_id).strip():
        params["message_thread_id"] = str(message_thread_id).strip()
    telegram_request(token, "sendMessage", params)


def delete_message(token, chat_id, message_id):
    try:
        telegram_request(token, "deleteMessage", {"chat_id": str(chat_id), "message_id": str(message_id)})
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
        "Пиши так:\n"
        "nick ваш_ник\n"
        "online\n"
        "chat ваш_текст\n"
        "playtime top\n\n"
        "Для админов:\n"
        "bantgbot @username|id|nick\n"
        "unbantgbot @username|id|nick\n"
        "whoistgbot @username|id|nick"
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


def require_group(chat_type):
    if chat_type not in {"group", "supergroup"}:
        raise ValueError("Команды работают только в группе.")


def require_admin(admins, telegram_id):
    if str(telegram_id) not in admins.get("admin_ids", []):
        raise ValueError("Эта команда только для админов из admins.json.")


def get_full_name(user_info):
    first_name = str(user_info.get("first_name", "")).strip()
    last_name = str(user_info.get("last_name", "")).strip()
    return " ".join(part for part in [first_name, last_name] if part).strip()


def update_user_record(users, telegram_user):
    telegram_id = str(telegram_user.get("id"))
    record = dict(users.get(telegram_id, {}))

    username = str(telegram_user.get("username", "")).strip()
    full_name = get_full_name(telegram_user)

    record["telegram_id"] = telegram_id
    record["telegram_username"] = username
    record["telegram_username_normalized"] = username.lower()
    record["telegram_name"] = full_name
    record.setdefault("nickname", "")
    record.setdefault("banned", False)

    users[telegram_id] = record
    return record


def get_identity_text(record):
    parts = []
    nickname = str(record.get("nickname", "")).strip()
    username = str(record.get("telegram_username", "")).strip()
    full_name = str(record.get("telegram_name", "")).strip()
    telegram_id = str(record.get("telegram_id", "")).strip()

    if nickname:
        parts.append(f"nick={nickname}")
    if username:
        parts.append(f"@{username}")
    if full_name:
        parts.append(full_name)
    if telegram_id:
        parts.append(f"id={telegram_id}")

    return " | ".join(parts) if parts else "unknown user"


def find_user_by_query(users, query):
    normalized_query = str(query or "").strip()
    if not normalized_query:
        return None

    if normalized_query.startswith("@"):
        normalized_query = normalized_query[1:]

    lowered_query = normalized_query.lower()
    if normalized_query in users:
        return users[normalized_query]

    for record in users.values():
        if str(record.get("telegram_id", "")).strip() == normalized_query:
            return record
        if str(record.get("nickname", "")).strip().lower() == lowered_query:
            return record
        if str(record.get("telegram_username_normalized", "")).strip() == lowered_query:
            return record

    return None


def is_nickname_taken(users, nickname, excluded_telegram_id=""):
    normalized_nickname = str(nickname or "").strip().lower()
    if not normalized_nickname:
        return False

    for telegram_id, record in users.items():
        if excluded_telegram_id and str(telegram_id) == str(excluded_telegram_id):
            continue
        if str(record.get("nickname", "")).strip().lower() == normalized_nickname:
            return True
    return False


def resolve_target_record(users, query, reply_message=None):
    query = str(query or "").strip()
    if query:
        record = find_user_by_query(users, query)
        if record:
            return record

    if reply_message and reply_message.get("from"):
        reply_user = reply_message["from"]
        reply_id = str(reply_user.get("id"))
        return users.get(reply_id) or update_user_record(users, reply_user)

    return None


def ensure_not_banned(record):
    if record and record.get("banned"):
        raise ValueError("Ты заблокирован в боте.")


def handle_nick(config, users, chat_id, telegram_id, text):
    parts = text.split(" ", 1)
    if len(parts) < 2 or not parts[1].strip():
        raise ValueError("Использование: nick ваш_ник")

    nickname = parts[1].strip()
    validate_nickname(nickname)

    existing_nickname = str(users.get(telegram_id, {}).get("nickname", "")).strip()
    if existing_nickname:
        send_message(config["telegram_bot_token"], chat_id, f"Ник уже привязан: {existing_nickname}", config.get("_reply_thread_id", ""))
        return

    if is_nickname_taken(users, nickname, telegram_id):
        raise ValueError("Этот ник уже привязан к другому Telegram аккаунту.")

    users[telegram_id]["nickname"] = nickname
    save_users(users)
    send_message(config["telegram_bot_token"], chat_id, f"Ник сохранён: {nickname}", config.get("_reply_thread_id", ""))


def handle_mynick(config, users, chat_id, telegram_id):
    nickname = str(users.get(telegram_id, {}).get("nickname", "")).strip()
    if not nickname:
        send_message(config["telegram_bot_token"], chat_id, "Ник ещё не сохранён. Используй: nick ваш_ник", config.get("_reply_thread_id", ""))
        return
    send_message(config["telegram_bot_token"], chat_id, f"Твой ник: {nickname}", config.get("_reply_thread_id", ""))


def handle_chat(config, users, chat_id, telegram_id, text):
    nickname = str(users.get(telegram_id, {}).get("nickname", "")).strip()
    if not nickname:
        raise ValueError("Сначала добавь ник игрока: nick ваш_ник")

    parts = text.split(" ", 1)
    if len(parts) < 2 or not parts[1].strip():
        raise ValueError("Использование: chat всем привет")

    message = parts[1].strip()
    params = {
        config["mirides_message_field"]: message,
        config["mirides_nickname_field"]: nickname,
        config["telegram_id_field"]: telegram_id,
    }
    if config["mirides_token"]:
        params[config["mirides_token_field"]] = config["mirides_token"]

    response = send_http_request(config["mirides_url"], config["mirides_method"], params)
    if isinstance(response, dict) and response.get("ok") is False:
        raise RuntimeError(response.get("error", "Не удалось отправить сообщение"))

    send_message(config["telegram_bot_token"], chat_id, f"{nickname}: {message}", config.get("_reply_thread_id", ""))


def handle_online(config, chat_id):
    params = {}
    if config["online_token"]:
        params[config["online_token_field"]] = config["online_token"]

    response = send_http_request(config["online_url"], config["online_method"], params)
    online_value = extract_value(response, config["online_response_path"])
    if online_value is None or online_value == "":
        raise RuntimeError("Сервер не вернул онлайн")

    if isinstance(response, dict):
        online_count = response.get("online", online_value)
        players = response.get("players", [])
        if isinstance(players, list) and players:
            send_message(
                config["telegram_bot_token"],
                chat_id,
                f"Онлайн: {online_count} | {', '.join(str(player) for player in players)}",
                config.get("_reply_thread_id", ""),
            )
            return
        send_message(config["telegram_bot_token"], chat_id, f"Онлайн: {online_count}", config.get("_reply_thread_id", ""))
        return

    send_message(config["telegram_bot_token"], chat_id, f"Онлайн: {online_value}", config.get("_reply_thread_id", ""))


def handle_playtime_top(config, chat_id):
    params = {"limit": int(config.get("playtime_top_limit", 10))}
    if config.get("playtime_top_token"):
        params[config["playtime_top_token_field"]] = config["playtime_top_token"]

    response = send_http_request(config["playtime_top_url"], config["playtime_top_method"], params)
    if not isinstance(response, dict) or response.get("ok") is False:
        raise RuntimeError("Не удалось получить топ по плейтайму")

    lines = [str(line).strip() for line in response.get("lines", []) if str(line).strip()]
    if not lines:
        send_message(config["telegram_bot_token"], chat_id, "Топ по плейтайму пока пуст.", config.get("_reply_thread_id", ""))
        return

    send_message(config["telegram_bot_token"], chat_id, "\n".join(lines), config.get("_reply_thread_id", ""))


def handle_whois(config, users, chat_id, query, reply_message):
    record = resolve_target_record(users, query, reply_message)
    if not record:
        send_message(config["telegram_bot_token"], chat_id, "Пользователь не найден.", config.get("_reply_thread_id", ""))
        return

    banned_text = "да" if record.get("banned") else "нет"
    send_message(
        config["telegram_bot_token"],
        chat_id,
        f"{get_identity_text(record)}\nban={banned_text}",
        config.get("_reply_thread_id", ""),
    )


def handle_ban(config, users, chat_id, query, reply_message):
    record = resolve_target_record(users, query, reply_message)
    if not record:
        send_message(config["telegram_bot_token"], chat_id, "Кого банить не найдено.", config.get("_reply_thread_id", ""))
        return

    record["banned"] = True
    users[str(record["telegram_id"])] = record
    save_users(users)
    send_message(config["telegram_bot_token"], chat_id, f"Забанен в боте: {get_identity_text(record)}", config.get("_reply_thread_id", ""))


def handle_unban(config, users, chat_id, query, reply_message):
    record = resolve_target_record(users, query, reply_message)
    if not record:
        send_message(config["telegram_bot_token"], chat_id, "Кого разбанить не найдено.", config.get("_reply_thread_id", ""))
        return

    record["banned"] = False
    users[str(record["telegram_id"])] = record
    save_users(users)
    send_message(config["telegram_bot_token"], chat_id, f"Разбанен в боте: {get_identity_text(record)}", config.get("_reply_thread_id", ""))


def poll_server_log(config):
    if not config.get("forward_join_quit"):
        return config
    if not config.get("chat_forward_chat_id"):
        return config

    log_path = Path(str(config.get("server_log_path", "")).strip())
    if not log_path.exists() or not log_path.is_file():
        return config

    position = int(config.get("_server_log_position", 0) or 0)
    if position <= 0:
        config["_server_log_position"] = log_path.stat().st_size
        return config

    file_size = log_path.stat().st_size
    if file_size < position:
        position = 0

    sent = False
    with log_path.open("r", encoding="utf-8", errors="ignore") as file:
        file.seek(position)
        for raw_line in file:
            line = raw_line.strip()
            text = parse_join_quit_line(line)
            if text:
                send_message(
                    config["telegram_bot_token"],
                    config["chat_forward_chat_id"],
                    text,
                    config.get("chat_forward_thread_id", ""),
                )
                sent = True
        config["_server_log_position"] = file.tell()

    if sent:
        return config
    return config


def parse_join_quit_line(line):
    match = JOIN_PREFIX_PATTERN.match(line)
    if match:
        return f"↗ {match.group(1)} вошёл на сервер"

    match = QUIT_PREFIX_PATTERN.match(line)
    if match:
        return f"↘ {match.group(1)} вышел с сервера"

    match = LOST_CONNECTION_PATTERN.match(line)
    if match:
        return f"↘ {match.group(1)} вышел с сервера"

    return ""


def poll_chat_feed(config):
    if not config.get("chat_feed_url") or not config.get("chat_forward_chat_id"):
        return config

    params = {"after_id": int(config.get("chat_feed_after_id", 0))}
    if config.get("chat_feed_token"):
        params[config["chat_feed_token_field"]] = config["chat_feed_token"]

    response = send_http_request(config["chat_feed_url"], config["chat_feed_method"], params)
    if not isinstance(response, dict):
        return config

    latest_id = int(response.get("latestId", 0) or 0)
    current_after_id = int(config.get("chat_feed_after_id", 0))
    if response.get("resetSuggested") or current_after_id > latest_id:
        config["chat_feed_after_id"] = latest_id
        save_config(config)
        return config

    items = response.get("items", [])
    max_id = current_after_id
    sent_keys = set()
    started_at_ms = int(config.get("_chat_feed_started_at_ms", 0) or 0)
    for item in items:
        item_id = int(item.get("id", 0))
        player_name = str(item.get("playerName", "")).strip()
        message = str(item.get("message", "")).strip()
        item_timestamp = int(item.get("timestamp", 0) or 0)
        if item_id <= 0 or not player_name or not message:
            continue

        if started_at_ms and item_timestamp and item_timestamp < started_at_ms:
            max_id = max(max_id, item_id)
            continue

        dedupe_key = (player_name, message)
        if dedupe_key in sent_keys:
            max_id = max(max_id, item_id)
            continue
        sent_keys.add(dedupe_key)

        send_message(
            config["telegram_bot_token"],
            config["chat_forward_chat_id"],
            f"\u24c9 {player_name} \u00bb {message}",
            config.get("chat_forward_thread_id", ""),
        )
        max_id = max(max_id, item_id)

    if max_id != current_after_id:
        config["chat_feed_after_id"] = max_id
        save_config(config)
    return config


def process_message(config, users, admins, message, last_usage):
    token = config["telegram_bot_token"]
    chat = message["chat"]
    chat_id = chat["id"]
    chat_type = str(chat.get("type", "")).strip().lower()
    telegram_user = message.get("from", {})
    telegram_id = str(telegram_user["id"])
    message_id = message["message_id"]
    message_thread_id = str(message.get("message_thread_id", "")).strip()
    reply_message = message.get("reply_to_message")
    text = message.get("text", "").strip()
    lowered = text.lower()
    config["_reply_thread_id"] = message_thread_id

    user_record = update_user_record(users, telegram_user)
    save_users(users)

    if not text:
        return

    if lowered in {"help", "помощь", "menu", "меню", "start"}:
        if chat_type not in {"group", "supergroup"}:
            send_message(token, chat_id, "Пиши команды только в группе.", message_thread_id)
            return
        send_message(token, chat_id, build_help_text(), message_thread_id)
        delete_message(token, chat_id, message_id)
        return

    require_group(chat_type)
    ensure_not_banned(user_record)

    if lowered.startswith("bantgbot"):
        require_admin(admins, telegram_id)
        query = text[len("bantgbot"):].strip()
        handle_ban(config, users, chat_id, query, reply_message)
        delete_message(token, chat_id, message_id)
        return

    if lowered.startswith("unbantgbot"):
        require_admin(admins, telegram_id)
        query = text[len("unbantgbot"):].strip()
        handle_unban(config, users, chat_id, query, reply_message)
        delete_message(token, chat_id, message_id)
        return

    if lowered.startswith("whoistgbot"):
        require_admin(admins, telegram_id)
        query = text[len("whoistgbot"):].strip()
        handle_whois(config, users, chat_id, query, reply_message)
        delete_message(token, chat_id, message_id)
        return

    if lowered.startswith("nick "):
        handle_nick(config, users, chat_id, telegram_id, text)
        delete_message(token, chat_id, message_id)
        return

    if lowered in {"mynick", "мойник", "мой ник"}:
        handle_mynick(config, users, chat_id, telegram_id)
        delete_message(token, chat_id, message_id)
        return

    if lowered.startswith("chat "):
        allowed, seconds_left = check_cooldown(last_usage, telegram_id)
        if not allowed:
            send_message(token, chat_id, f"Подожди {seconds_left} сек. перед следующей командой.", message_thread_id)
            delete_message(token, chat_id, message_id)
            return
        handle_chat(config, users, chat_id, telegram_id, text)
        delete_message(token, chat_id, message_id)
        return

    if lowered == "online":
        allowed, seconds_left = check_cooldown(last_usage, telegram_id)
        if not allowed:
            send_message(token, chat_id, f"Подожди {seconds_left} сек. перед следующей командой.", message_thread_id)
            delete_message(token, chat_id, message_id)
            return
        handle_online(config, chat_id)
        delete_message(token, chat_id, message_id)
        return

    if lowered == "playtime top":
        allowed, seconds_left = check_cooldown(last_usage, telegram_id)
        if not allowed:
            send_message(token, chat_id, f"Подожди {seconds_left} сек. перед следующей командой.", message_thread_id)
            delete_message(token, chat_id, message_id)
            return
        handle_playtime_top(config, chat_id)
        delete_message(token, chat_id, message_id)


def main():
    ensure_runtime_files()
    config = load_config()
    users = load_users()
    admins = load_admins()
    token = config["telegram_bot_token"]
    offset = 0
    last_usage = {}
    last_chat_feed_poll = 0.0
    config["_chat_feed_started_at_ms"] = int(time.time() * 1000)
    try:
        log_path = Path(str(config.get("server_log_path", "")).strip())
        if log_path.exists() and log_path.is_file():
            config["_server_log_position"] = log_path.stat().st_size
        else:
            config["_server_log_position"] = 0
    except OSError:
        config["_server_log_position"] = 0

    while True:
        try:
            try:
                now = time.monotonic()
                if now - last_chat_feed_poll >= CHAT_FEED_POLL_INTERVAL_SECONDS:
                    config = poll_chat_feed(config)
                    config = poll_server_log(config)
                    last_chat_feed_poll = now
            except Exception as exc:
                print(f"Chat feed poll error: {exc}")

            updates = telegram_request(token, "getUpdates", {"timeout": int(config["poll_timeout_seconds"]), "offset": offset})
            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message")
                if not message:
                    continue
                try:
                    process_message(config, users, admins, message, last_usage)
                except ValueError as exc:
                    send_message(token, message["chat"]["id"], str(exc), str(message.get("message_thread_id", "")).strip())
                except urllib.error.HTTPError as exc:
                    send_message(token, message["chat"]["id"], f"Ошибка HTTP: {exc.code}", str(message.get("message_thread_id", "")).strip())
                except Exception as exc:
                    send_message(token, message["chat"]["id"], f"Ошибка: {exc}", str(message.get("message_thread_id", "")).strip())

            try:
                now = time.monotonic()
                if now - last_chat_feed_poll >= CHAT_FEED_POLL_INTERVAL_SECONDS:
                    config = poll_chat_feed(config)
                    config = poll_server_log(config)
                    last_chat_feed_poll = now
            except Exception as exc:
                print(f"Chat feed poll error: {exc}")
        except Exception as exc:
            print(f"Bot loop error: {exc}")
            time.sleep(5)


if __name__ == "__main__":
    main()
