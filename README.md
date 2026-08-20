# US Earnings Screener Bot — Telegram

Bot คัดกรองหุ้น US "อาการหลังงบดี" จาก universe **หุ้นที่มี DR ไทย ∪ S&P 500** (~529 ตัว)
ให้คะแนนด้วยระบบ 5-factor (Gap 25% · Pre-Earnings Trend 30% · Volume 20% · MA200 15% · MA50 10%)
แจ้งเฉพาะเกรด **A (≥85)** และ **B (70–84)** พร้อมระดับราคาแบบ SET Earnings Breakout Screener เดิม:
High 5 วันก่อนงบ, High 3 เดือนก่อนงบ, High สัปดาห์ก่อน, ความถี่ทำไฮใหม่, SL = low วันงบ, Volume ratio และสัญลักษณ์ DR ไทย

- **Push อัตโนมัติ**: อังคาร–เสาร์ 08:30 น. (หลังตลาด US ปิด)
- **เตือนทะลุแนว + หลุด SL** (หุ้นที่ติดตาม): อังคาร–เสาร์ 08:20 น. · **เตือนวันงบ**: ทุกวัน 08:25 น.
- **Catch-up**: เปิดเครื่องหลังเวลา job เช้า → บอทรันรอบที่พลาดชดเชยให้เอง (กันซ้ำด้วย `job_state.json`)
- **สั่งเอง**: `/scan` (ย้อนหลัง 2 วัน), `/scan 7`, `/help`

## ติดตั้งครั้งแรก

```bash
pip install -r requirements.txt
```

## ตั้งค่า Telegram Bot

1. เปิด Telegram → หา **@BotFather** → พิมพ์ `/newbot` → ตั้งชื่อ → copy **TOKEN**
2. คัดลอก `.env.example` เป็น `.env` แล้วใส่ token:
   ```
   TELEGRAM_BOT_TOKEN=1234567890:AAF...
   ```
3. ทักหา bot ของคุณ 1 ข้อความ (สำคัญ) แล้วรัน:
   ```bash
   python -m bot.get_chat_id
   ```
4. เอา chat_id ที่ได้ใส่ `.env`:
   ```
   TELEGRAM_CHAT_ID=987654321
   ```
5. ใส่ `FMP_API_KEY` (financialmodelingprep.com — free tier พอ)

## รัน

```bash
python -m bot.main
```

แล้วลองสั่ง `/scan 7` ใน Telegram — bot ตอบเฉพาะ chat_id ที่ตั้งไว้เท่านั้น

## ตั้งรันอัตโนมัติตอนเปิดเครื่อง

**วิธีที่ใช้อยู่ (ไม่ต้องใช้สิทธิ์ admin):** shortcut ใน Startup folder ชี้ไปที่ `start_bot_hidden.vbs`
ซึ่งรัน `run_bot.bat` แบบไม่มีหน้าต่าง และ bat มี loop restart เองถ้า bot crash
ติดตั้งด้วย:

```powershell
$startup = [Environment]::GetFolderPath('Startup')
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut("$startup\USEarningsScreenerBot.lnk")
$lnk.TargetPath = "wscript.exe"
$lnk.Arguments = '"' + "$PWD\start_bot_hidden.vbs" + '"'
$lnk.Save()
```

**ทางเลือก (ต้องรัน PowerShell แบบ Run as Administrator):** `.\setup_task.ps1` ใช้ Task Scheduler แทน

หยุด bot ชั่วคราว: `Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*bot.main*' } | ForEach-Object { Stop-Process -Id $_.ProcessId }` (ระวัง run_bot.bat จะ restart ใน 60 วิ — ปิดหน้าต่าง cmd ของมันด้วยหรือลบ shortcut ออกจาก Startup)

## โครงสร้าง

```
bot/
├── main.py          entry: handlers + daily job
├── screener.py      universe → earnings calendar → score → levels
├── levels.py        ระดับราคา (5d/3M/week high, new-high freq, SL)
├── formatter.py     ข้อความ Telegram ภาษาไทย
├── config.py        อ่าน .env
├── get_chat_id.py   helper หา chat_id
└── vendor/eta/      โมดูล scoring (vendored จาก earnings-trade-analyzer skill)
us_stock_list.csv    universe (dr=Y หรือ index มี SP500)
reports/             ผลสแกนรายครั้ง (JSON + MD)
```

ปรับ config เพิ่มเติมผ่าน env: `SCAN_LOOKBACK_DAYS` (default 2), `MAX_API_CALLS` (default 200)

## ทดสอบ

```bash
python -m pytest -q
```

## หมายเหตุ

- ข้อมูลจาก FMP (EOD) — สแกนหลังตลาดปิด ไม่ใช่ realtime แบบ SET screener เดิม
- API ที่ใช้ต่อรอบ ≈ 1 (ปฏิทินงบ) + 1 ต่อหุ้นที่ออกงบใน universe → free tier 250 calls/วัน เพียงพอ
- Log อยู่ที่ `bot.log`
