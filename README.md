# TelegramMiridesBot

Пиши в группе так:

```text
nick ваш_ник
online
chat ваш_текст
playtime top
```

Админские команды без конфликта с Iris:

```text
bantgbot @username|id|nick
unbantgbot @username|id|nick
whoistgbot @username|id|nick
```

Можно и ответом на сообщение пользователя:

```text
bantgbot
unbantgbot
whoistgbot
```

Админы задаются в отдельном файле:
[admins.json](/C:/Users/cekta/Desktop/пвпвап/TelegramMiridesBot/admins.json)

Пример:

```json
{
  "admin_ids": [
    "123456789"
  ]
}
```

Что умеет бот:
- `nick` сохраняет игровой ник и привязку к Telegram;
- `online` показывает онлайн сервера;
- `chat` отправляет сообщение в Minecraft;
- `playtime top` показывает топ по плейтайму;
- `whoistgbot` показывает `nick`, `@username`, имя и `telegram id`;
- `bantgbot` и `unbantgbot` блокируют или разблокируют человека только внутри бота.
