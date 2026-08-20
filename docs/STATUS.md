# สถานะโปรเจค — US Earnings Screener Bot

> อัปเดตล่าสุด: 2026-08-20 (ทำเสร็จทั้งหมดใน session เดียว)

## โปรเจคนี้คืออะไร

Telegram bot (`@Sakuro_usbot`) คัดกรองหุ้น US "อาการหลังงบดี" จาก universe
**หุ้นมี DR ไทย ∪ S&P 500 = 529 ตัว** (จาก `us_stock_list.csv`: `dr=Y` หรือ index มี SP500)
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
2. **เช็คผล push อัตโนมัติรอบแรก** — พฤหัส 21 ส.ค. 08:30 น. จะได้เกรดของ **WMT + TGT** ที่เพิ่งออกงบ
3. (เสนอ) **patch fmp_client ต้นฉบับ** ใน earnings-trade-analyzer + pead-screener skills ให้ใช้ endpoint ใหม่ (ตามข้อ 1 ด้านบน)
4. (ไอเดีย) ต่อยอด: ติดตาม drift รายสัปดาห์ด้วย logic pead-screener หลังหุ้นติดเกรด A/B

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
