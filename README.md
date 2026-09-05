# US Earnings Screener Bot — Telegram

Bot คัดกรองหุ้น US "อาการหลังงบดี" จาก universe **หุ้นที่มี DR ไทย ∪ S&P 500** (~566 ตัว)
ให้คะแนนด้วยระบบ 5-factor (Gap 25% · Pre-Earnings Trend 30% · Volume 20% · MA200 15% · MA50 10%)
แจ้งเฉพาะเกรด **A (≥85)** และ **B (70–84)** **ที่วันตอบรับงบปิดบวก** (5-factor ให้คะแนน |gap| ไม่สนทิศทาง —
หุ้น gap ลงจึงถูกตัดก่อนให้เกรด นับแยกเป็น "ตอบรับลบ") พร้อมระดับราคาแบบ SET Earnings Breakout Screener เดิม:
High 5 วันก่อนงบ, High 3 เดือนก่อนงบ, High สัปดาห์ก่อน, ความถี่ทำไฮใหม่, SL = low วันงบ, Volume ratio และสัญลักษณ์ DR ไทย

- **Push อัตโนมัติ**: อังคาร–เสาร์ 08:30 น. (หลังตลาด US ปิด)
- **เตือนทะลุแนว + หลุด SL + หลุด Low 5 วันก่อนงบ** (หุ้นที่ติดตาม): อังคาร–เสาร์ 08:20 น. · **เตือนวันงบ**: ทุกวัน 08:25 น.
  — ปิดหลุด Low ก่อนงบ = setup จบ หุ้นติดตามอัตโนมัติถูกเอาออกเอง · พิมพ์ `ติดตาม` เห็นแนวรายตัว (H5d/H3m/SL/Low ก่อนงบ)
- **Catch-up**: เปิดเครื่องหลังเวลา job เช้า → บอทรันรอบที่พลาดชดเชยให้เอง (กันซ้ำด้วย `job_state.json`)
  · หุ้นที่ยังรอวันตอบรับ (เช่น งบ AMC วันศุกร์) จำไว้ใน `pending.json` แล้วเช็คต่อทุกรอบจนได้เกรด แม้หลุดหน้าต่างปฏิทิน 2 วันไปแล้ว
  · `last_alive.json` (heartbeat ทุก 5 นาที ให้ watchdog นอก process — ไม่ต้องสำรอง)
- **สั่งเอง** (เมนู `/` ใน Telegram ลงทะเบียนเองตอนบอท start): `/scan` (ย้อนหลัง 2 วัน), `/scan 7`, `/hot` (หุ้นที่ติดตามตัวไหนน่าสนใจตอนนี้ — ใกล้ H5d/H3m ≤3%, เพิ่งทะลุ, งบ ≤3 วัน, หลุด SL/Low ก่อนงบ), `/watch [ticker]`, `/unwatch <ticker>`, `/cal [0-7]`, `/scanlog [N]` (หรือ `สแกนล็อก`: สองเกณฑ์คู่กัน — 🇹🇭 SET ปิด D0 ≥2% & vol ≥1.5× คะแนน 0–15 ⭐ คิดสด + เดิม A/B), `/dr <ticker>`, `/plan <ticker>` (หรือ `แผน CRM` / ปุ่ม 📋 ใต้ lookup และกราฟผลสแกน: แผนเทรด 3 ทางเข้า ① เข้าตอนนี้ ② ทะลุ High วันงบ ③ ย่อถึง D0 Open · SL = D0 Low · เป้า 1R/2R/3R · แปลงเป็นราคาบาท + จำนวนหน่วยต่อ DR ผ่าน implied ratio), `/risk 1% ทุน 500000` (หรือ `เสี่ยง ...`: ตั้งทุน/%เสี่ยงต่อไม้ให้แผนคิดจำนวนหน่วย — เก็บใน `settings.json` gitignored · `/risk` เฉย ๆ = ดูค่า), `/summary`, `/stats`, `/status` (รันอยู่ไหม/โค้ดตรง HEAD ไหม, job วันนี้, รอตอบรับ, FMP 402, error, สแกนล่าสุด), `/help` — คำสั่งไทยเดิม (`ติดตาม`, `น่าสนใจ`, `งบ`, `dr`, `แผน`, `เสี่ยง`, `สรุป`, `สถิติ`, `สถานะ`) ใช้ได้เหมือนเดิม
- **พิมพ์ ticker** (เช่น `NVDA`, สูงสุด 5 ตัว): snapshot ราคา EOD + สัญญาณหลังงบ/เกรด + **🇹🇭 เกณฑ์ SET** คะแนน 0–15 ⭐ แบบบอทไทย (ไฮ 5 วัน/3 ด. ก่อนงบ ผ่านหรือยัง, ไฮใหม่ล่าสุด, ความถี่ไฮใหม่, ไฮรายสัปดาห์, Low ก่อนงบ — ตกด่านเข้า ≥2%/vol 1.5× ก็ยังโชว์คะแนน; สูตรเดียวกับ `/scanlog`/`scan_log.csv` และบอทไทย/HK) + กราฟ 6 เดือน + ปุ่ม ➕ ติดตาม / 📋 แผนเทรด
- **`scan_log.csv` ให้ gem-lab** (28 ส.ค. 2026 — port จาก HK Stock Screener): ทั้ง `/scanlog` และ job สแกน 08:30 เขียนไฟล์นี้ (root, gitignore ตั้งแต่ 31 ส.ค. 2026) ใน **schema เดียวกับ `scan_log.csv` ของ Set screnner** + คอลัมน์ `grade` ท้ายสุด (`scan_date,ticker,earn_date,reaction_pct,reaction_vol_ratio,since_earn_pct,price,broke_5d_high,broke_3m_high,days_since_new_high,pre_earn_low,above_pre_low,score,grade`) · `ticker` = `NVDA` ไม่มีนามสกุล (gem-lab ต้องรู้ตลาดจาก config ของไฟล์) · `score` = คะแนน SET 0–15 (`bot/set_score.py` port `signal_score` ของไทยตัวต่อตัว) คิดสด ณ วันเขียน · แถว = ตัวที่ผ่านด่าน SET หรือเข้าเกณฑ์เดิม A/B · หนึ่งแถวต่อ (scan_date, ticker) รอบหลังทับรอบก่อน · utf-8-sig เปิด Excel ได้ · ไฟล์ถูกล็อก → log เตือน ไม่ล้มสแกน · ไม่แตะ signals.json/auto-watch · `run_scan` คืน `rows` (ทุกตัวที่มีแท่ง D0 รวม down/C/D พร้อม `set_hit`/`set_pts`) ให้ทั้งสองทางใช้

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
5. ใส่ `FMP_API_KEY` (financialmodelingprep.com — free tier พอ: ใช้แค่ปฏิทินงบรวม ราคาใช้ Yahoo)
6. (ตัวเลือก) ใส่ `FINNHUB_API_KEY` (finnhub.io — สมัครฟรี) → เติมเวลางบ BMO/AMC ให้ปฏิทิน
   ลดเคส "ไม่ระบุ" ที่ต้องอนุมานจากแท่งราคา ไม่ใส่บอทก็ทำงานครบ
7. (ครั้งแรก) seed คลังวันงบย้อนหลัง: `python -m bot.earnings_store backfill 90` (NASDAQ ฟรี ไม่ต้อง key)

## รัน

```bash
python -m bot.main
```

แล้วลองสั่ง `/scan 7` ใน Telegram — bot ตอบเฉพาะ chat_id ที่ตั้งไว้เท่านั้น

## ตั้งรันอัตโนมัติตอนเปิดเครื่อง

**วิธีที่ใช้อยู่ (ไม่ต้องใช้สิทธิ์ admin):** shortcut ใน Startup folder ชี้ไปที่ `start_bot_hidden.vbs`
ซึ่งรัน `run_bot.bat` แบบไม่มีหน้าต่าง และ bat มี loop restart เองถ้า bot crash
(ถ้า bot จบเพราะมีอีก instance ถือ lock อยู่ — exit code 3 — launcher จะหยุดเอง ไม่วน restart ซ้ำ)
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

หยุด/restart bot — **หา PID จาก port ของ instance lock (48962) เท่านั้น** เพราะเครื่องนี้มีบอท HK Stock Screener รัน `python -m bot.main` คู่กัน (port 48972) filter `*bot.main*` จะฆ่าบอท HK ด้วย (เคยเกิด 25 ส.ค. 2026):

```powershell
$pid_ = (Get-NetTCPConnection -LocalPort 48962 -State Listen).OwningProcess
(Get-CimInstance Win32_Process -Filter "ProcessId=$pid_").CommandLine   # ต้องเป็น python -m bot.main (parent = run_bot.bat ของโปรเจคนี้)
Stop-Process -Id $pid_                                                  # run_bot.bat restart ให้ใน 60 วิ = โหลดโค้ดใหม่
```

หยุดจริง (ไม่ให้ฟื้น): ปิด cmd ที่เป็น parent ของ PID นั้นด้วย (`(Get-CimInstance Win32_Process -Filter "ProcessId=$pid_").ParentProcessId`) หรือลบ shortcut ออกจาก Startup · เช็คหลัง restart: port 48962 กลับมา + `bot.log` มี `bot starting` ไม่มี traceback · `/status` บอกว่าโค้ดตรง HEAD ไหม

## โครงสร้าง

```
bot/
├── main.py          entry: handlers + daily job
├── screener.py      universe → earnings calendar → score → levels
├── prices.py        ราคา EOD: cache → Yahoo (หลัก) → FMP (สำรอง) + prefetch ขนาน
├── earnings_store.py คลังวันงบสะสม earnings_calendar.json (NASDAQ/FMP/Finnhub) — อ่านก่อนยิง FMP รายตัว
├── levels.py        ระดับราคา (5d/3M/week high, new-high freq, SL)
├── dr.py            DR premium + implied ratio (DR/(US×USDTHB)) ใช้ร่วมกับ plan
├── plan.py          แผนเทรด 3 ทางเข้า + แปลงเป็นราคาบาท/จำนวนหน่วย DR (pure)
├── settings.py      ทุน/%เสี่ยงต่อไม้ → settings.json (gitignored)
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

- ข้อมูล EOD — สแกนหลังตลาดปิด ไม่ใช่ realtime แบบ SET screener เดิม
- **ราคา**: Yahoo (v8 chart, ไม่ต้อง key) เป็นหลักทุกตัว — FMP แผนฟรีตอบ 402 กับหุ้นเกือบทั้ง universe จึงเหลือเป็นสำรองตอน Yahoo ล้ม
- **วันงบ**: ปฏิทินรวม FMP (1 call) + NASDAQ (ฟรี) + Finnhub (ถ้ามี key) ทุกแถวลง `earnings_calendar.json` (gitignored)
  → เตือนวันงบ / `/hot` "งบใกล้" / lookup อ่านจากคลังก่อน ไม่ยิง FMP รายตัว (402) · job เช้าดึงล่วงหน้า 7 วัน, อาทิตย์ดึงถึง 35 วัน
- API FMP ต่อวัน ≈ 2–3 call (ปฏิทิน) → free tier 250 calls/วัน เหลือเฟือ
- `settings.json` (ทุน/%เสี่ยง), `watchlist.json`, `auto_watch.json` เป็นข้อมูลส่วนตัว gitignored — ย้ายเครื่องต้องตั้งใหม่ (`/risk`, `ติดตาม`)
- Log อยู่ที่ `bot.log`
