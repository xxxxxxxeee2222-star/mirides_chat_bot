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
    return config

def save_config(config):
    persisted = {key: value for key, value in config.items() if not str(key).startswith("_")}
    save_json(CONFIG_PATH, persisted)

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
                    
                    # РћР±СЂР°Р±РѕС‚РєР° РєРѕРјР°РЅРґС‹ online
                    if text.lower() == "online":
                        print("[+] РћР±СЂР°Р±РѕС‚РєР° РєРѕРјР°РЅРґС‹ online...")
                        params = {config["online_token_field"]: config["online_token"]}
                        res = send_http_request(config["online_url"], method=config["online_method"], params=params, body_format=config.get("online_body_format", "json"))
                        players = extract_value(res, config["online_response_path"])
                        
                        if isinstance(players, list) and players:
                            players_text = ", ".join(str(p) for p in players)
                        elif isinstance(players, dict) and "list" in players:
                            players_text = ", ".join(str(p) for p in players["list"])
                        else:
                            players_text = "РќР° СЃРµСЂРІРµСЂРµ РЅРёРєРѕРіРѕ РЅРµС‚."
                            
                        send_message(token, chat_id, f"рџЋ® РћРЅР»Р°Р№РЅ: {players_text}")
                    
                    # РџРµСЂРµСЃС‹Р»РєР° СЃРѕРѕР±С‰РµРЅРёСЏ РёР· РўР“ РІ С‡Р°С‚ РёРіСЂС‹
                    elif str(chat_id) == str(config["chat_forward_chat_id"]):
                        if configured_thread_id and thread_id != configured_thread_id:
                            continue

                        # РРіРЅРѕСЂРёСЂСѓРµРј РєРѕРјР°РЅРґС‹ СЃР°РјРѕРіРѕ Р±РѕС‚Р°
                        if text.startswith("/"):
                            continue
                            
                        nickname = msg["from"].get("username") or msg["from"].get("first_name", "User")
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



