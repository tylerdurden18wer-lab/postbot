"""Har bir foydalanuvchi uchun alohida Telegram akkaunt (Telethon) va uning holatini boshqarish."""
import asyncio, time
from telethon import TelegramClient, events, errors
from telethon.sessions import StringSession
import config
from db import q

CL, PH, GC, HOOKS = {}, {}, {}, []   # clientlar, kod so'rovlari, guruhlar keshi, "akkaunt uzildi" xabarchilari
DEAD = (errors.AuthKeyUnregisteredError, errors.SessionRevokedError, errors.SessionExpiredError,
        errors.AuthKeyDuplicatedError, errors.UnauthorizedError)

def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)

def new_client(uid, sess=""):
    c = TelegramClient(StringSession(sess), config.API_ID, config.API_HASH)
    @c.on(events.NewMessage(incoming=True))
    async def on_msg(e):  # bizning e'longa reply qilganlarni sanash
        rt = e.message.reply_to
        if rt and e.is_group and q("select 1 from sent where user_id=? and chat_id=? and msg_id=?", (uid, e.chat_id, rt.reply_to_msg_id)):
            q("insert into replies(user_id,chat_id,msg_id,sender,ts) values(?,?,?,?,?)", (uid, e.chat_id, rt.reply_to_msg_id, e.sender_id, time.time()))
    return c

def has_saved(uid): return bool(q("select 1 from users where uid=? and session!=''", (uid,)))

async def get_client(uid):
    if uid not in CL:
        row = q("select session from users where uid=?", (uid,))
        CL[uid] = new_client(uid, row[0]["session"] if row and row[0]["session"] else "")
    if not CL[uid].is_connected(): await CL[uid].connect()
    return CL[uid]

async def reset(uid):  # clientni yopib, saqlangan sessiyani o'chirish
    c = CL.pop(uid, None)
    if c:
        try: await c.disconnect()
        except Exception: pass
    g = GC.pop(uid, None)
    if g and g.get("task"): g["task"].cancel()
    q("update users set session='' where uid=?", (uid,))

async def dead(uid):  # Telegram sessiyani o'chirgan: tozalaymiz va foydalanuvchiga xabar beramiz
    if not has_saved(uid): return
    log("sessiya o'lgan:", uid)
    await reset(uid)
    for h in HOOKS: asyncio.create_task(h(uid))

async def me_of(uid):  # (client, me). me=None -> akkaunt ulanmagan
    c = await get_client(uid)
    try: me = await c.get_me()
    except DEAD: me = None
    if me is None and has_saved(uid):
        await dead(uid); c = await get_client(uid)
    return c, me

def wipe(uid):
    for t in ("ads", "jobs", "sent", "replies"): q(f"delete from {t} where user_id=?", (uid,))

def save_session(uid, c, me):
    old = q("select tg_id from users where uid=?", (uid,))
    if not old or old[0]["tg_id"] != me.id: wipe(uid)  # boshqa akkaunt ulandi -> eski vazifalar o'chadi
    q("insert or replace into users(uid,session,tg_id) values(?,?,?)", (uid, c.session.save(), me.id))

async def load_groups(u, g):  # guruhlar fonda yuklanadi, kelgani sari ro'yxatga qo'shiladi
    try:
        c = await get_client(u)
        async for d in c.iter_dialogs(ignore_migrated=True):
            if d.is_group: g["d"].append({"id": d.id, "title": d.title or "Guruh", "n": getattr(d.entity, "participants_count", None)})
    except DEAD: g["err"] = "login"; await dead(u)
    except Exception as e: g["err"] = f"{type(e).__name__}: {e}"; log("guruhlar xato:", g["err"])
    g["done"] = True; g["t"] = time.time()

def start_groups(u):
    g = GC[u] = {"d": [], "done": False, "err": None, "t": time.time()}
    g["task"] = asyncio.create_task(load_groups(u, g)); return g
