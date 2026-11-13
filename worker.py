"""Fon ishlari: e'lon yuboruvchi, akkaunt nazoratchisi, /start boti."""
import os, json, time, asyncio, random, hashlib, urllib.request
from telethon import TelegramClient, events, errors
from telethon.sessions import StringSession
import config, tgclients as T, api
from db import q

RUN = set(); BOT_OK = False; BOT_ERR = ""

def tgapi(method, data):  # Telegram Bot API
    req = urllib.request.Request(f"https://api.telegram.org/bot{config.BOT_TOKEN}/{method}", json.dumps(data).encode(), {"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=20).read()

def open_btn(): return {"inline_keyboard": [[{"text": "📣 Ochish", "web_app": {"url": config.WEBAPP_URL}}]]}

async def notify_dead(uid):  # akkaunt Telegram tomonidan uzilsa, foydalanuvchiga xabar beramiz
    try:
        d = {"chat_id": uid, "text": "⚠️ Telegram akkauntingiz xizmatdan uzildi (sessiya tugadi), avtomatik yuborish to'xtadi.\nQayta ulash uchun tugmani bosing 👇"}
        if config.WEBAPP_URL: d["reply_markup"] = open_btn()
        await asyncio.to_thread(tgapi, "sendMessage", d)
    except Exception as e: T.log("xabar yuborilmadi:", e)
T.HOOKS.append(notify_dead)

async def send(c, chat, m):
    try: return await c.send_message(chat["id"], m)  # matn, premium emoji, video, stiker - aynan o'zidek
    except ValueError:
        await c.get_dialogs(); return await c.send_message(chat["id"], m)

FRIENDLY = {"MessageEmptyError": "Post bo'sh yoki qo'llab-quvvatlanmaydigan turda. Postni o'chirib, qaytadan qo'shing.",
    "ChatWriteForbiddenError": "Bu guruhga yozish taqiqlangan.", "UserBannedInChannelError": "Siz bu guruhda cheklangansiz (ban).",
    "ChatAdminRequiredError": "Bu guruhga faqat adminlar yoza oladi.", "ChannelPrivateError": "Guruhga kirish yo'q (chiqib ketgansiz yoki guruh yopilgan).",
    "PeerIdInvalidError": "Guruh topilmadi.", "SlowModeWaitError": "Guruhda sekin rejim yoqilgan, keyingi safar urinadi.",
    "ChatRestrictedError": "Guruh sizga yozishni cheklagan."}
def friendly(e): return FRIENDLY.get(type(e).__name__, f"{type(e).__name__}: {e}")

async def run_job(j):
    u = j["user_id"]; E = api.ERR[j["id"]] = {}
    c, me = await T.me_of(u)
    if me is None: E["_"] = "Akkaunt ulanmagan. Ilovaga kirib, qaytadan ulang."; return
    ad = q("select * from ads where id=?", (j["ad_id"],))
    m = await c.get_messages(ad[0]["peer"] or "me", ids=ad[0]["msg_id"]) if ad else None
    if not m: E["_"] = "Post topilmadi (bot bilan chatdan o'chirib yuborilgan bo'lishi mumkin). Postni qaytadan qo'shing."; return
    if not (m.message or m.media): E["_"] = FRIENDLY["MessageEmptyError"]; return
    for chat in json.loads(j["chats"]):
        try:
            s = await send(c, chat, m)
            q("insert into sent(user_id,ad_id,job_id,chat_id,chat_title,msg_id,ts) values(?,?,?,?,?,?,?)", (u, j["ad_id"], j["id"], chat["id"], chat["title"], s.id, time.time()))
        except errors.FloodWaitError as e: await asyncio.sleep(min(e.seconds, 600) + 1)
        except T.DEAD: await T.dead(u); E["_"] = "Akkaunt Telegram tomonidan uzilgan."; return
        except Exception as e:
            if type(e).__name__ in ("PeerFloodError", "UserDeactivatedBanError", "UserDeactivatedError", "PhoneNumberBannedError"):
                q("update jobs set active=0 where user_id=?", (u,))   # Telegram cheklov qo'ydi: hamma vazifa to'xtaydi
                E["_"] = "Telegram akkauntingizga cheklov qo'ydi (spam deb topildi). Barcha vazifalar to'xtatildi. @SpamBot ga yozib holatni tekshiring."; return
            E[chat["title"]] = friendly(e)
        await asyncio.sleep(random.uniform(5, 12))  # ban bo'lmasligi uchun pauza

async def run_safe(j):
    try: await run_job(j)
    except Exception as e: api.ERR[j["id"]] = {"_": friendly(e)}; T.log("vazifa xato:", e)
    finally: RUN.discard(j["id"])

async def scheduler():
    while True:
        await asyncio.sleep(15)
        try:
            for j in q("select * from jobs where active=1 and next_run<=?", (time.time(),)):
                if j["id"] in RUN: continue
                RUN.add(j["id"]); q("update jobs set next_run=? where id=?", (time.time() + j["interval"] * 60, j["id"]))
                asyncio.create_task(run_safe(j))
        except Exception as e: T.log("scheduler:", e)

async def watchdog():  # har 2 daqiqada akkauntlar tirikligini tekshiradi
    while True:
        await asyncio.sleep(120)
        for row in q("select uid from users where session!=''"):
            try: await T.me_of(row["uid"])
            except Exception as e: T.log("watchdog:", row["uid"], type(e).__name__, e)

bot = TelegramClient(StringSession(), config.API_ID, config.API_HASH)
@bot.on(events.NewMessage(pattern=r"^/start"))
async def start_cmd(e):
    try:
        await e.respond("Salom! 👋 PostBot guruhlaringizga e'lonlarni avtomatik, belgilangan vaqtda yuboradi.")
        if config.WEBAPP_URL:
            await asyncio.to_thread(tgapi, "sendMessage", {"chat_id": e.chat_id, "text": "Boshlash uchun tugmani bosing 👇", "reply_markup": open_btn()})
        else: await e.respond("WEBAPP_URL sozlanmagan (Railway > Variables).")
    except Exception as ex: T.log("start xato:", repr(ex))

def kind_of(m):
    return "video" if m.video else "rasm" if m.photo else "sticker" if m.sticker else "fayl" if m.media else "matn"

def reply(chat_id, text):  # bot javobi + Mini App tugmasi
    d = {"chat_id": chat_id, "text": text}
    if config.WEBAPP_URL: d["reply_markup"] = open_btn()
    tgapi("sendMessage", d)

async def capture(uid, text, date, grouped, kind=None):
    """Foydalanuvchi botga yuborgan postni uning O'Z akkauntidagi bot bilan chatdan topib, saqlaydi."""
    if not T.has_saved(uid): return "noauth"
    if time.time() - T.WAIT.get(uid, 0) > 900: return "nowait"
    if grouped and T.LASTG.get(uid) == grouped: return "album"
    c, me = await T.me_of(uid)
    if me is None: return "noauth"
    if me.id != uid: return "other"
    found = None
    for _ in range(4):
        cand = [m for m in await c.get_messages(config.BOT_USERNAME, limit=8)
                if m.out and (m.message or m.media) and (m.message or "") == (text or "") and (kind is None or kind_of(m) == kind)
                and abs((m.date - date).total_seconds()) < 120]
        if cand: found = min(cand, key=lambda m: abs((m.date - date).total_seconds())); break
        await asyncio.sleep(1.5)
    if not found: return "notfound"
    if q("select 1 from ads where user_id=? and peer=? and msg_id=?", (uid, config.BOT_USERNAME, found.id)): return "dup"
    kind = kind_of(found); body = (found.message or "").strip()
    prev = (body[:140] or {"video": "🎬 Video", "rasm": "🖼 Rasm", "sticker": "🎭 Stiker", "fayl": "📎 Fayl"}.get(kind, "Post"))
    q("insert into ads(user_id,msg_id,title,peer,kind,preview,created) values(?,?,?,?,?,?,?)",
      (uid, found.id, prev[:30], config.BOT_USERNAME, kind, prev, time.time()))
    T.WAIT[uid] = time.time()
    if grouped: T.LASTG[uid] = grouped
    return "ok"

REPLY = {"ok": "✅ Post qabul qilindi! Ilovaga qaytib, guruhlar va vaqtni tanlang.\nYana post qo'shmoqchi bo'lsangiz, shu yerga yuboravering.",
         "nowait": "Yangi post qo'shish uchun avval ilovada «➕ Yangi post qo'shish» tugmasini bosing.",
         "noauth": "Avval ilovada Telegram akkauntingizni ulang.",
         "other": "Post qo'shish uchun ilovaga ulangan Telegram akkaunt bilan yuboring.",
         "notfound": "Postni topa olmadim. Qaytadan yuboring yoki ilovada «Yangi post» ni bosing.",
         "dup": "Bu post allaqachon qo'shilgan.", "error": "Xatolik yuz berdi, qaytadan urinib ko'ring."}

@bot.on(events.NewMessage(incoming=True))
async def on_private(e):  # botga yuborilgan oddiy xabar = yangi post
    if not e.is_private or (e.raw_text or "").startswith("/"): return
    try: res = await capture(e.sender_id, e.message.message, e.message.date, e.message.grouped_id, kind_of(e.message))
    except Exception as ex: T.log("capture xato:", type(ex).__name__, ex); res = "error"
    if res == "album": return
    try: await asyncio.to_thread(reply, e.sender_id, REPLY[res])
    except Exception as ex: T.log("javob yuborilmadi:", ex)

async def start_bot():
    global BOT_OK, BOT_ERR
    try:
        config.BOT_USERNAME = json.loads(await asyncio.to_thread(tgapi, "getMe", {}))["result"]["username"]
    except Exception as e: BOT_ERR = f"getMe: {type(e).__name__}: {e}"; T.log("BOT XATO:", BOT_ERR); return
    try:
        await bot.start(bot_token=config.BOT_TOKEN); BOT_OK = True
        if config.WEBAPP_URL:
            await asyncio.to_thread(tgapi, "setChatMenuButton", {"menu_button": {"type": "web_app", "text": "Ochish", "web_app": {"url": config.WEBAPP_URL}}})
    except Exception as e: BOT_ERR = f"{type(e).__name__}: {e}"; T.log("BOT XATO:", BOT_ERR)

async def restore():  # server qayta yoqilganda saqlangan akkauntlarni ulaydi
    for row in q("select uid from users where session!=''"):
        try: await T.me_of(row["uid"])
        except Exception as e: T.log("ulanmadi:", row["uid"], type(e).__name__, e)
