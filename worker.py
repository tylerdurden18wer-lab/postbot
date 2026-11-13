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

async def run_job(j):
    u = j["user_id"]; api.ERR.pop(j["id"], None)
    c, me = await T.me_of(u)
    if me is None: api.ERR[j["id"]] = "Akkaunt ulanmagan. Ilovaga kirib, qaytadan ulang."; return
    ad = q("select * from ads where id=?", (j["ad_id"],))
    m = await c.get_messages("me", ids=ad[0]["msg_id"]) if ad else None
    if not m: api.ERR[j["id"]] = "E'lon Saqlangan xabarlardan topilmadi (o'chirib yuborilgan bo'lishi mumkin)."; return
    for chat in json.loads(j["chats"]):
        try:
            s = await send(c, chat, m)
            q("insert into sent(user_id,ad_id,chat_id,chat_title,msg_id,ts) values(?,?,?,?,?,?)", (u, j["ad_id"], chat["id"], chat["title"], s.id, time.time()))
        except errors.FloodWaitError as e: await asyncio.sleep(min(e.seconds, 600) + 1)
        except T.DEAD: await T.dead(u); api.ERR[j["id"]] = "Akkaunt Telegram tomonidan uzilgan."; return
        except Exception as e: api.ERR[j["id"]] = f'{chat["title"]}: {type(e).__name__}: {e}'
        await asyncio.sleep(random.uniform(5, 12))  # ban bo'lmasligi uchun pauza

async def run_safe(j):
    try: await run_job(j)
    except Exception as e: api.ERR[j["id"]] = f"{type(e).__name__}: {e}"; T.log("vazifa xato:", e)
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

async def start_bot():
    global BOT_OK, BOT_ERR
    try:
        await bot.start(bot_token=config.BOT_TOKEN); BOT_OK = True
        if config.WEBAPP_URL:
            await asyncio.to_thread(tgapi, "setChatMenuButton", {"menu_button": {"type": "web_app", "text": "Ochish", "web_app": {"url": config.WEBAPP_URL}}})
    except Exception as e: BOT_ERR = f"{type(e).__name__}: {e}"; T.log("BOT XATO:", BOT_ERR)

async def restore():  # server qayta yoqilganda saqlangan akkauntlarni ulaydi
    for row in q("select uid from users where session!=''"):
        try: await T.me_of(row["uid"])
        except Exception as e: T.log("ulanmadi:", row["uid"], type(e).__name__, e)
