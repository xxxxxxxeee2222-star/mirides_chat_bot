# TelegramMiridesBot

Отдельный проект Telegram-бота.

Что умеет:
- `/nick ваш_ник` - обязательно сохранить ник игрока;
- `/mynick` - посмотреть свой сохраненный ник;
- `/mirides текст` - отправить сообщение в игровой чат от имени этого ника;
- `/online` - показать онлайн;
- можно писать и без `/`: `online`, `mirides текст`, `nick ваш_ник`;
- кулдаун 10 секунд на `/mirides` и `/online`.

Как работает:
1. Пользователь пишет `/nick Mirides`.
2. Бот сохраняет ник в `users.json`.
3. Пользователь пишет `/mirides всем привет`.
4. Бот отправляет в ваш API поля `nickname`, `message`, `telegram_id` и `token`.

Настройка:
1. Откройте `config.json`.
2. Вставьте токен Telegram-бота в `telegram_bot_token`.
3. Укажите адреса `mirides_url` и `online_url`.
4. Если нужно, задайте `mirides_token` и `online_token`.

Пример запуска:

```powershell
python bot.py
```
