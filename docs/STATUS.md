# สถานะโปรเจค — US Earnings Screener Bot

> อัปเดตล่าสุด: 2026-08-21 (รอบสิบเอ็ด: atomic write ไฟล์ state ทุกตัว)

## โปรเจคนี้คืออะไร

Telegram bot (`@Sakuro_usbot`) คัดกรองหุ้น US "อาการหลังงบดี" จาก universe
**หุ้นมี DR ไทย ∪ S&P 500 = 566 ตัว** (จาก `us_stock_list.csv`: `dr=Y` หรือ index มี SP500 — ตรวจทาน DR กับ SET ล่าสุด 2026-08-20: dr=Y 168 ตัว / 297 DR)
ให้คะแนน 5-factor (Gap 25% / Pre-Earnings Trend 30% / Volume 20% / MA200 15% / MA50 10%)
แจ้งเฉพาะเกรด A (≥85) / B (70–84) พร้อม levels แบบ SET Earnings Breakout Screener เดิม
(High 5 วันก่อนงบ, High 3 เดือน, High สัปดาห์ก่อน, ความถี่ new 3M high ใน 10 วัน, SL = low วันงบ, Volume ratio, สัญลักษณ์ DR)

## ✅ เสร็จแล้วทั้งหมด (2026-08-20)

| งาน | สถานะ |
|---|---|
| Spec + implementation plan | `docs/superpowers/specs/` และ `docs/superpowers/plans/` |
| โค้ด bot ครบทุกโมดูล | `bot/` — main, screener, levels, formatter, config, get_chat_id |
| Vendor 5-factor scoring | `bot/vendor/eta/` (คัดลอกจาก earnings-trade-analyzer skill) |
| Tests | 84 ตัว ผ่านหมด (`python -m pytest -q`) |
| Telegram ทดสอบจริง | token + chat_id (808446026) ใช้ได้, user สั่ง `/scan 7` จากมือถือสำเร็จครบวงจร |
| รันถาวร | Startup shortcut → `start_bot_hidden.vbs` → `run_bot.bat` (restart loop 60s) — bot รัน detached อยู่ |
| GitHub | https://github.com/peodpeod55-debug/US-Stockscreener branch `feature/telegram-earnings-bot` push ครบ |
| Lookup รายตัว (20 ส.ค. เย็น) | พิมพ์ ticker หาบอท (สูงสุด 5 ตัว/ข้อความ) → snapshot ราคา EOD, %เปลี่ยน, วอลุ่ม, วันงบล่าสุด/ถัดไป, สัญญาณหลังงบ+เกรด, H/L 5วัน/3ด./52w, DR — `bot/lookup.py` + `format_lookup` + `get_earnings_dates` (2 API calls/ตัว) |
| Watchlist + เตือนวันงบ (20 ส.ค. ค่ำ) | พิมพ์ `ติดตาม NVDA` / `เลิกติดตาม NVDA` / `ติดตาม` (ดูรายชื่อ, สูงสุด 20 ตัว, เก็บใน `watchlist.json` — gitignored) · job ทุกวัน 08:25 เช็คหุ้นที่ติดตามตัวไหนงบวันนี้/พรุ่งนี้แล้วเตือนพร้อม BMO/AMC (1 API call/ตัว/วัน) — `bot/watchlist.py` + `bot/reminders.py` + `format_reminders` |
| เตือนทะลุแนว + auto-watch (20 ส.ค. ดึก) | job 08:20 อังคาร–เสาร์: หุ้นที่ติดตาม (manual+auto) ตัวไหน "เพิ่งทะลุ" High 5วัน/3ด.ก่อนงบ (ปิดข้ามแนวแต่เมื่อวานยังไม่ข้าม — กันเตือนซ้ำ) → แจ้งพร้อมวอลุ่ม/DR — `detect_new_breaks` ใน levels.py + `new_breaks` ใน snapshot + `format_breakouts` · หุ้นเกรด A/B จากสแกนเข้า watchlist เองอัตโนมัติ 30 วัน (`auto_watch.json` — gitignored, เพดาน 20 ตัวเก่าสุดหลุด, `เลิกติดตาม` เอาออกได้) |
| สรุปผลรายสัปดาห์ (20 ส.ค. ดึก) | job อาทิตย์ 09:00 + พิมพ์ `สรุป` ได้ทุกเมื่อ: หุ้น A/B ที่แจ้งใน 30 วัน (อ่านจาก `reports/scan_*.json`, dedup ต่อ symbol+รอบงบ นับครั้งแรกที่แจ้ง) → +/-% ตั้งแต่วันแจ้ง, จำนวนวัน, 🛑 ถ้า low เคยหลุด SL, สรุปเฉลี่ย+อัตราบวก — `bot/weekly.py` + `format_weekly` (1 API call/ตัว, yahoo fallback สำหรับหุ้น 402) |
| ยืนยันเปิดตลาด US (20 ส.ค. ดึก) | job ยิง 21:00+22:00 ไทย แล้ว `in_open_window` เลือกรอบที่ห่างระฆังเปิด (09:30 America/New_York — DST อัตโนมัติ) 20–80 นาที: quote สดหุ้นที่ติดตาม → ราคา, %วันนี้, gap เปิด, เหนือ/ใต้ราคาเปิด — `bot/openbell.py` + `get_quote` (stable/quote) ใน vendored client + `format_open_report` (yahoo quote fallback สำหรับ 402) |
| เตือนหลุด SL (20 ส.ค. รอบสอง) | ใน `breakout_job` เดิม (ศูนย์ API เพิ่ม): หุ้นที่ติดตามตัวไหน low ล่าสุดหลุด SL (low วันงบ) แต่วันก่อนยังไม่หลุด (self-dedup แบบเดียวกับทะลุแนว) → แจ้ง 🛑 พร้อมราคาปิด/low/ระดับ SL — `detect_sl_break` ใน levels.py + field `sl_break`,`low` ใน snapshot + `format_sl_breaks` |
| Catch-up job ที่พลาด (20 ส.ค. รอบสอง) | เครื่องปิด/หลับช่วงเช้า → เปิดเครื่องแล้วบอทรันรอบที่พลาดชดเชยเอง: `bot/jobstate.py` — state file `job_state.json` (gitignored) แต่ละ job `claim` วันของตัวเองก่อนทำงาน (restart กี่รอบก็ไม่ส่งซ้ำ) + `due_catchup(now)` เลือก job ที่เวลาผ่านแล้ววันนี้ + `catchup_job` ยิง `run_once` 15 วิหลัง start (openbell ไม่ catch-up — ผูกช่วงเปิดตลาด) · `/scan` และ `สรุป` manual ไม่ claim |
| GitHub Actions CI (20 ส.ค. รอบสอง) | `.github/workflows/ci.yml` — รัน `pytest -q` บน Python 3.12 ทุก push/PR เข้า master |
| Price cache ข้าม job (20 ส.ค. รอบสาม) | `bot/fetch_cache.py` — in-memory TTL 60 นาที คีย์ `("prices", sym, 250)` / `("earnings", sym)` ใช้ร่วมกันใน lookup/breakout/scan/reminder/weekly → job เช้า 08:20/08:25/08:30 (และ catch-up) ดึงหุ้นชุดที่ทับซ้อนกันแค่รอบเดียว ตัดงบ API เกินครึ่ง · ค่าว่างไม่ cache (fetch ล้มลองใหม่ได้), list คืนสำเนากัน mutate, `tests/conftest.py` ล้าง cache ทุก test |
| signals.json (20 ส.ค. รอบสาม) | `bot/signals.py` — บันทึกถาวรของสัญญาณ A/B ที่แจ้ง (dedup `(symbol, earnings_date)` ครั้งแรกที่แจ้งชนะ) เขียนจากทุกสแกน (manual + อัตโนมัติ) **track ใน git เป็น backup** (ไม่ gitignore) · weekly อ่านจาก `signals_since(30)` แทนการ glob `reports/scan_*.json` (ลบ `collect_signals` แล้ว — reports/ เหลือเป็น artifact อย่างเดียว) · เป็นฐานของฟีเจอร์สถิติผลงานระยะยาวต่อไป |
| กราฟแนบแจ้งเตือน (20 ส.ค. รอบสี่) | `bot/chart.py` — `build_chart_png` (mplfinance, dep ใหม่ดึง matplotlib+pandas): แท่งเทียน 120 แท่ง (~6 เดือน) + volume + เส้นแนว high_5d เขียว / high_3m น้ำเงิน / SL แดง + เส้นประวันตอบรับงบ · แนบใน: ผลสแกน A/B, เตือนทะลุแนว/หลุด SL, lookup รายตัว (เพดาน `CHART_MAX=6` รูป/รอบ) — ราคาเอาจาก fetch_cache ที่เพิ่งดึงตอนสร้างข้อความ (**0 API call เพิ่ม**), `_send_chart` พังเงียบไม่ล้มข้อความหลัก · ตัวหนังสือบนภาพอังกฤษล้วน (ฟอนต์ default matplotlib ไม่มี glyph ไทย — caption เป็นไทยแทน) |
| สถิติผลงานสะสม (20 ส.ค. รอบห้า) | พิมพ์ `สถิติ` / `สถิติสะสม` / `stats` — `bot/stats.py`: ประเมินทุกสัญญาณใน signals.json → drift เฉลี่ย +5/+20/+60 วันทำการ, win rate ต่อ horizon, อัตราเคยหลุด SL แยกเกรด A/B + รวม (`format_stats`) · นิยาม post-bars = `date > flag_date` ตรงกับ sl_hit ของ weekly (ตัวเลขสองรายงานไม่ขัดกัน) · สัญญาณที่ราคา 250 วันย้อนไม่ถึงวันแจ้ง (เก่ากว่า ~9 เดือน) ข้าม โชว์เป็น "ทั้งหมด X · ประเมินได้ Y" · ราคาใช้ fetcher เดิม (cache→FMP→yahoo) |
| เชื่อม gem-lab (21 ส.ค. รอบแปด) | ฝั่งบอท: `bot/breakouts.py` — `breakouts.json` (track ใน git แบบ signals.json) บันทึกเหตุการณ์ทะลุแนวจาก breakout_job dedup (symbol, วันแท่ง) ครั้งแรกชนะ, ไม่เก็บ SL/Low break (ขาออก) · ฝั่ง gem-lab (`Desktop\gem-lab`, commit ceea86e — backup ที่ https://github.com/peodpeod55-debug/gem-lab private, branch `feat/gem-batch`, มี CI `npm test` Node 22 รันผ่านแล้ว): config `usBotPath` → `lib/us_signals.mjs` อ่าน signals.json (A/B กรอบ 30 วัน) + breakouts.json (กรอบ 7 วัน) เป็น source `[us]` คิว my → us → scan TH, ป้าย `A·break↑5d/3m` เดินทาง gem_list → prompts.json → ช่อง TG รายงาน, ตัดเพราะเก่ารายงานเสมอ · gem-lab tests 191 |
| Watchlist levels + หลุด Low ก่อนงบ (21 ส.ค. รอบเจ็ด) | พิมพ์ `ติดตาม` ได้ตาราง levels รายตัว (ราคา/%, H5d/H3m ทะลุหรือยัง+ระยะ, SL, Low 5 วันก่อนงบ, ⏳/⚠️ ตามสถานะ, cache เช้าช่วยให้แทบไม่กิน API — `format_watch_detail`) · ระดับใหม่ `low_5d` (min low 5 วันก่อน D0) ใน `compute_levels` + `detect_low_break` (edge, self-dedup แบบ SL) + `below_low_5d` (state, เทียบ close) ใน levels.py · breakout_job แจ้ง ⛔ หลุด Low ก่อนงบ (= คายการตอบรับงบทั้งก้อน setup จบ) และ**เอาหุ้น auto-watch ที่ปิดใต้แนวนี้ออกอัตโนมัติ** (state-based เก็บตัวหลุดค้างด้วย, manual ไม่แตะ, แจ้ง 🗑 เสมอไม่หายเงียบ) · เส้น low_5d สีส้มบนกราฟ · tests 280 |
| DR premium/discount (20 ส.ค. รอบหก) | พิมพ์ `dr NVDA` / `ดีอาร์ NVDA` — `bot/dr.py`: ราคา DR จาก Yahoo `<DR>.BK` + `USDTHB=X` (พิสูจน์แล้วว่ามีครบ currency THB/exch SET, ฟรีไม่กินงบ FMP; `fetch_yahoo_prices` เพิ่มพารามิเตอร์ `raw=True` กันแปลงจุด) · ไม่ต้องรู้ ratio ทางการ: **implied ratio** k = DR/(หุ้นแม่×FX) จับคู่ DR วันไทย D ↔ US close ล่าสุด date<D ↔ FX date≤D แล้ววัด premium เทียบ median ย้อน 60 คู่ (ขั้นต่ำ 10 คู่ ไม่พอ = "ข้อมูลไม่พอ") — ตอบว่า "แพง/ถูกกว่าปกติของตัวเอง" (baseline ดูดซับ premium ถาวร) · เกณฑ์ป้าย ±1.5% · รายงานทุก DR ของหุ้น (เพดาน 6 เกินแจ้ง "ไม่แสดงอีก N") · ทดสอบจริง NVDA 6 DR ส่งเข้า Telegram แล้ว premium ±0.7% |
| Hardening (21 ส.ค. รอบเก้า) | จากรีวิวโค้ดทั้งโปรเจค แก้ 3 จุด: (1) **edited message crash** — ข้อความ/คำสั่งที่ถูก "แก้ไข" ใน Telegram ผ่าน `filters.TEXT`/`CommandHandler` ได้แต่ `update.message` เป็น `None` → AttributeError เงียบ ผู้ใช้ไม่ได้คำตอบ — เพิ่ม `filters.UpdateType.MESSAGE` ทุก handler (บอทไม่ตอบข้อความที่ edit — ต้องส่งใหม่) + แยก `build_app(config)` ออกจาก `main()` ให้เทสตรวจ wiring ได้ และย้าย `load_config`/logging ออกจาก import time (import `bot.main` ได้โดยไม่มี `.env` — CI ต้องการ) (2) **error handler + กันรันซ้อน** — `on_error` แยกชนิด: Conflict = แจ้ง instance ซ้อน, NetworkError = warning บรรทัดเดียว, อื่นๆ = traceback เต็ม (เดิม log เป็น "No error handlers are registered" 65 ครั้งจากเหตุรันซ้อน 20 ส.ค.) + `bot/instance_lock.py` จอง port 48962 บน localhost — instance ที่สอง exit ทันทีก่อนแตะ Telegram (socket ดีกว่า lockfile: process ตาย OS คืน port เอง) (3) **log rotation** — `RotatingFileHandler` 5MB × 3 + ปิด apscheduler INFO (เสียงรบกวนหลัก ~190KB/วัน) · tests 296 |
| Job retry (21 ส.ค. รอบสิบ) | เดิม job เช้า `claim` ก่อนทำงานแล้วไม่คืนเมื่อล้ม — เน็ตสะดุดตอน 08:20–08:30 = job หายทั้งวัน (catch-up เห็น already_ran แล้วข้าม) และ breakout/reminder/weekly ล้มเงียบไม่แจ้งใคร → (1) `jobstate.release()` คืน claim เฉพาะของวันนี้ (2) wrapper `_run_claimed` ใช้ร่วมทั้ง 4 job: ล้ม → คืน claim + แจ้งผู้ใช้ "จะลองใหม่ใน ~30 นาที (ครั้งที่ n/3)" · ครบ `JOB_MAX_TRIES=3` ครั้ง/วัน → เก็บ claim เลิกลอง (กันสแปม/เผางบ API) · ตัวนับล้มอยู่ใน memory — restart แล้วนับใหม่ (3) catch-up เปลี่ยน run_once → **run_repeating ทุก 30 นาที** (`CATCHUP_INTERVAL`) เป็นกลไก retry + เก็บกรณีเครื่องหลับกลางวันตื่นมา job เช้ายังไม่รัน · trade-off ที่ยอมรับ: retry อาจส่งข้อความที่ออกไปแล้วซ้ำถ้าล้มกลางคัน (ดีกว่าพลาดเตือน SL ทั้งวัน) · process crash จริง claim ค้างเหมือนเดิม (แยกไม่ได้ว่าส่งไปแค่ไหน) · openbell ไม่เข้าระบบนี้ (ผูกช่วงเปิดตลาด) · tests 305 |
| Atomic write (21 ส.ค. รอบสิบเอ็ด) | `bot/fileio.py` — `write_json_atomic`: เขียนลง `.tmp` ข้างๆ → fsync → `os.replace` ทับ (atomic ทั้ง Windows/POSIX) — ไฟดับ/crash กลางคันไฟล์เดิมอยู่ครบ ไฟล์ใหม่ไม่มีทางว่าง/ครึ่งเดียว · ใช้กับ writer ทุกตัวของ state: signals.json + breakouts.json (ประวัติถาวร track ใน git), watchlist.json, auto_watch.json, job_state.json (claim/release) · reports/scan_* ไม่แตะ (ไฟล์ใหม่ timestamped ไม่มี overwrite risk) · `.tmp` เข้า .gitignore · เทสจำลอง crash (os.replace พัง) ยืนยัน writer ทุกตัว raise โดยไฟล์เดิมไม่ถูกแตะ · tests 313 |
## 🔧 บั๊กที่เจอและแก้แล้วระหว่างทาง

1. **FMP ปิด endpoint เก่า** — `historical-price-full` โดน 403 Legacy สำหรับ key ใหม่
   → เพิ่ม `stable/historical-price-eod/full` ใน vendored `fmp_client.py` (commit `cfa10ee`)
   ⚠️ **skill ต้นฉบับใน `~/.claude/skills/earnings-trade-analyzer` และ `pead-screener` ยังพังอยู่ ยังไม่ได้ patch**
2. **UTF-8 BOM ในไฟล์ `.env`** ทำ key แรกอ่านไม่เจอ → ใช้ `encoding="utf-8-sig"` + test (commit `d3792ba`)
3. **httpx log URL ที่มี bot token ลง bot.log** → ปิด log level + ล้าง log เก่า (commit `d3792ba`)
4. **Register-ScheduledTask ต้องใช้ admin บนเครื่องนี้** → เปลี่ยนเป็น Startup-folder shortcut (commit `c9a924b`)
5. หุ้นที่งบเพิ่งออก (ยังไม่มีวันตอบรับ) แสดงเป็น "⏳ รอวันตอบรับงบ" ไม่หายเงียบ (commit `9c5bad8`)
6. **แผนฟรี FMP จำกัดรายชื่อหุ้น (HTTP 402)** — เจอตอนทำ lookup: HD โดนบล็อก, NVDA/WMT/TGT ใช้ได้
   และ ticker ที่ไม่มีจริงก็ได้ 402 เหมือนกัน (แยกไม่ได้) → client มีธง `saw_402`, lookup raise
   `SymbolNotCovered` แจ้งผู้ใช้ตรงๆ ⚠️ scan อาจข้ามหุ้น universe บางตัวเงียบๆ ด้วยเหตุเดียวกัน
   (ขึ้นเป็น pending "no_data")

## ⏳ ค้างอยู่ / งานต่อ session หน้า

1. ~~เปิด PR~~ ✅ PR #1 merge แล้ว (20 ส.ค.) — **ต่อจากนี้ทำงานบน `master` ตรงๆ ไม่ใช้ feature branch**
   (branch `feature/telegram-earnings-bot` ลบในเครื่องแล้ว เหลือบน GitHub ลบได้จากหน้า PR)
2. ~~เช็คผล push อัตโนมัติรอบแรก~~ ✅ ศุกร์ 21 ส.ค.: เครื่องเปิด 09:05 → catch-up ยิง breakout/reminder/scan ชดเชยครบ
   ผลสแกน: ไม่มี A/B (C=3, D=4) · **WMT/BABA/ROST งบ 20 ส.ค. AMC → รอวันตอบรับ ได้เกรดเสาร์ 22 ส.ค. 08:30**
3. (เสนอ) **patch fmp_client ต้นฉบับ** ใน earnings-trade-analyzer + pead-screener skills ให้ใช้ endpoint ใหม่ (ตามข้อ 1 ด้านบน)
4. (ไอเดีย) ต่อยอด: ติดตาม drift รายสัปดาห์ด้วย logic pead-screener หลังหุ้นติดเกรด A/B
5. ~~DR premium/discount~~ ✅ เสร็จแล้ว (รอบหก) — ไอเดียต่อยอด: แนบ premium ใน lookup อัตโนมัติเมื่อหุ้นมี DR, เตือนเมื่อ DR ที่ติดตาม discount เกินเกณฑ์

## วิธีใช้งาน / ดูแล

- สั่งใน Telegram: `/scan`, `/scan 7`, `/help` (bot ตอบเฉพาะ chat_id ใน `.env`)
- Log: `bot.log` · ผลสแกน: `reports/scan_*.json|md`
- หยุด bot: ดูหัวข้อ "ตั้งรันอัตโนมัติ" ใน `README.md` (ระวัง restart loop + อย่ารัน 2 instance ซ้อน)
- ทดสอบ: `python -m pytest -q`

## การตัดสินใจสำคัญ (จะได้ไม่ต้องเถียงใหม่)

- Reaction day (D0): BMO → วันงบ, AMC/unknown → วันซื้อขายถัดไป (ตาม gap_size_calculator เดิม)
- "ความถี่ทำไฮใหม่" = จำนวนวันใน 10 วันล่าสุดที่ close > max High ของ 63 วันก่อนหน้าวันนั้น
- Push อังคาร–เสาร์ 08:30 Asia/Bangkok (เช็ค weekday ใน callback เอง ไม่พึ่ง days param ของ JobQueue)
- Vendor โค้ด scoring แทน import ข้าม path → โปรเจค self-contained
