# PostBot

Har kim o'z Telegram akkauntini ulab, guruhlariga e'lonlarni avtomatik yuboradi.

Tuzilishi: main.py (ilova) · config.py · db.py · tgclients.py (akkauntlar) · api.py (Mini App API) · worker.py (yuboruvchi, nazoratchi, bot) · index.html (Mini App)

Railway Variables: API_ID, API_HASH, BOT_TOKEN, WEBAPP_URL (Railway bergan https manzil), DATA_DIR=/data (Volume /data ga ulangan bo'lsin).
Ixtiyoriy: MIN_INTERVAL (5), MAX_JOBS (10), MAX_CHATS (50).
Replika soni 1 bo'lsin. Tekshiruv: <WEBAPP_URL>/health va Mini App ichidagi "Tekshiruv" tugmasi.

## Ishlash tartibi
1. Mini App → akkauntni ulash.
2. ➕ Yangi post → botga o'tib postni yuborish (matn/rasm/video/premium emoji/stiker) → bot "qabul qilindi" deydi.
3. Ilovaga qaytish → post tanlanadi → guruhlar → vaqt → Saqlash. Yana e'lon uchun yana ➕ bosiladi.
