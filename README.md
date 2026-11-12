# PostBot — ishga tushirish

1. https://my.telegram.org → "API development tools" → `API_ID` va `API_HASH` oling.
2. @BotFather → /newbot → `BOT_TOKEN`. Keyin /mybots → Bot → Menu Button → Mini App URL (HTTPS manzilingiz).
3. O'z Telegram ID ingizni @userinfobot dan oling (`OWNER_ID`).
4. Ishga tushirish:

```
pip install -r requirements.txt
export API_ID=123 API_HASH=abc BOT_TOKEN=123:xyz OWNER_ID=111
uvicorn main:app --host 0.0.0.0 --port 8000
```
5. HTTPS kerak: serverda Caddy/nginx yoki sinash uchun `cloudflared tunnel --url http://localhost:8000`.
6. Botni oching → Menu tugmasi → akkauntga kiring.

Faqat OWNER_ID egasi ilovadan foydalana oladi. `session.session` va `data.db` fayllarini hech kimga bermang.
