"""Sozlamalar: .env fayli yoki Railway Variables."""
import os
if os.path.exists(".env"):
    for _l in open(".env", encoding="utf-8"):
        _l = _l.strip()
        if _l and not _l.startswith("#") and "=" in _l:
            _k, _v = _l.split("=", 1); os.environ.setdefault(_k.strip(), _v.strip().strip('"'))

def need(name):
    v = os.environ.get(name, "").strip()
    if not v or v.startswith("SHU_YERGA"):
        raise SystemExit(f"XATO: {name} o'zgaruvchisi kiritilmagan (Railway > Variables yoki .env)")
    return v

API_ID = int(need("API_ID")); API_HASH = need("API_HASH"); BOT_TOKEN = need("BOT_TOKEN")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "").strip()
if WEBAPP_URL.startswith("SHU_YERGA"): WEBAPP_URL = ""
VERSION = "2.0"
BOT_USERNAME = ""  # worker ishga tushganda to'ldiradi
MIN_INTERVAL = int(os.environ.get("MIN_INTERVAL", "5"))
MAX_JOBS = int(os.environ.get("MAX_JOBS", "10"))
MAX_CHATS = int(os.environ.get("MAX_CHATS", "50"))
DATA = os.environ.get("DATA_DIR", "."); os.makedirs(DATA, exist_ok=True)
