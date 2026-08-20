"""หา chat_id: ทักหา bot ก่อน 1 ข้อความ แล้วรัน python -m bot.get_chat_id"""
import os

import requests
from dotenv import load_dotenv

from bot.config import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")
token = os.environ.get("TELEGRAM_BOT_TOKEN")
if not token or token == "PENDING":
    raise SystemExit("ยังไม่ได้ใส่ TELEGRAM_BOT_TOKEN ใน .env")

resp = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10)
updates = resp.json().get("result", [])
if not updates:
    raise SystemExit("ไม่พบข้อความ — ทักหา bot ใน Telegram ก่อน 1 ข้อความแล้วรันใหม่")
for u in updates:
    chat = (u.get("message") or {}).get("chat", {})
    if chat:
        print(f"chat_id: {chat['id']}  ({chat.get('first_name', '')} @{chat.get('username', '')})")
