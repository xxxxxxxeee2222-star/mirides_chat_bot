import json
import re
import time
import asyncio
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
USERS_PATH = BASE_DIR / "users.json"
ADMINS_PATH = BASE_DIR / "admins.json"

COOLDOWN_SECONDS = 2
CHAT_FEED_POLL_INTERVAL_SECONDS = 3.0  # РЈРІРµР»РёС‡РµРЅРѕ, С‡С‚РѕР±С‹ РёР·Р±РµР¶Р°С‚СЊ РѕС€РёР±РєРё 429

NICKNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,16}$")

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
        raise RuntimeError("Р’ config.json РЅРµ Р·Р°РїРѕР»РЅРµРЅС‹ РѕР±СЏР·Р°С‚РµР»СЊРЅС‹Рµ РїРѕР»СЏ: " + ", ".join(missing))

    config.setdefault("poll_timeout_seconds", 1)
    config.setdefault("mirides_method", "POST")
    config.setdefault("online_method", "GET")
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
    config.setdefault("mirides_body_format", "json")
    config.setdefault("online_body_format", "json")
    config.setdefault("chat_feed_body_format", "json")
    config.setdefault("playtime_top_url", "")
    config.setdefault("playtime_top_method", "GET")
    config.setdefault("playtime_top_body_format", "json")
    config.setdefault("playtime_top_token", "")
    config.setdefault("playtime_top_token_field", "token")
    config.setdefault("playtime_top_limit", 10)
    config.setdefault("forward_join_quit", True)
    return config

def save_config(config):
    persisted = {key: value for key, value in config.items() if not str(key).startswith("_")}
    save_json(CONFIG_PATH, persisted)

def load_users():
    return load_json(USERS_PATH, {})

def save_users(users):
    save_json(USERS_PATH, users)

def load_admin_ids():
    data = load_json(ADMINS_PATH, {"admin_ids": []})
    return {str(item) for item in data.get("admin_ids", [])}

def normalize_username(username):
    return str(username or "").strip().lstrip("@").lower()

def ensure_user_record(users, telegram_id, telegram_username="", telegram_name=""):
    telegram_id = str(telegram_id)
    record = users.get(telegram_id, {})
    record["telegram_id"] = telegram_id
    record["telegram_username"] = telegram_username or record.get("telegram_username", "")
    record["telegram_username_normalized"] = normalize_username(telegram_username or record.get("telegram_username", ""))
    record["telegram_name"] = telegram_name or record.get("telegram_name", "")
    record.setdefault("nickname", "")
    record.setdefault("banned", False)
    users[telegram_id] = record
    return record

def find_user_record(users, query):
    query = str(query or "").strip()
    if not query:
        return None

    if query.startswith("@"):
        query = query[1:]

    if query in users:
        return users[query]

    normalized_query = query.lower()
    for record in users.values():
        if normalize_username(record.get("telegram_username")) == normalized_query:
            return record
        if str(record.get("nickname", "")).lower() == normalized_query:
            return record
        if str(record.get("telegram_name", "")).lower() == normalized_query:
            return record

    for record in users.values():
        haystack = " ".join([
            str(record.get("telegram_username", "")),
            str(record.get("nickname", "")),
            str(record.get("telegram_name", "")),
            str(record.get("telegram_id", "")),
        ]).lower()
        if normalized_query in haystack:
            return record

    return None

def is_admin_user(telegram_id):
    return str(telegram_id) in load_admin_ids()

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

    if command == "playtime" and argument.lower() == "top":
        return "playtime top", ""

    return command, argument

def resolve_target_user(users, msg, argument, allow_self_when_missing=True):
    if msg.get("reply_to_message") and isinstance(msg["reply_to_message"], dict):
        replied_from = msg["reply_to_message"].get("from", {})
        replied_id = str(replied_from.get("id", ""))
        if replied_id:
            return ensure_user_record(
                users,
                replied_id,
                replied_from.get("username", ""),
                replied_from.get("first_name", "User"),
            )

    if argument:
        record = find_user_record(users, argument)
        if record:
            return record
        if argument.isdigit():
            return ensure_user_record(users, argument)
        return None

    if not allow_self_when_missing:
        return None

    from_user = msg.get("from", {})
    return ensure_user_record(
        users,
        from_user.get("id", ""),
        from_user.get("username", ""),
        from_user.get("first_name", "User"),
    )

def format_user_info(record):
    username = record.get("telegram_username", "")
    username_text = f"@{username}" if username else "no username"
    nickname = record.get("nickname", "") or "no nick"
    name = record.get("telegram_name", "") or "no name"
    banned = "yes" if record.get("banned") else "no"
    return (
        f"Telegram ID: {record.get('telegram_id', '')}\n"
        f"Username: {username_text}\n"
        f"Name: {name}\n"
        f"Minecraft nick: {nickname}\n"
        f"Banned: {banned}"
    )

async def handle_telegram_command(config, msg, text, chat_id, thread_id):
    users = load_users()
    from_user = msg.get("from", {})
    sender_id = str(from_user.get("id", ""))
    sender_record = ensure_user_record(
        users,
        sender_id,
        from_user.get("username", ""),
        from_user.get("first_name", "User"),
    )
    command, argument = parse_command_text(text)
    if not command:
        return False

    if sender_record.get("banned") and command not in {"whoistgbot"}:
        return True

    token = config["telegram_bot_token"]

    if command == "online":
        params = {config["online_token_field"]: config["online_token"]}
        res = send_http_request(
            config["online_url"],
            method=config["online_method"],
            params=params,
            body_format=config.get("online_body_format", "json"),
        )
        players = extract_value(res, config["online_response_path"])
        if isinstance(players, list) and players:
            players_text = ", ".join(str(p) for p in players)
        elif isinstance(players, dict) and "list" in players:
            players_text = ", ".join(str(p) for p in players["list"])
        elif isinstance(players, int):
            players_text = f"{players} players online"
        else:
            players_text = "На сервере никого нет."
        send_message(token, chat_id, f"🎮 Онлайн: {players_text}", message_thread_id=thread_id)
        return True

    if command == "playtime top":
        if not config.get("playtime_top_url"):
            send_message(token, chat_id, "Playtime endpoint is not configured.", message_thread_id=thread_id)
            return True

        params = {config["playtime_top_token_field"]: config["playtime_top_token"]}
        limit = config.get("playtime_top_limit", 10)
        if limit not in (None, ""):
            params["limit"] = limit
        res = send_http_request(
            config["playtime_top_url"],
            method=config["playtime_top_method"],
            params=params,
            body_format=config.get("playtime_top_body_format", "json"),
        )
        if isinstance(res, dict) and isinstance(res.get("lines"), list):
            lines = [str(line) for line in res["lines"]]
            send_message(token, chat_id, "\n".join(lines), message_thread_id=thread_id)
        elif isinstance(res, list):
            send_message(token, chat_id, "\n".join(str(line) for line in res), message_thread_id=thread_id)
        else:
            send_message(token, chat_id, str(res), message_thread_id=thread_id)
        return True

    if command == "nick":
        nickname = argument.strip()
        if not nickname:
            current = sender_record.get("nickname", "")
            if current:
                send_message(token, chat_id, f"Current nick: {current}", message_thread_id=thread_id)
            else:
                send_message(token, chat_id, "Usage: nick <minecraft_nick>", message_thread_id=thread_id)
            return True

        if not NICKNAME_PATTERN.fullmatch(nickname):
            send_message(token, chat_id, "Nick must be 3-16 chars: letters, numbers, underscore.", message_thread_id=thread_id)
            return True

        sender_record["nickname"] = nickname
        users[sender_id] = sender_record
        save_users(users)
        send_message(token, chat_id, f"Nick saved: {nickname}", message_thread_id=thread_id)
        return True

    if command == "chat":
        message = argument.strip()
        if not message:
            send_message(token, chat_id, "Usage: chat <message>", message_thread_id=thread_id)
            return True

        nickname = sender_record.get("nickname") or from_user.get("username") or from_user.get("first_name", "User")
        payload = {
            config["mirides_token_field"]: config["mirides_token"],
            config["mirides_nickname_field"]: nickname,
            config["mirides_message_field"]: message,
        }
        send_http_request(
            config["mirides_url"],
            method=config["mirides_method"],
            params=payload,
            body_format=config.get("mirides_body_format", "json"),
        )
        send_message(token, chat_id, "Sent to Minecraft.", message_thread_id=thread_id)
        return True

    if command == "whoistgbot":
        target = resolve_target_user(users, msg, argument, allow_self_when_missing=True)
        if target is None:
            send_message(token, chat_id, "Target user not found.", message_thread_id=thread_id)
            return True
        send_message(token, chat_id, format_user_info(target), message_thread_id=thread_id)
        return True

    if command in {"bantgbot", "unbantgbot"}:
        if not is_admin_user(sender_id):
            send_message(token, chat_id, "No admin rights.", message_thread_id=thread_id)
            return True

        target = resolve_target_user(users, msg, argument, allow_self_when_missing=False)
        if not target.get("telegram_id"):
            send_message(token, chat_id, "Target user not found.", message_thread_id=thread_id)
            return True

        target["banned"] = command == "bantgbot"
        users[str(target["telegram_id"])] = target
        save_users(users)
        state = "banned" if target["banned"] else "unbanned"
        send_message(token, chat_id, f"{state}: {format_user_info(target)}", message_thread_id=thread_id)
        return True

    return False

def telegram_request(token, method, params=None):
    params = params or {}
    data = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=data)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok"):
            raise RuntimeError(payload.get("description", f"Telegram API error in {method}"))
        return payload["result"]
    except urllib.error.HTTPError as e:
        if e.code == 409:
            print("[-] РљСЂРёС‚РёС‡РµСЃРєР°СЏ РѕС€РёР±РєР°: РљРѕРЅС„Р»РёРєС‚ С‚РѕРєРµРЅР° (409). Р‘РѕС‚ Р·Р°РїСѓС‰РµРЅ РІ РґСЂСѓРіРѕРј РјРµСЃС‚Рµ!")
        raise e

def normalize_thread_id(value):
    if value in (None, "", 0, "0"):
        return None
    return str(value)

def send_message(token, chat_id, text, message_thread_id=None):
    params = {"chat_id": str(chat_id), "text": text}
    if message_thread_id:
        params["message_thread_id"] = str(message_thread_id)
    telegram_request(token, "sendMessage", params)

def send_http_request(url, method="GET", params=None, body_format="json"):
    params = params or {}
    method = method.upper()
    
    headers = {
        "Accept": "application/json",
        "User-Agent": "Bothost-Minecraft-Bot/1.0"
    }

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

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw_body = response.read().decode("utf-8")
            content_type = response.headers.get("Content-Type", "")
            
            if "application/json" in content_type.lower() or raw_body.startswith(("{", "[")):
                return json.loads(raw_body)
            return raw_body.strip()
    except urllib.error.HTTPError as e:
        try:
            error_text = e.read().decode("utf-8")
            print(f"[-] РЎРµСЂРІРµСЂ РњР°Р№РЅРєСЂР°С„С‚Р° РІРµСЂРЅСѓР» РѕС€РёР±РєСѓ {e.code}: {error_text}")
        except Exception:
            pass
        raise e

def extract_value(payload, path):
    if not path or not isinstance(payload, dict):
        return payload
    current = payload
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current

async def telegram_polling_loop(config):
    """РРЎРџР РђР’Р›Р•РќРћ: РќРѕРІС‹Р№ РїРѕС‚РѕРє, РєРѕС‚РѕСЂС‹Р№ РїСЂРёРЅРёРјР°РµС‚ СЃРѕРѕР±С‰РµРЅРёСЏ Рё РєРѕРјР°РЅРґС‹ РёР· Telegram С‡Р°С‚Р°"""
    token = config["telegram_bot_token"]
    offset = 0
    configured_thread_id = normalize_thread_id(config.get("chat_forward_thread_id"))
    print("[+] РџРѕС‚РѕРє РѕР±СЂР°Р±РѕС‚РєРё РєРѕРјР°РЅРґ Telegram СѓСЃРїРµС€РЅРѕ Р·Р°РїСѓС‰РµРЅ!")
    
    while True:
        try:
            updates = telegram_request(token, "getUpdates", {"offset": offset, "timeout": 5})
            for update in updates:
                offset = update["update_id"] + 1
                
                if "message" in update and "text" in update["message"]:
                    msg = update["message"]
                    text = msg["text"].strip()
                    chat_id = msg["chat"]["id"]
                    thread_id = normalize_thread_id(msg.get("message_thread_id"))
                    handled = await handle_telegram_command(config, msg, text, chat_id, thread_id)
                    if handled:
                        continue
                    
                    # РџРµСЂРµСЃС‹Р»РєР° СЃРѕРѕР±С‰РµРЅРёСЏ РёР· РўР“ РІ С‡Р°С‚ РёРіСЂС‹
                    if str(chat_id) == str(config["chat_forward_chat_id"]):
                        if configured_thread_id and thread_id != configured_thread_id:
                            continue

                        # РРіРЅРѕСЂРёСЂСѓРµРј РєРѕРјР°РЅРґС‹ СЃР°РјРѕРіРѕ Р±РѕС‚Р°
                        if text.startswith("/"):
                            continue
                            
                        users = load_users()
                        sender = msg["from"]
                        sender_record = ensure_user_record(
                            users,
                            sender.get("id", ""),
                            sender.get("username", ""),
                            sender.get("first_name", "User"),
                        )
                        nickname = sender_record.get("nickname") or sender.get("username") or sender.get("first_name", "User")
                        payload = {
                            config["mirides_token_field"]: config["mirides_token"],
                            config["mirides_nickname_field"]: nickname,
                            config["mirides_message_field"]: text
                        }
                        try:
                            send_http_request(config["mirides_url"], method=config["mirides_method"], params=payload, body_format=config.get("mirides_body_format", "json"))
                            print(f"[+] РћС‚РїСЂР°РІР»РµРЅРѕ РІ Minecraft РѕС‚ {nickname}: {text}")
                        except Exception as e:
                            print(f"[-] РќРµ СѓРґР°Р»РѕСЃСЊ РѕС‚РїСЂР°РІРёС‚СЊ СЃРѕРѕР±С‰РµРЅРёРµ РІ РёРіСЂСѓ: {e}")
                            
        except Exception as e:
            if isinstance(e, urllib.error.HTTPError) and e.code == 409:
                print("[-] Telegram API вернул 409 Conflict. Остановите все другие копии бота с этим токеном и перезапустите только один экземпляр.")
                return
            print(f"[-] Ошибка обработки Telegram: {e}")
            await asyncio.sleep(3)
        await asyncio.sleep(0.5)

async def minecraft_polling_loop(config):
    """РџРѕС‚РѕРє, РєРѕС‚РѕСЂС‹Р№ Р·Р°Р±РёСЂР°РµС‚ СЃРѕРѕР±С‰РµРЅРёСЏ РёР· РёРіСЂС‹ Рё С€Р»РµС‚ РёС… РІ РўР“ С‡Р°С‚"""
    token = config["telegram_bot_token"]
    chat_id = config["chat_forward_chat_id"]
    thread_id = normalize_thread_id(config.get("chat_forward_thread_id"))
    last_id = config["chat_feed_after_id"]
    print("[+] РџРѕС‚РѕРє С‡С‚РµРЅРёСЏ С‡Р°С‚Р° Minecraft СѓСЃРїРµС€РЅРѕ Р·Р°РїСѓС‰РµРЅ!")
    
    while True:
        try:
            if config["chat_feed_url"]:
                payload = {
                    config["chat_feed_token_field"]: config["chat_feed_token"], 
                    "after_id": last_id
                }
                res = send_http_request(config["chat_feed_url"], method=config["chat_feed_method"], params=payload, body_format=config.get("chat_feed_body_format", "json"))
                
                items = None
                if isinstance(res, list):
                    items = res
                elif isinstance(res, dict):
                    if isinstance(res.get("items"), list):
                        items = res["items"]
                    elif isinstance(res.get("messages"), list):
                        items = res["messages"]
                    if isinstance(res.get("latestId"), int):
                        last_id = max(last_id, res["latestId"])
                
                if items:
                    for msg in items:
                        if isinstance(msg, dict):
                            nickname = msg.get("nickname") or msg.get("playerName") or msg.get("player")
                            message = msg.get("message") or msg.get("text")
                            if nickname is not None and message is not None:
                                send_message(token, chat_id, f"рџ’¬ [{nickname}]: {message}", message_thread_id=thread_id)
                                last_id = max(last_id, msg.get("id", last_id))
                    
                    config["chat_feed_after_id"] = last_id
                    save_config(config)
        except Exception as e:
            print(f"[-] Ошибка чтения Minecraft-чата: {e}")
        await asyncio.sleep(CHAT_FEED_POLL_INTERVAL_SECONDS)

def main():
    ensure_runtime_files()
    config = load_config()
    
    # Р—Р°РїСѓСЃРє Р°СЃРёРЅС…СЂРѕРЅРЅС‹С… РїРѕС‚РѕРєРѕРІ
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    loop.create_task(telegram_polling_loop(config))
    loop.create_task(minecraft_polling_loop(config))
    
    try:
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        pass

if __name__ == "__main__":
    main()



