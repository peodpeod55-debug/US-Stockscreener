# Telegram Earnings Screener Bot — Design Spec

วันที่: 2026-08-20 · สถานะ: อนุมัติแล้ว (user approved in chat)

## เป้าหมาย

Bot Telegram คัดกรองหุ้น US ที่ "อาการหลังงบดี" จาก universe หุ้นที่มี DR ไทย ∪ S&P 500
ทำงาน 2 โหมดในโปรเซสเดียว:

1. **Push อัตโนมัติ** ทุกวันอังคาร–เสาร์ 08:30 น. เวลาไทย (หลังตลาด US ปิด)
2. **โต้ตอบ**: `/scan [days]` สแกนทันที, `/help`

## Universe

โหลดจาก `us_stock_list.csv` (โปรเจคนี้) — เงื่อนไข: `dr == "Y"` **หรือ** `index` มีคำว่า `SP500`
→ ปัจจุบัน 529 ตัว (DR 117 + SP500 498, ทับซ้อน 86)
Metadata ที่ใช้จาก CSV: `name`, `sector`, `dr_symbols` (ไม่ต้องเรียก FMP profile → ประหยัด API)

## เกณฑ์คัดกรอง — 5-Factor Score (reuse จาก earnings-trade-analyzer)

Vendor โมดูลจาก `~/.claude/skills/earnings-trade-analyzer/scripts/` เข้ามาใน
`bot/vendor/eta/` (คัดลอก ไม่ import ข้าม path เพื่อให้โปรเจค self-contained):

- `calculators/` ทั้ง 5 ตัว (gap, pre-earnings trend, volume, MA200, MA50)
- `scorer.py` (composite + เกรด A/B/C/D)
- `fmp_client.py` (FMP API + budget guard)
- `scripts/tests/` unit tests เดิม

น้ำหนัก: Gap 25% · Pre-Earnings Trend 30% · Volume 20% · MA200 15% · MA50 10%
**แจ้งเตือนเฉพาะเกรด A (≥85) และ B (70–84)** ท้ายข้อความสรุปจำนวน C/D ที่ตกเกณฑ์

## Flow การสแกน (ฟังก์ชันเดียว ใช้ทั้ง push และ /scan)

1. โหลด universe จาก CSV
2. FMP earnings calendar ย้อนหลัง N วัน (default 2) → กรอง symbol ∩ universe
3. ดึงราคา daily 250 วัน ต่อ candidate (1 call/ตัว, budget cap 200 calls)
4. ให้คะแนน 5-factor + คำนวณ Levels (ด้านล่าง)
5. จัดข้อความ → ส่ง Telegram (แบ่งข้อความถ้าเกิน 4096 ตัวอักษร)
6. บันทึกรายงาน JSON + Markdown ลง `reports/`
7. ไม่มีตัวเข้าเกณฑ์ → ส่งข้อความสั้น "วันนี้ไม่มีหุ้นใน universe ออกงบ/เข้าเกณฑ์"

## Levels (สืบทอด format จาก SET Earnings Breakout Screener เดิม)

นิยาม **reaction day (D0)** ตาม convention ของ gap calculator:
BMO → วันประกาศงบ · AMC/unknown → วันซื้อขายถัดไป

คำนวณจาก daily prices 250 วันที่ดึงมาแล้ว (ไม่มี API call เพิ่ม):

| ฟิลด์ | นิยาม |
|---|---|
| ราคา | close ล่าสุด |
| High 5 วันก่อนงบ | max High ของ 5 วันซื้อขายก่อน D0 |
| High 3 เดือนก่อนงบ | max High ของ 63 วันซื้อขายก่อน D0 |
| High สัปดาห์ก่อน | max High ของสัปดาห์ (จ–ศ) ที่จบล่าสุดก่อนวันสแกน |
| ความถี่ทำไฮใหม่ | จำนวนวันใน 10 วันซื้อขายล่าสุดที่ close > max High ของ 63 วันก่อนหน้าวันนั้น (new 3M high) |
| SL | low ของ D0 พร้อม % ห่างจากราคาปัจจุบัน |

แต่ละ level แสดง ✅ ทะลุ (+x%) หรือ ⬆️ ห่างอีก x%

## Format ข้อความต่อหุ้น

```
🔵 AAPL — Apple Inc.   [เกรด A · 88/100]
💰 ราคา: 316.83  (gap +4.2%)
📈 High 5 วันก่อนงบ: 310.20  ✅ ทะลุ (+2.1%)
🏔️ High 3 เดือนก่อนงบ: 325.00  ⬆️ ห่างอีก 2.6%
🗓️ High สัปดาห์ก่อน: ✅ ทะลุแล้ว
🔁 ทำไฮใหม่ 3M: 4 ครั้งใน 10 วันล่าสุด
🛑 SL (low วันงบ): 302.50  (-4.5%)
📊 Volume: 1.8x avg 20d
🇹🇭 DR: AAPL01 AAPL03 AAPL19 AAPL80
```

หุ้นที่ไม่มี DR → ไม่แสดงบรรทัด DR · เกรด A ใช้ 🔵, B ใช้ 🟡

## สถาปัตยกรรม

```
US Stock Screener/
├── us_stock_list.csv        universe (มีอยู่แล้ว)
├── us_dr_sp500.csv          (อ้างอิง ไม่ได้ใช้ใน bot)
├── bot/
│   ├── main.py              entry: PTB Application + JobQueue (push อ–ส 08:30 Asia/Bangkok)
│   ├── screener.py          orchestration: universe → calendar → score → levels
│   ├── levels.py            คำนวณ Levels ตามตารางด้านบน
│   ├── formatter.py         ข้อความ Telegram ภาษาไทย
│   ├── config.py            อ่าน .env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, FMP_API_KEY
│   └── vendor/eta/          โมดูลที่ vendor มา (ดูข้างบน)
├── reports/                 ผลสแกน (gitignored)
├── tests/                   unit tests: universe filter, levels, formatter
├── .env                     secrets (gitignored)
├── .env.example
├── requirements.txt         python-telegram-bot[job-queue], requests, python-dotenv, pytest
├── run_bot.bat              สำหรับ Task Scheduler
└── README.md                วิธีติดตั้ง + สร้าง bot ผ่าน @BotFather
```

- **Stack หลัก**: python-telegram-bot v22+ (long polling + JobQueue)
  **Fallback**: ถ้าติดตั้งบน Python 3.14 ไม่ได้ → polling loop ด้วย `requests` ล้วน (โครงสร้างอื่นคงเดิม)
- **Auth**: ตอบเฉพาะ chat_id ที่ตั้งใน config เท่านั้น
- **Deployment**: Task Scheduler รัน `run_bot.bat` ตอน logon (bot มี JobQueue จัดตารางเอง)

## Error handling

- Job/command ห่อ try/except → ส่งข้อความ error เข้า Telegram + log ลง `bot.log`
- FMP budget guard 200 calls/รอบ (ของเดิมใน fmp_client)
- Retry ส่ง Telegram 1 ครั้งเมื่อ timeout

## การทดสอบ

1. Unit tests: vendored calculator tests เดิม + tests ใหม่ (universe filter, levels, formatter)
2. Integration: รัน scan จริงย้อนหลัง 7 วันด้วย FMP_API_KEY (มีใน session) เทียบผลด้วยตา
3. Telegram: ทดสอบหลัง user ใส่ token (ส่งข้อความทดสอบ + /scan จริง)

## สิ่งที่ user ต้องทำ

1. @BotFather → `/newbot` → เอา token ใส่ `.env`
2. ทักหา bot 1 ข้อความ → รัน `python -m bot.get_chat_id` (จะมีให้) → ได้ chat_id ใส่ `.env`
3. (ทางเลือก) ตั้ง FMP_API_KEY ถาวรใน user env
