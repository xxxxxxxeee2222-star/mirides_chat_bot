import asyncio
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
CONFIG_EXAMPLE_PATH = BASE_DIR / "config.example.json"
USERS_PATH = BASE_DIR / "users.json"

COMMAND_POLL_DELAY_SECONDS = 0.5
CHAT_FEED_POLL_INTERVAL_SECONDS = 3.0

ONLINE_ALIASES = {"online", "\u043e\u043d\u043b\u0430\u0439\u043d"}
CHAT_ALIASES = {"chat", "cha", "ch", "\u0447\u0430\u0442", "\u0447\u0430\u0442\u0438\u043a"}

CONFIG_ENV_MAP = {
    "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
    "mirides_url": "MIRIDES_URL",
    "mirides_method": "MIRIDES_METHOD",
    "mirides_body_format": "MIRIDES_BODY_FORMAT",
    "mirides_token": "MIRIDES_TOKEN",
    "mirides_token_field": "MIRIDES_TOKEN_FIELD",
    "mirides_message_field": "MIRIDES_MESSAGE_FIELD",
    "mirides_nickname_field": "MIRIDES_NICKNAME_FIELD",
    "online_url": "ONLINE_URL",
    "online_method": "ONLINE_METHOD",
    "online_body_format": "ONLINE_BODY_FORMAT",
    "online_token": "ONLINE_TOKEN",
    "online_token_field": "ONLINE_TOKEN_FIELD",
    "chat_feed_url": "CHAT_FEED_URL",
    "chat_feed_method": "CHAT_FEED_METHOD",
    "chat_feed_body_format": "CHAT_FEED_BODY_FORMAT",
    "chat_feed_token": "CHAT_FEED_TOKEN",
    "chat_feed_token_field": "CHAT_FEED_TOKEN_FIELD",
    "chat_forward_chat_id": "CHAT_FORWARD_CHAT_ID",
    "chat_forward_thread_id": "CHAT_FORWARD_THREAD_ID",
}


def load_json(path, default):
    if not path.exists():
        return default
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return default
        return json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_runtime_files():
    if not USERS_PATH.exists():
        save_json(USERS_PATH, {})
    if not CONFIG_PATH.exists() and CONFIG_EXAMPLE_PATH.exists():
        example = load_json(CONFIG_EXAMPLE_PATH, {})
        if isinstance(example, dict) and example:
            save_json(CONFIG_PATH, example)


def read_env_config():
    config = {}
    for key, env_name in CONFIG_ENV_MAP.items():
        value = os.getenv(env_name)
        if value is None or value == "":
            continue
        config[key] = value
    return config


def load_config():
    config = {}
    if CONFIG_PATH.exists():
        config = load_json(CONFIG_PATH, {})
    elif CONFIG_EXAMPLE_PATH.exists():
        config = load_json(CONFIG_EXAMPLE_PATH, {})

    if not isinstance(config, dict):
        config = {}

    config.update(read_env_config())

    required = ["telegram_bot_token", "mirides_url", "online_url"]
    missing = [key for key in required if not config.get(key)]
    if missing:
        env_names = ", ".join(f"{key}={CONFIG_ENV_MAP[key]}" for key in missing)
        raise RuntimeError(
            "config.json is missing required fields: "
            + ", ".join(missing)
            + ". Set them in config.json or via env vars: "
            + env_names
        )

    config.setdefault("poll_timeout_seconds", 5)
    config.setdefault("chat_forward_chat_id", "")
    config.setdefault("chat_forward_thread_id", "")
    config.setdefault("mirides_method", "POST")
    config.setdefault("mirides_token", "")
    config.setdefault("mirides_token_field", "token")
    config.setdefault("mirides_message_field", "message")
    config.setdefault("mirides_nickname_field", "nickname")
    config.setdefault("mirides_body_format", "form")
    config.setdefault("online_method", "GET")
    config.setdefault("online_token", "")
    config.setdefault("online_token_field", "token")
    config.setdefault("online_body_format", "json")
    config.setdefault("chat_feed_url", "")
    config.setdefault("chat_feed_method", "GET")
    config.setdefault("chat_feed_token", "")
    config.setdefault("chat_feed_token_field", "token")
    config.setdefault("chat_feed_body_format", "json")
    config.setdefault("chat_feed_after_id", 0)
    return config


def save_config(config):
    save_json(CONFIG_PATH, {key: value for key, value in config.items() if not str(key).startswith("_")})


def load_users():
    return load_json(USERS_PATH, {})


def save_users(users):
    save_json(USERS_PATH, users)


def normalize_username(username):
    return str(username or "").strip().lstrip("@").lower()


def ensure_user_record(users, telegram_id, telegram_username="", telegram_name=""):
    telegram_id = str(telegram_id)
    record = users.get(telegram_id, {})
    record["telegram_id"] = telegram_id
    record["telegram_username"] = telegram_username or record.get("telegram_username", "")
    record["telegram_username_normalized"] = normalize_username(record["telegram_username"])
    record["telegram_name"] = telegram_name or record.get("telegram_name", "")
    record.setdefault("nickname", "")
    users[telegram_id] = record
    return record


def resolve_display_name(record, fallback_user=None):
    nickname = str(record.get("nickname", "")).strip()
    if nickname:
        return nickname

    if fallback_user:
        username = str(fallback_user.get("username", "")).strip()
        if username:
            return username
        first_name = str(fallback_user.get("first_name", "")).strip()
        if first_name:
            return first_name

    username = str(record.get("telegram_username", "")).strip()
    if username:
        return username

    name = str(record.get("telegram_name", "")).strip()
    if name:
        return name

    return "User"


def parse_command_text(text):
    raw = str(text or "").strip()
    if not raw:
        return "", ""

    if raw.startswith("/"):
        raw = raw[1:]
        if "@" in raw:
            raw = raw.split("@", 1)[0]

    parts = raw.split(None, 1)
    command = parts[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""

    if command in ONLINE_ALIASES:
        return "online", argument
    if command in CHAT_ALIASES:
        return "chat", argument
    return command, argument


def normalize_thread_id(value):
    if value in (None, "", 0, "0"):
        return None
    return str(value)


def telegram_request(token, method, params=None):
    params = params or {}
    data = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=data)
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description", f"Telegram API error in {method}"))
    return payload["result"]


def send_message(token, chat_id, text, message_thread_id=None):
    params = {"chat_id": str(chat_id), "text": text}
    if message_thread_id:
        params["message_thread_id"] = str(message_thread_id)
    return telegram_request(token, "sendMessage", params)


def send_http_request(url, method="GET", params=None, body_format="json"):
    params = params or {}
    method = method.upper()
    headers = {"Accept": "application/json", "User-Agent": "MiridesBridgeBot/1.0"}

    if method == "GET":
        query = urllib.parse.urlencode(params)
        request_url = url if not query else f"{url}?{query}"
        request = urllib.request.Request(request_url, headers=headers, method="GET")
    else:
        if str(body_format).lower() == "form":
            data = urllib.parse.urlencode(params).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(params).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)

    with urllib.request.urlopen(request, timeout=20) as response:
        raw_body = response.read().decode("utf-8")
        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type.lower() or raw_body.startswith(("{", "[")):
            return json.loads(raw_body)
        return raw_body.strip()


def format_online_response(payload):
    if isinstance(payload, dict):
        online = payload.get("online")
        max_players = payload.get("maxPlayers")
        players = payload.get("players")
        if isinstance(players, list):
            if players:
                names = ", ".join(str(item) for item in players)
                if online is not None and max_players is not None:
                    return f"\u041e\u043d\u043b\u0430\u0439\u043d {online}/{max_players}: {names}"
                return f"\u0418\u0433\u0440\u043e\u043a\u0438: {names}"
            return "\u041d\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0435 \u043d\u0438\u043a\u043e\u0433\u043e \u043d\u0435\u0442."
        if isinstance(online, int) and isinstance(max_players, int):
            return f"\u041e\u043d\u043b\u0430\u0439\u043d {online}/{max_players}"
        if isinstance(online, int):
            return f"\u041e\u043d\u043b\u0430\u0439\u043d {online}"

    if isinstance(payload, list):
        if payload:
            return "\u0418\u0433\u0440\u043e\u043a\u0438: " + ", ".join(str(item) for item in payload)
        return "\u041d\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0435 \u043d\u0438\u043a\u043e\u0433\u043e \u043d\u0435\u0442."

    return "\u041d\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0435 \u043d\u0438\u043a\u043e\u0433\u043e \u043d\u0435\u0442."


async def handle_telegram_command(config, msg, text, chat_id, thread_id):
    users = load_users()
    from_user = msg.get("from", {})
    sender_record = ensure_user_record(
        users,
        from_user.get("id", ""),
        from_user.get("username", ""),
        from_user.get("first_name", "User"),
    )
    save_users(users)

    command, argument = parse_command_text(text)
    if not command:
        return False

    token = config["telegram_bot_token"]
    print(f"[+] command={command} arg={argument!r} from={sender_record.get('telegram_id', '')}")

    if command == "online":
        try:
            response = send_http_request(
                config["online_url"],
                method=config["online_method"],
                params={config["online_token_field"]: config["online_token"]},
                body_format=config.get("online_body_format", "json"),
            )
            send_message(token, chat_id, format_online_response(response), message_thread_id=thread_id)
        except Exception as e:
            send_message(token, chat_id, f"\u041d\u0435 \u0441\u043c\u043e\u0433 \u043f\u043e\u043b\u0443\u0447\u0438\u0442\u044c online: {e}", message_thread_id=thread_id)
        return True

    if command == "chat":
        message = argument.strip()
        if not message:
            send_message(
                token,
                chat_id,
                "\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0435: chat <\u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435>",
                message_thread_id=thread_id,
            )
            return True

        nickname = resolve_display_name(sender_record, from_user)
        payload = {
            config["mirides_token_field"]: config["mirides_token"],
            config["mirides_nickname_field"]: nickname,
            config["mirides_message_field"]: message,
        }

        try:
            send_http_request(
                config["mirides_url"],
                method=config["mirides_method"],
                params=payload,
                body_format=config.get("mirides_body_format", "form"),
            )
            send_message(token, chat_id, "\u0421\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u043e \u0432 \u0438\u0433\u0440\u0443.", message_thread_id=thread_id)
        except Exception as e:
            send_message(token, chat_id, f"\u041d\u0435 \u0441\u043c\u043e\u0433 \u043e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c \u0432 \u0438\u0433\u0440\u0443: {e}", message_thread_id=thread_id)
        return True

    return False


async def telegram_polling_loop(config):
    token = config["telegram_bot_token"]
    offset = 0
    configured_thread_id = normalize_thread_id(config.get("chat_forward_thread_id"))

    print("[+] Telegram loop started.")

    while True:
        try:
            updates = telegram_request(
                token,
                "getUpdates",
                {"offset": offset, "timeout": config.get("poll_timeout_seconds", 5)},
            )
            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message")
                if not isinstance(message, dict) or "text" not in message:
                    continue

                text = str(message["text"]).strip()
                chat_id = message["chat"]["id"]
                thread_id = normalize_thread_id(message.get("message_thread_id"))

                handled = await handle_telegram_command(config, message, text, chat_id, thread_id)
                if handled:
                    continue

                if str(chat_id) != str(config["chat_forward_chat_id"]):
                    continue
                if configured_thread_id and thread_id != configured_thread_id:
                    continue
                if text.startswith("/"):
                    continue

                users = load_users()
                sender = message.get("from", {})
                sender_record = ensure_user_record(
                    users,
                    sender.get("id", ""),
                    sender.get("username", ""),
                    sender.get("first_name", "User"),
                )
                save_users(users)
                nickname = resolve_display_name(sender_record, sender)
                payload = {
                    config["mirides_token_field"]: config["mirides_token"],
                    config["mirides_nickname_field"]: nickname,
                    config["mirides_message_field"]: text,
                }
                send_http_request(
                    config["mirides_url"],
                    method=config["mirides_method"],
                    params=payload,
                    body_format=config.get("mirides_body_format", "form"),
                )
                print(f"[+] Sent to Minecraft from {nickname}: {text}")

        except urllib.error.HTTPError as e:
            if e.code == 409:
                print("[-] Telegram API returned 409 Conflict. Stop all other copies of the bot using this token.")
                return
            print(f"[-] Telegram API error: {e}")
            await asyncio.sleep(3)
        except Exception as e:
            print(f"[-] Telegram loop error: {e}")
            await asyncio.sleep(3)

        await asyncio.sleep(COMMAND_POLL_DELAY_SECONDS)


async def minecraft_polling_loop(config):
    token = config["telegram_bot_token"]
    chat_id = config["chat_forward_chat_id"]
    thread_id = normalize_thread_id(config.get("chat_forward_thread_id"))
    last_id = int(config.get("chat_feed_after_id", 0) or 0)

    print("[+] Minecraft chat loop started.")

    while True:
        try:
            if config.get("chat_feed_url"):
                response = send_http_request(
                    config["chat_feed_url"],
                    method=config["chat_feed_method"],
                    params={
                        config["chat_feed_token_field"]: config["chat_feed_token"],
                        "after_id": last_id,
                    },
                    body_format=config.get("chat_feed_body_format", "json"),
                )

                items = []
                if isinstance(response, dict):
                    if isinstance(response.get("items"), list):
                        items = response["items"]
                    elif isinstance(response.get("messages"), list):
                        items = response["messages"]
                    latest_id = response.get("latestId")
                    if isinstance(latest_id, int):
                        last_id = max(last_id, latest_id)
                elif isinstance(response, list):
                    items = response

                if items:
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        nickname = item.get("playerName") or item.get("nickname") or item.get("player") or "system"
                        message = item.get("message") or item.get("text")
                        if message is None:
                            continue
                        try:
                            item_id = int(item.get("id", last_id))
                        except (TypeError, ValueError):
                            item_id = last_id
                        send_message(token, chat_id, f"[{nickname}]: {message}", message_thread_id=thread_id)
                        last_id = max(last_id, item_id)

                    config["chat_feed_after_id"] = last_id
                    save_config(config)

        except Exception as e:
            print(f"[-] Minecraft chat loop error: {e}")

        await asyncio.sleep(CHAT_FEED_POLL_INTERVAL_SECONDS)


async def main():
    ensure_runtime_files()
    config = load_config()
    await asyncio.gather(
        telegram_polling_loop(config),
        minecraft_polling_loop(config),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
