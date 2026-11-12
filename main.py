import os
if os.path.exists(".env"):  # .env faylidan sozlamalarni o'qish
    for _l in open(".env", encoding="utf-8"):
        _l = _l.strip()
        if _l and not _l.startswith("#") and "=" in _l:
            _k, _v = _l.split("=", 1); os.environ.setdefault(_k.strip(), _v.strip())
import os, json, time, asyncio, hmac, hashlib, sqlite3, random
from urllib.parse import parse_qsl
from fastapi import FastAPI, APIRouter, Header, HTTPException, Depends
from fastapi.responses import FileResponse
from telethon import TelegramClient, events, errors

API_ID = int(os.environ["API_ID"]); API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]; OWNER = int(os.environ["OWNER_ID"])
tg = TelegramClient("session", API_ID, API_HASH)

D = sqlite3.connect("data.db", check_same_thread=False); D.row_factory = sqlite3.Row
D.executescript("""
create table if not exists ads(id integer primary key, msg_id int, title text);
create table if not exists jobs(id integer primary key, ad_id int, chats text, interval int, active int default 1, next_run real default 0);
create table if not exists sent(id integer primary key, ad_id int, chat_id int, chat_title text, msg_id int, ts real);
create table if not exists replies(id integer primary key, chat_id int, msg_id int, user_id int, ts real);
""")
def q(sql, a=()):
    c = D.execute(sql, a); D.commit(); return [dict(r) for r in c.fetchall()]

def auth(x_init_data: str = Header("")):
    d = dict(parse_qsl(x_init_data)); h = d.pop("hash", "")
    s = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
    k = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    ok = hmac.compare_digest(hmac.new(k, s.encode(), hashlib.sha256).hexdigest(), h)
    if not ok or json.loads(d.get("user", "{}")).get("id") != OWNER:
        raise HTTPException(403, "Ruxsat yo'q")

app = FastAPI(); r = APIRouter(prefix="/api", dependencies=[Depends(auth)])
PH = {}

@app.get("/")
def index(): return FileResponse("index.html")

@r.get("/state")
async def state(): return {"auth": await tg.is_user_authorized()}

@r.post("/send_code")
async def send_code(b: dict):
    try:
        x = await tg.send_code_request(b["phone"]); PH.update(phone=b["phone"], hash=x.phone_code_hash)
    except Exception as e: raise HTTPException(400, str(e))
    return {"ok": 1}

@r.post("/login")
async def login(b: dict):
    try:
        await tg.sign_in(PH["phone"], b.get("code"), phone_code_hash=PH["hash"])
    except errors.SessionPasswordNeededError:
        if not b.get("password"): return {"need_password": True}
        try: await tg.sign_in(password=b["password"])
        except Exception as e: raise HTTPException(400, str(e))
    except Exception as e: raise HTTPException(400, str(e))
    return {"ok": 1}

@r.get("/groups")
async def groups():
    return [{"id": d.id, "title": d.title} async for d in tg.iter_dialogs() if d.is_group]

@r.get("/saved")
async def saved():  # E'lonlar "Saved Messages" (Izbrannoe) dan olinadi
    out = []
    async for m in tg.iter_messages("me", limit=25):
        kind = "video" if m.video else "rasm" if m.photo else "sticker" if m.sticker else "fayl" if m.media else "matn"
        out.append({"id": m.id, "text": (m.message or "")[:90], "kind": kind})
    return out

@r.get("/ads")
def ads(): return q("select * from ads")
@r.post("/ads")
def add_ad(b: dict):
    q("insert into ads(msg_id,title) values(?,?)", (b["msg_id"], b["title"] or "E'lon")); return {"ok": 1}
@r.delete("/ads/{i}")
def del_ad(i: int): q("delete from ads where id=?", (i,)); q("delete from jobs where ad_id=?", (i,)); return {"ok": 1}

@r.get("/jobs")
def jobs():
    return [dict(j, chats=json.loads(j["chats"]), title=(q("select title from ads where id=?", (j["ad_id"],)) or [{"title": "?"}])[0]["title"])
            for j in q("select * from jobs")]
@r.post("/jobs")
def add_job(b: dict):
    q("insert into jobs(ad_id,chats,interval) values(?,?,?)", (b["ad_id"], json.dumps(b["chats"]), max(1, int(b["interval"])))); return {"ok": 1}
@r.post("/jobs/{i}/toggle")
def toggle(i: int): q("update jobs set active=1-active where id=?", (i,)); return {"ok": 1}
@r.post("/jobs/{i}/now")
def now(i: int): q("update jobs set next_run=0, active=1 where id=?", (i,)); return {"ok": 1}
@r.delete("/jobs/{i}")
def del_job(i: int): q("delete from jobs where id=?", (i,)); return {"ok": 1}

@r.get("/stats")
def stats():
    return {
        "total": q("select count(*) n from sent")[0]["n"],
        "replies": q("select count(*) n from replies")[0]["n"],
        "people": q("select count(distinct user_id) n from replies")[0]["n"],
        "chats": q("""select s.chat_title title, count(*) n,
            (select count(*) from replies x where x.chat_id=s.chat_id) rep,
            (select count(distinct user_id) from replies x where x.chat_id=s.chat_id) ppl
            from sent s group by s.chat_id order by n desc"""),
    }
app.include_router(r)

@tg.on(events.NewMessage(incoming=True))
async def on_msg(e):  # bizning e'longa reply qilganlarni sanash
    rt = e.message.reply_to
    if rt and e.is_group and q("select 1 from sent where chat_id=? and msg_id=?", (e.chat_id, rt.reply_to_msg_id)):
        q("insert into replies(chat_id,msg_id,user_id,ts) values(?,?,?,?)", (e.chat_id, rt.reply_to_msg_id, e.sender_id, time.time()))

async def run_job(j):
    ad = q("select * from ads where id=?", (j["ad_id"],))
    if not ad: return
    m = await tg.get_messages("me", ids=ad[0]["msg_id"])
    if not m: return
    for c in json.loads(j["chats"]):
        try:
            s = await tg.send_message(c["id"], m)  # matn, premium emoji, video, sticker - aynan o'zidek
            q("insert into sent(ad_id,chat_id,chat_title,msg_id,ts) values(?,?,?,?,?)", (j["ad_id"], c["id"], c["title"], s.id, time.time()))
        except errors.FloodWaitError as e: await asyncio.sleep(e.seconds + 1)
        except Exception as e: print("xato", c["title"], e)
        await asyncio.sleep(random.uniform(5, 12))  # ban bo'lmasligi uchun pauza

async def scheduler():
    while True:
        await asyncio.sleep(15)
        try:
            if not await tg.is_user_authorized(): continue
            for j in q("select * from jobs where active=1 and next_run<=?", (time.time(),)):
                q("update jobs set next_run=? where id=?", (time.time() + j["interval"] * 60, j["id"]))
                await run_job(j)
        except Exception as e: print("scheduler:", e)

@app.on_event("startup")
async def up():
    await tg.connect(); asyncio.create_task(scheduler())
