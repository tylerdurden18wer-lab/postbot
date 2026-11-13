"""Mini App uchun HTTP API."""
import json, time, hmac, hashlib, asyncio
from urllib.parse import parse_qsl
from fastapi import APIRouter, Header, HTTPException, Depends
from telethon import errors
import config, tgclients as T
from db import q, D, drop_job

r = router = APIRouter(prefix="/api")
SCHED = {"t": 0, "run": set()}   # rejalashtirgich yurak urishi
LIVE, FLOOD = {}, {}   # vazifalarning jonli holati; Telegram cheklovi tugash vaqti (foydalanuvchi bo'yicha)
ERR = {}  # vazifa xatolari: {job_id: {"_": umumiy, "guruh nomi": xato}} (worker yozadi)
def first_err(jid): return next(iter((ERR.get(jid) or {}).values()), None)

def auth(x_init_data: str = Header("")):  # Telegram Mini App imzosini tekshiradi -> foydalanuvchi ID
    d = dict(parse_qsl(x_init_data)); h = d.pop("hash", "")
    s = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
    k = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    if not h or not hmac.compare_digest(hmac.new(k, s.encode(), hashlib.sha256).hexdigest(), h):
        raise HTTPException(403, "Ruxsat yo'q. Ilovani Telegram ichidan oching (BOT_TOKEN to'g'riligini ham tekshiring).")
    if time.time() - int(d.get("auth_date", 0)) > 3 * 86400:
        raise HTTPException(403, "Sessiya eskirdi. Ilovani yopib, qayta oching.")
    return int(json.loads(d["user"])["id"])

def fullname(me): return (f"{me.first_name or ''} {me.last_name or ''}").strip() or me.username or "Akkaunt"

async def need(u):  # ulangan client yoki 401
    c, me = await T.me_of(u)
    if me is None: raise HTTPException(401, "login")
    return c

@r.get("/state")
async def state(u: int = Depends(auth)):
    c, me = await T.me_of(u)
    if me and u not in T.GC: T.start_groups(u)
    return {"auth": me is not None, "me": fullname(me) if me else None, "phone": getattr(me, "phone", None), "min": config.MIN_INTERVAL, "bot": config.BOT_USERNAME}

@r.post("/send_code")
async def send_code(b: dict, u: int = Depends(auth)):
    c, me = await T.me_of(u)
    if me: return {"already": True}
    phone = "".join(ch for ch in b.get("phone", "") if ch.isdigit() or ch == "+")
    if not phone.startswith("+"): phone = "+" + phone
    try:
        x = await c.send_code_request(phone); T.PH[u] = {"phone": phone, "hash": x.phone_code_hash}
    except errors.PhoneNumberInvalidError: raise HTTPException(400, "Telefon raqam noto'g'ri. Misol: +998901234567")
    except errors.FloodWaitError as e: raise HTTPException(400, f"Juda ko'p urinish. {e.seconds} soniya kuting.")
    except errors.ApiIdInvalidError: raise HTTPException(400, "API_ID / API_HASH noto'g'ri (my.telegram.org dan oling).")
    except Exception as e: raise HTTPException(400, f"{type(e).__name__}: {e}")
    return {"ok": 1}

@r.post("/login")
async def login(b: dict, u: int = Depends(auth)):
    c = await T.get_client(u); pw = b.get("password"); p = T.PH.get(u)
    if not pw and not p: raise HTTPException(400, "Avval kod so'rang.")
    try:
        if pw: await c.sign_in(password=pw)
        else: await c.sign_in(p["phone"], (b.get("code") or "").replace(" ", ""), phone_code_hash=p["hash"])
    except errors.SessionPasswordNeededError: return {"need_password": True}
    except errors.PasswordHashInvalidError: raise HTTPException(400, "Parol noto'g'ri.")
    except errors.PhoneCodeInvalidError: raise HTTPException(400, "Kod noto'g'ri.")
    except errors.PhoneCodeExpiredError: raise HTTPException(400, "Kod eskirgan. Qaytadan kod so'rang.")
    except Exception as e: raise HTTPException(400, f"{type(e).__name__}: {e}")
    me = await c.get_me(); T.save_session(u, c, me); T.PH.pop(u, None); T.start_groups(u)
    return {"ok": 1}

@r.post("/logout")
async def logout(u: int = Depends(auth)):  # akkauntni uzish + barcha ma'lumotlarni o'chirish
    c = await T.get_client(u)
    try: await c.log_out()
    except Exception: pass
    await T.reset(u); T.wipe(u); q("delete from users where uid=?", (u,)); T.PH.pop(u, None)
    return {"ok": 1}

@r.get("/groups")
async def groups(refresh: int = 0, u: int = Depends(auth)):
    g = T.GC.get(u)
    if refresh or not g or (g["done"] and (g["err"] or time.time() - g["t"] > 600)):
        await need(u); g = T.start_groups(u)
    if g["err"] == "login": raise HTTPException(401, "login")
    return {"d": g["d"], "done": g["done"], "err": g["err"]}

@r.post("/new_post")
async def new_post(u: int = Depends(auth)):  # foydalanuvchi botga post yuborishini kutamiz
    c, me = await T.me_of(u)
    if me is None: raise HTTPException(401, "login")
    if me.id != u: raise HTTPException(400, f"Post qo'shish uchun ulangan akkaunt ({fullname(me)}) bilan botga kiring. Hozir boshqa akkauntdasiz.")
    if not config.BOT_USERNAME: raise HTTPException(500, "Bot username aniqlanmadi (BOT_TOKEN ni tekshiring).")
    T.WAIT[u] = time.time(); return {"bot": config.BOT_USERNAME}

@r.get("/posts")
def posts(u: int = Depends(auth)):
    return q("select id,title,kind,preview,created from ads where user_id=? and preview!='' order by id desc", (u,))

@r.delete("/posts/{i}")
def del_post(i: int, u: int = Depends(auth)):
    for j in q("select id from jobs where ad_id=? and user_id=?", (i, u)): drop_job(j["id"])
    q("delete from ads where id=? and user_id=?", (i, u)); return {"ok": 1}

@r.get("/home")
def home(u: int = Depends(auth)):  # bosh sahifa: vazifalar + umumiy holat
    js = jobs(u); now = time.time(); act = [j["next_run"] for j in js if j["active"]]
    return {"jobs": js, "today": q("select count(*) n from sent where user_id=? and ts>?", (u, now - 86400))[0]["n"],
            "flood": FLOOD.get(u, 0) if FLOOD.get(u, 0) > now else 0, "next": min(act) if act else 0, "v": config.VERSION}

@r.get("/jobs")
def jobs(u: int = Depends(auth)):
    return [dict(j, err=first_err(j["id"]), live=LIVE.get(j["id"]), chats=json.loads(j["chats"])) for j in
            q("""select j.*, a.title, a.preview, a.kind,
                 (select count(*) from sent s where s.job_id=j.id) sent_n, (select max(ts) from sent s where s.job_id=j.id) last
                 from jobs j left join ads a on a.id=j.ad_id where j.user_id=? order by j.id desc""", (u,))]

def check_job(b, u):
    if int(b["interval"]) < config.MIN_INTERVAL: raise HTTPException(400, f"Interval eng kamida {config.MIN_INTERVAL} daqiqa bo'lishi kerak.")
    if not b["chats"] or len(b["chats"]) > config.MAX_CHATS: raise HTTPException(400, f"Guruhlar soni 1 dan {config.MAX_CHATS} gacha bo'lishi kerak.")
    if not q("select 1 from ads where id=? and user_id=?", (b["ad_id"], u)): raise HTTPException(400, "Post topilmadi.")

@r.post("/jobs")
def add_job(b: dict, u: int = Depends(auth)):
    check_job(b, u)
    if q("select count(*) n from jobs where user_id=?", (u,))[0]["n"] >= config.MAX_JOBS: raise HTTPException(400, f"Eng ko'pi bilan {config.MAX_JOBS} ta vazifa.")
    q("insert into jobs(user_id,ad_id,chats,interval) values(?,?,?,?)", (u, b["ad_id"], json.dumps(b["chats"]), int(b["interval"]))); return {"ok": 1}

@r.put("/jobs/{i}")
def edit_job(i: int, b: dict, u: int = Depends(auth)):  # post, guruhlar va vaqtni tahrirlash
    if not q("select 1 from jobs where id=? and user_id=?", (i, u)): raise HTTPException(404, "Vazifa topilmadi.")
    check_job(b, u); iv = int(b["interval"])
    q("update jobs set ad_id=?, chats=?, interval=?, next_run=min(next_run, ?) where id=?", (b["ad_id"], json.dumps(b["chats"]), iv, time.time() + iv * 60, i)); return {"ok": 1}

@r.post("/jobs/{i}/chats")
def job_add_chats(i: int, b: dict, u: int = Depends(auth)):  # vazifaga bitta/bir nechta guruh qo'shish
    row = q("select chats from jobs where id=? and user_id=?", (i, u))
    if not row: raise HTTPException(404, "Vazifa topilmadi.")
    chats = json.loads(row[0]["chats"]); have = {c["id"] for c in chats}
    for c in b.get("add", []):
        if c["id"] in have: continue
        if len(chats) >= config.MAX_CHATS: raise HTTPException(400, f"Bitta vazifada eng ko'pi bilan {config.MAX_CHATS} ta guruh.")
        chats.append({"id": c["id"], "title": c["title"]}); have.add(c["id"])
    q("update jobs set chats=? where id=?", (json.dumps(chats), i)); return {"ok": 1}

@r.delete("/jobs/{i}/chats/{cid}")
def job_del_chat(i: int, cid: int, u: int = Depends(auth)):  # guruhni shu vazifadan chiqarish
    row = q("select chats from jobs where id=? and user_id=?", (i, u))
    if not row: raise HTTPException(404, "Vazifa topilmadi.")
    chats = [c for c in json.loads(row[0]["chats"]) if c["id"] != cid]
    if not chats: raise HTTPException(400, "Kamida 1 ta guruh qolishi kerak. Butun vazifani o'chirmoqchi bo'lsangiz, 🗑 ni bosing.")
    q("update jobs set chats=? where id=?", (json.dumps(chats), i)); return {"ok": 1}

@r.post("/pause_all")
def pause_all(u: int = Depends(auth)): q("update jobs set active=0 where user_id=?", (u,)); return {"ok": 1}

@r.post("/groups/leave")
async def leave_group(b: dict, u: int = Depends(auth)):  # Telegram'da guruhdan chiqish + barcha vazifalardan olib tashlash
    c = await need(u); cid = int(b["id"])
    try: await c.delete_dialog(cid)
    except T.DEAD: await T.dead(u); raise HTTPException(401, "login")
    except Exception as e: raise HTTPException(400, f"Guruhdan chiqib bo'lmadi: {type(e).__name__}: {e}")
    gone = 0
    for j in q("select id, chats from jobs where user_id=?", (u,)):
        old = json.loads(j["chats"]); new = [x for x in old if x["id"] != cid]
        if len(new) == len(old): continue
        if new: q("update jobs set chats=? where id=?", (json.dumps(new), j["id"]))
        else: drop_job(j["id"]); gone += 1
    g = T.GC.get(u)
    if g: g["d"] = [x for x in g["d"] if x["id"] != cid]
    return {"ok": 1, "jobs_removed": gone}

@r.get("/jobs/{i}")
def job_detail(i: int, u: int = Depends(auth)):  # bitta vazifaning o'z statistikasi
    row = q("select j.*, a.title, a.preview, a.kind from jobs j left join ads a on a.id=j.ad_id where j.id=? and j.user_id=?", (i, u))
    if not row: raise HTTPException(404, "Vazifa topilmadi.")
    j = dict(row[0], chats=json.loads(row[0]["chats"])); errs = ERR.get(i) or {}
    z = "exists(select 1 from sent z where z.job_id=? and z.chat_id=r.chat_id and z.msg_id=r.msg_id)"
    tot = q("select count(*) n, max(ts) last from sent where job_id=? and user_id=?", (i, u))[0]
    rp = q(f"select count(*) n, count(distinct sender) p from replies r where r.user_id=? and {z}", (u, i))[0]
    per = {x["chat_id"]: x for x in q(f"""select chat_id, count(*) n, max(ts) last,
        (select count(*) from replies r where r.user_id=s.user_id and r.chat_id=s.chat_id and {z}) rep,
        (select count(distinct sender) from replies r where r.user_id=s.user_id and r.chat_id=s.chat_id and {z}) ppl
        from sent s where s.job_id=? and s.user_id=? group by chat_id""", (i, i, i, u))}
    groups = [{"id": c["id"], "title": c["title"], "n": per.get(c["id"], {}).get("n", 0), "last": per.get(c["id"], {}).get("last"),
               "rep": per.get(c["id"], {}).get("rep", 0), "ppl": per.get(c["id"], {}).get("ppl", 0), "err": errs.get(c["title"])} for c in j["chats"]]
    return {"job": j, "total": tot["n"], "last": tot["last"], "replies": rp["n"], "people": rp["p"], "err": errs.get("_"), "live": LIVE.get(i), "groups": groups}

@r.post("/jobs/{i}/toggle")
def toggle(i: int, u: int = Depends(auth)): q("update jobs set active=1-active where id=? and user_id=?", (i, u)); return {"ok": 1}
@r.post("/jobs/{i}/now")
def now(i: int, u: int = Depends(auth)): q("update jobs set next_run=0, active=1 where id=? and user_id=?", (i, u)); return {"ok": 1}
@r.delete("/jobs/{i}")
def del_job(i: int, u: int = Depends(auth)):
    if q("select 1 from jobs where id=? and user_id=?", (i, u)): drop_job(i)
    return {"ok": 1}

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

@r.get("/log")
def get_log(u: int = Depends(auth)): return [{"t": t, "m": m} for t, m in reversed(T.EV.get(u, []))]

@r.post("/test_send")
async def test_send(u: int = Depends(auth)):  # yuborish umuman ishlayaptimi: "Saqlangan xabarlar"ga sinov xabari
    c = await need(u); t = time.time()
    try: await asyncio.wait_for(c.send_message("me", "✅ PostBot sinov xabari: yuborish ishlayapti"), 30)
    except asyncio.TimeoutError: raise HTTPException(400, "Telegram 30 soniya ichida javob bermadi.")
    except errors.FloodWaitError as e: raise HTTPException(400, f"Telegram {e.seconds} soniya kutishni talab qilmoqda (cheklov).")
    except Exception as e: raise HTTPException(400, f"{type(e).__name__}: {e}")
    T.ev(u, "📨 Sinov xabari muvaffaqiyatli yuborildi"); return {"ok": 1, "ms": int((time.time() - t) * 1000)}

@r.get("/diag")
async def diag(u: int = Depends(auth)):  # qadamma-qadam tekshiruv: muammo aynan qayerdaligini ko'rsatadi
    out = [{"n": "Mini App imzosi (initData)", "ok": True, "d": f"user_id={u}", "ms": 0}]; box = {}
    async def step(name, fn):
        t = time.time()
        try: d = await fn(); ok = True
        except Exception as e: d = f"{type(e).__name__}: {e}"; ok = False
        out.append({"n": name, "ok": ok, "d": str(d), "ms": int((time.time() - t) * 1000)}); return ok
    async def s1(): box["c"] = await T.get_client(u); return "ulandi" if box["c"].is_connected() else "ulanmagan"
    async def s2():
        me = await box["c"].get_me(); box["me"] = me
        if me is None: raise Exception("Akkaunt ulanmagan (kirish kerak yoki sessiya o'lgan)")
        return f"{fullname(me)} (id {me.id})"
    async def s3(): return f"{len(await box['c'].get_messages('me', limit=5))} ta xabar o'qildi"
    async def s4():
        ds = await box["c"].get_dialogs(limit=40); return f"{len(ds)} chat, shundan {sum(1 for d in ds if d.is_group)} ta guruh"
    if await step("Telegram serveriga ulanish", s1) and await step("Akkaunt (get_me)", s2):
        await step("Saqlangan xabarlarni o'qish", s3); await step("Chatlar ro'yxati", s4)
    age = int(time.time() - SCHED["t"]); mine = q("select id, active, next_run from jobs where user_id=?", (u,))
    run = sum(1 for j in mine if j["id"] in SCHED["run"]); act = [j["next_run"] for j in mine if j["active"]]
    out.append({"n": "Rejalashtirgich", "ok": age < 60, "ms": 0, "d": f"oxirgi tekshiruv {age} soniya oldin · faol vazifa: {len(act)} · hozir bajarilmoqda: {run}" + (f" · keyingisi {'hozir' if min(act) <= time.time() else time.strftime('%H:%M', time.localtime(min(act)))}" if act else "")})
    fl = FLOOD.get(u, 0)
    out.append({"n": "Telegram cheklovi", "ok": fl < time.time(), "ms": 0, "d": "yo'q" if fl < time.time() else f"{time.strftime('%H:%M', time.localtime(fl))} gacha kutiladi"})
    out.append({"n": "Bazada saqlangan sessiya", "ok": T.has_saved(u), "d": "bor" if T.has_saved(u) else "yo'q", "ms": 0})
    return out
