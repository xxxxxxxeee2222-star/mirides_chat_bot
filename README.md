# TelegramMiridesBot

Пиши в группе только так:

```text
nick ваш_ник
online
chat ваш_текст
playtime top
```

Примеры:

```text
nick Kuni_Masterr
online
chat всем привет
playtime top
```

Для админов:

```text
whois @username
whois nick
ban @username
ban nick
unban @username
```

Можно банить и по ответу на сообщение пользователя:

```text
ban
unban
whois
```

Что делает бот:
- `nick` сохраняет игровой ник и привязку к Telegram ID / username;
- `online` показывает онлайн сервера;
- `chat` отправляет сообщение в Minecraft-чат;
- `playtime top` показывает топ по плейтайму;
- `whois` показывает `nick`, `@username`, имя и `telegram id`;
- `ban` и `unban` блокируют или разблокируют человека только внутри бота.
