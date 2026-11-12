import os
if os.path.exists(".env"):  # .env faylidan sozlamalarni o'qish
    for _l in open(".env", encoding="utf-8"):
        _l = _l.strip()
        if _l and not _l.startswith("#") and "=" in _l:
            _k, _v = _l.split("=", 1); os.environ.setdefault(_k.strip(), _v.strip().strip('"'))
import json, time, asyncio, hmac, hashlib, sqlite3, random, glob, urllib.request
from urllib.parse import parse_qsl
from fastapi import FastAPI, APIRouter, Header, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from telethon import TelegramClient, events, errors

API_ID = int(os.environ["API_ID"]); API_HASH = os.environ["API_HASH"]; BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBAPP_URL = os.environ.get("WEBAPP_URL", "").strip()
MIN_INTERVAL = int(os.environ.get("MIN_INTERVAL", "5"))   # eng kam interval (daqiqa)
MAX_JOBS = int(os.environ.get("MAX_JOBS", "10"))          # bitta foydalanuvchiga vazifalar soni
MAX_CHATS = int(os.environ.get("MAX_CHATS", "50"))        # bitta vazifadagi guruhlar soni
DATA = os.environ.get("DATA_DIR", "."); SD = os.path.join(DATA, "sessions")
os.makedirs(SD, exist_ok=True)

D = sqlite3.connect(os.path.join(DATA, "postbot.db"), check_same_thread=False); D.row_factory = sqlite3.Row
D.executescript("""
create table if not exists ads(id integer primary key, user_id int, msg_id int, title text);
create table if not exists jobs(id integer primary key, user_id int, ad_id int, chats text, interval int, active int default 1, next_run real default 0);
create table if not exists sent(id integer primary key, user_id int, ad_id int, chat_id int, chat_title text, msg_id int, ts real);
create table if not exists replies(id integer primary key, user_id int, chat_id int, msg_id int, sender int, ts real);
""")
def q(sql, a=()):
    c = D.execute(sql, a); D.commit(); return [dict(r) for r in c.fetchall()]

def auth(x_init_data: str = Header("")):  # Telegram Mini App imzosini tekshiradi, foydalanuvchi ID sini qaytaradi
    d = dict(parse_qsl(x_init_data)); h = d.pop("hash", "")
    s = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
    k = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    if not h or not hmac.compare_digest(hmac.new(k, s.encode(), hashlib.sha256).hexdigest(), h):
        raise HTTPException(403, "Ruxsat yo'q. Ilovani Telegram ichidan oching.")
    if time.time() - int(d.get("auth_date", 0)) > 3 * 86400:
        raise HTTPException(403, "Sessiya eskirdi. Ilovani yopib, qayta oching.")
    return int(json.loads(d["user"])["id"])

CL, PH, GC, ERR, RUN = {}, {}, {}, {}, set()

def make_client(uid):
    c = TelegramClient(os.path.join(SD, str(uid)), API_ID, API_HASH)
    @c.on(events.NewMessage(incoming=True))
    async def on_msg(e):  # bizning e'longa reply qilganlarni sanash
        rt = e.message.reply_to
        if rt and e.is_group and q("select 1 from sent where user_id=? and chat_id=? and msg_id=?", (uid, e.chat_id, rt.reply_to_msg_id)):
            q("insert into replies(user_id,chat_id,msg_id,sender,ts) values(?,?,?,?,?)", (uid, e.chat_id, rt.reply_to_msg_id, e.sender_id, time.time()))
    return c

async def cl(uid):
    if uid not in CL: CL[uid] = make_client(uid)
    if not CL[uid].is_connected(): await CL[uid].connect()
    return CL[uid]

app = FastAPI()
@app.exception_handler(Exception)
async def on_err(request, exc): return JSONResponse({"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)
r = APIRouter(prefix="/api")

@app.get("/")
def index(): return FileResponse("index.html")

@r.get("/state")
async def state(u: int = Depends(auth)):
    c = await cl(u); ok = bool(await c.is_user_authorized()); me = await c.get_me() if ok else None
    return {"auth": ok, "me": getattr(me, "first_name", None), "phone": getattr(me, "phone", None), "min": MIN_INTERVAL}

@r.post("/send_code")
async def send_code(b: dict, u: int = Depends(auth)):
    c = await cl(u)
    try:
        x = await c.send_code_request(b["phone"].strip()); PH[u] = {"phone": b["phone"].strip(), "hash": x.phone_code_hash}
    except errors.PhoneNumberInvalidError: raise HTTPException(400, "Telefon raqam noto'g'ri. Misol: +998901234567")
    except errors.FloodWaitError as e: raise HTTPException(400, f"Juda ko'p urinish. {e.seconds} soniya kuting.")
    except Exception as e: raise HTTPException(400, str(e))
    return {"ok": 1}

@r.post("/login")
async def login(b: dict, u: int = Depends(auth)):
    c = await cl(u); p = PH.get(u)
    if not p: raise HTTPException(400, "Avval kod so'rang.")
    try:
        await c.sign_in(p["phone"], b.get("code"), phone_code_hash=p["hash"])
    except errors.SessionPasswordNeededError:
        if not b.get("password"): return {"need_password": True}
        try: await c.sign_in(password=b["password"])
        except errors.PasswordHashInvalidError: raise HTTPException(400, "Parol noto'g'ri.")
    except errors.PhoneCodeInvalidError: raise HTTPException(400, "Kod noto'g'ri.")
    except errors.PhoneCodeExpiredError: raise HTTPException(400, "Kod eskirgan. Qaytadan kod so'rang.")
    except Exception as e: raise HTTPException(400, str(e))
    PH.pop(u, None); return {"ok": 1}

@r.post("/logout")
async def logout(u: int = Depends(auth)):  # akkauntni uzish va barcha ma'lumotlarni o'chirish
    c = await cl(u)
    try: await c.log_out()
    except Exception: pass
    CL.pop(u, None); GC.pop(u, None); PH.pop(u, None)
    for t in ("ads", "jobs", "sent", "replies"): q(f"delete from {t} where user_id=?", (u,))
    for f in glob.glob(os.path.join(SD, f"{u}.session*")):
        try: os.remove(f)
        except Exception: pass
    return {"ok": 1}

@r.get("/groups")
async def groups(refresh: int = 0, u: int = Depends(auth)):
    g = GC.get(u)
    if refresh or not g or time.time() - g["t"] > 600:
        c = await cl(u)
        GC[u] = g = {"t": time.time(), "d": [{"id": d.id, "title": d.title} async for d in c.iter_dialogs() if d.is_group]}
    return g["d"]

@r.get("/saved")
async def saved(u: int = Depends(auth)):  # e'lonlar "Saqlangan xabarlar" dan olinadi
    c = await cl(u); out = []
    async for m in c.iter_messages("me", limit=25):
        kind = "video" if m.video else "rasm" if m.photo else "sticker" if m.sticker else "fayl" if m.media else "matn"
        out.append({"id": m.id, "text": (m.message or "")[:90], "kind": kind})
    return out

@r.get("/jobs")
def jobs(u: int = Depends(auth)):
    return [dict(j, err=ERR.get(j["id"]), chats=json.loads(j["chats"])) for j in
            q("select j.*, a.title from jobs j left join ads a on a.id=j.ad_id where j.user_id=? order by j.id desc", (u,))]

@r.post("/jobs")
def add_job(b: dict, u: int = Depends(auth)):
    if int(b["interval"]) < MIN_INTERVAL: raise HTTPException(400, f"Interval eng kamida {MIN_INTERVAL} daqiqa bo'lishi kerak.")
    if not b["chats"] or len(b["chats"]) > MAX_CHATS: raise HTTPException(400, f"Guruhlar soni 1 dan {MAX_CHATS} gacha bo'lishi kerak.")
    if q("select count(*) n from jobs where user_id=?", (u,))[0]["n"] >= MAX_JOBS: raise HTTPException(400, f"Eng ko'pi bilan {MAX_JOBS} ta vazifa.")
    c = D.execute("insert into ads(user_id,msg_id,title) values(?,?,?)", (u, b["msg_id"], b.get("title") or "E'lon")); D.commit()
    q("insert into jobs(user_id,ad_id,chats,interval) values(?,?,?,?)", (u, c.lastrowid, json.dumps(b["chats"]), int(b["interval"]))); return {"ok": 1}

@r.post("/jobs/{i}/toggle")
def toggle(i: int, u: int = Depends(auth)): q("update jobs set active=1-active where id=? and user_id=?", (i, u)); return {"ok": 1}
@r.post("/jobs/{i}/now")
def now(i: int, u: int = Depends(auth)): q("update jobs set next_run=0, active=1 where id=? and user_id=?", (i, u)); return {"ok": 1}
@r.delete("/jobs/{i}")
def del_job(i: int, u: int = Depends(auth)): q("delete from jobs where id=? and user_id=?", (i, u)); return {"ok": 1}

@r.get("/stats")
def stats(u: int = Depends(auth)):
    return {
        "total": q("select count(*) n from sent where user_id=?", (u,))[0]["n"],
        "replies": q("select count(*) n from replies where user_id=?", (u,))[0]["n"],
        "people": q("select count(distinct sender) n from replies where user_id=?", (u,))[0]["n"],
        "chats": q("""select s.chat_title title, count(*) n,
            (select count(*) from replies x where x.user_id=s.user_id and x.chat_id=s.chat_id) rep,
            (select count(distinct sender) from replies x where x.user_id=s.user_id and x.chat_id=s.chat_id) ppl
            from sent s where s.user_id=? group by s.chat_id order by n desc""", (u,)),
    }
app.include_router(r)

# ---------- yuboruvchi ----------
async def send(c, chat, m):
    try: return await c.send_message(chat["id"], m)  # matn, premium emoji, video, stiker - aynan o'zidek
    except ValueError:
        await c.get_dialogs(); return await c.send_message(chat["id"], m)

async def run_job(j):
    u = j["user_id"]; ERR.pop(j["id"], None)
    c = await cl(u)
    if not await c.is_user_authorized(): return
    ad = q("select * from ads where id=?", (j["ad_id"],))
    m = await c.get_messages("me", ids=ad[0]["msg_id"]) if ad else None
    if not m: ERR[j["id"]] = "E'lon Saqlangan xabarlardan topilmadi (o'chirib yuborilgan bo'lishi mumkin)."; return
    for chat in json.loads(j["chats"]):
        try:
            s = await send(c, chat, m)
            q("insert into sent(user_id,ad_id,chat_id,chat_title,msg_id,ts) values(?,?,?,?,?,?)", (u, j["ad_id"], chat["id"], chat["title"], s.id, time.time()))
        except errors.FloodWaitError as e: await asyncio.sleep(min(e.seconds, 600) + 1)
        except Exception as e: ERR[j["id"]] = f'{chat["title"]}: {type(e).__name__}: {e}'
        await asyncio.sleep(random.uniform(5, 12))  # ban bo'lmasligi uchun pauza

async def run_safe(j):
    try: await run_job(j)
    except Exception as e: ERR[j["id"]] = f"{type(e).__name__}: {e}"
    finally: RUN.discard(j["id"])

async def scheduler():
    while True:
        await asyncio.sleep(15)
        try:
            for j in q("select * from jobs where active=1 and next_run<=?", (time.time(),)):
                if j["id"] in RUN: continue
                RUN.add(j["id"]); q("update jobs set next_run=? where id=?", (time.time() + j["interval"] * 60, j["id"]))
                asyncio.create_task(run_safe(j))
        except Exception as e: print("scheduler:", e)

# ---------- bot (/start) ----------
bot = TelegramClient(os.path.join(DATA, "bot"), API_ID, API_HASH)

def tgapi(method, data):
    req = urllib.request.Request(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json.dumps(data).encode(), {"Content-Type": "application/json"})
    urllib.request.urlopen(req)

@bot.on(events.NewMessage(pattern=r"^/start"))
async def start_cmd(e):
    try:
        await e.respond("Salom! 👋 PostBot — guruhlaringizga e'lonlarni avtomatik, belgilangan vaqtda yuboradi.")
        if WEBAPP_URL:
            await asyncio.to_thread(tgapi, "sendMessage", {"chat_id": e.chat_id, "text": "Boshlash uchun tugmani bosing 👇",
                "reply_markup": {"inline_keyboard": [[{"text": "📣 Ochish", "web_app": {"url": WEBAPP_URL}}]]}})
    except Exception as ex: print("start xato:", repr(ex))

@app.on_event("startup")
async def up():
    await bot.start(bot_token=BOT_TOKEN)
    if WEBAPP_URL:
        try: await asyncio.to_thread(tgapi, "setChatMenuButton", {"menu_button": {"type": "web_app", "text": "Ochish", "web_app": {"url": WEBAPP_URL}}})
        except Exception as e: print("menu button:", e)
    for f in glob.glob(os.path.join(SD, "*.session")):  # saqlangan akkauntlarni qayta ulash (reply sanash uchun)
        try: await cl(int(os.path.basename(f).split(".")[0]))
        except Exception as e: print("ulanmadi:", f, e)
    asyncio.create_task(scheduler())
