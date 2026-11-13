"""PostBot: ishga tushirish ->  uvicorn main:app --host 0.0.0.0 --port $PORT"""
import os, asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
import telethon, config, tgclients as T, api, worker
from db import q

@asynccontextmanager
async def lifespan(app):
    T.log("PostBot ishga tushmoqda… telethon", telethon.__version__)
    await worker.start_bot()          # bot ishlamasa ham ilova ishlayveradi
    await worker.restore()
    tasks = [asyncio.create_task(worker.scheduler()), asyncio.create_task(worker.watchdog())]
    T.log("tayyor. WEBAPP_URL:", config.WEBAPP_URL or "(yo'q)")
    yield
    for t in tasks: t.cancel()
    for c in list(T.CL.values()):
        try: await c.disconnect()
        except Exception: pass

app = FastAPI(lifespan=lifespan)
app.include_router(api.router)

@app.exception_handler(Exception)
async def on_err(request, exc):
    T.log("500:", type(exc).__name__, exc)
    return JSONResponse({"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)

async def on_dead(request, exc): return JSONResponse({"detail": "login"}, status_code=401)
for _E in T.DEAD: app.add_exception_handler(_E, on_dead)

@app.get("/")
def index(): return FileResponse(os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html"), headers={"Cache-Control": "no-store"})

@app.get("/health")
def health():  # ochiq tekshiruv (maxfiy ma'lumotsiz)
    return {"ok": True, "v": config.VERSION, "telethon": telethon.__version__, "bot": worker.BOT_OK, "bot_err": worker.BOT_ERR,
            "webapp": bool(config.WEBAPP_URL), "users": q("select count(*) n from users where session!=''")[0]["n"]}
