"""จัดข้อความ Telegram (plain text ภาษาไทย)"""
from bot.levels import below_low_5d
from bot.stats import HORIZONS

MAX_LEN = 3800

GRADE_ICON = {"A": "🔵", "B": "🟡"}


def _level_line(label, value, pct):
    if value is None:
        return f"{label}: n/a"
    if pct is None:
        return f"{label}: {value:,.2f}"
    if pct >= 0:
        return f"{label}: {value:,.2f}  ✅ ทะลุ (+{pct}%)"
    return f"{label}: {value:,.2f}  ⬆️ ห่างอีก {abs(pct)}%"


def _format_candidate(c):
    lv = c["levels"]
    icon = GRADE_ICON.get(c["grade"], "⚪")
    lines = [
        f"{icon} {c['symbol']} — {c['name']}   [เกรด {c['grade']} · {c['score']:.0f}/100]",
        f"💰 ราคา: {lv['price']:,.2f}  (gap {c['gap_pct']:+.1f}%)",
        "📈 " + _level_line("High 5 วันก่อนงบ", lv["high_5d"], lv["pct_vs_high_5d"]),
        "🏔️ " + _level_line("High 3 เดือนก่อนงบ", lv["high_3m"], lv["pct_vs_high_3m"]),
    ]
    if lv["broke_prev_week_high"] is not None:
        mark = "✅ ทะลุแล้ว" if lv["broke_prev_week_high"] else "❌ ยังไม่ทะลุ"
        lines.append(f"🗓️ High สัปดาห์ก่อน: {lv['prev_week_high']:,.2f}  {mark}")
    lines.append(f"🔁 ทำไฮใหม่ 3M: {lv['new_high_count_10d']} ครั้งใน 10 วันล่าสุด")
    if lv["sl"] is not None:
        lines.append(f"🛑 SL (low วันงบ): {lv['sl']:,.2f}  (-{lv['sl_pct']}%)")
    if lv["vol_ratio"] is not None:
        lines.append(f"📊 Volume วันงบ: {lv['vol_ratio']}x avg 20d")
    if c["dr_symbols"]:
        lines.append(f"🇹🇭 DR: {c['dr_symbols']}")
    lines.append(f"📅 งบ: {c['earnings_date']} ({c['timing'].upper()})")
    return "\n".join(lines)


def _signed(x):
    return "n/a" if x is None else f"{x:+.1f}%"


def _fmt_volume(v):
    if v is None:
        return "n/a"
    if v >= 1e9:
        return f"{v / 1e9:.1f}B"
    if v >= 1e6:
        return f"{v / 1e6:.1f}M"
    if v >= 1e3:
        return f"{v / 1e3:.1f}K"
    return f"{v:.0f}"


def format_lookup(s):
    """ข้อความ snapshot รายตัว (ผู้ใช้พิมพ์ ticker หาบอท) — plain text"""
    lines = [
        f"📊 {s['name']} ({s['symbol']})",
        f"🗓 ปิดล่าสุด {s['last_date']} (ข้อมูล EOD)",
        "",
        f"💰 ราคาปิด: {s['price']:,.2f}  ({_signed(s['day_change_pct'])} วันล่าสุด)",
        f"⚡ Gap เปิด {_signed(s['gap_pct'])} · ระหว่างวัน {_signed(s['intraday_pct'])}",
        f"📈 เปลี่ยน 5 วัน {_signed(s['chg_5d_pct'])} · 1 เดือน {_signed(s['chg_1m_pct'])}",
    ]
    if s["vol_ratio"] is not None:
        fire = " 🔥" if s["vol_ratio"] >= 2 else ""
        lines.append(f"📊 วอลุ่ม {_fmt_volume(s['volume'])} "
                     f"({s['vol_ratio']:.1f}x เฉลี่ย 20 วัน){fire}")
    else:
        lines.append(f"📊 วอลุ่ม {_fmt_volume(s['volume'])}")

    if s["last_earnings"] or s["next_earnings"]:
        lines.append("")
        if s["last_earnings"]:
            timing = (f" ({s['timing'].upper()})"
                      if s.get("timing") and s["timing"] != "unknown" else "")
            line = (f"🗓 งบล่าสุด: {s['last_earnings']}{timing} — "
                    f"{s['days_since_earnings']} วันก่อน")
            if s["since_earnings_pct"] is not None:
                line += f" → ตั้งแต่งบ {_signed(s['since_earnings_pct'])}"
            lines.append(line)
            if s["reaction_pct"] is not None:
                lines.append(f"   วันตอบรับงบ: {_signed(s['reaction_pct'])}")
        if s["next_earnings"]:
            lines.append(f"🗓 งบถัดไป: {s['next_earnings']} "
                         f"(อีก {s['days_to_earnings']} วัน)")

    if s.get("pending_reaction"):
        lines += ["", "⏳ รอวันตอบรับงบ (งบเพิ่งออก ยังไม่มีแท่งราคาตอบรับ)"]

    lv = s.get("levels")
    if lv:
        head = "📌 สัญญาณหลังงบ"
        if s.get("grade"):
            head += f"   [เกรด {s['grade']} · {s['score']:.0f}/100]"
        lines += [
            "", head,
            "📈 " + _level_line("High 5 วันก่อนงบ", lv["high_5d"], lv["pct_vs_high_5d"]),
            "🏔️ " + _level_line("High 3 เดือนก่อนงบ", lv["high_3m"], lv["pct_vs_high_3m"]),
        ]
        if lv["broke_prev_week_high"] is not None:
            mark = "✅ ทะลุแล้ว" if lv["broke_prev_week_high"] else "❌ ยังไม่ทะลุ"
            lines.append(f"🗓️ High สัปดาห์ก่อน: {lv['prev_week_high']:,.2f}  {mark}")
        lines.append(f"🔁 ทำไฮใหม่ 3M: {lv['new_high_count_10d']} ครั้งใน 10 วันล่าสุด")
        if lv["sl"] is not None:
            lines.append(f"🛑 SL (low วันงบ): {lv['sl']:,.2f}  (-{lv['sl_pct']}%)")

    lines += [
        "",
        f"📅 High/Low 5 วัน: {s['hi_5d']:,.2f} / {s['lo_5d']:,.2f}",
        f"📆 High/Low 3 เดือน: {s['hi_3m']:,.2f} / {s['lo_3m']:,.2f}",
    ]
    if s["hi_52w"] is not None and s["lo_52w"] is not None:
        hi_pct = _signed((s["price"] - s["hi_52w"]) / s["hi_52w"] * 100)
        lo_pct = _signed((s["price"] - s["lo_52w"]) / s["lo_52w"] * 100)
        lines.append(f"📈 52w High: {s['hi_52w']:,.2f} ({hi_pct}) · "
                     f"Low: {s['lo_52w']:,.2f} ({lo_pct})")
    if s["dr_symbols"]:
        lines.append(f"🇹🇭 DR: {s['dr_symbols']}")
    return "\n".join(lines)


_BREAK_TH = {"high_5d": "High 5 วันก่อนงบ", "high_3m": "High 3 เดือนก่อนงบ"}


def format_breakouts(snaps):
    """ข้อความเตือนทะลุแนวจาก snapshot ที่ new_breaks ไม่ว่าง — None ถ้าไม่มี"""
    if not snaps:
        return None
    lines = ["🚀 ทะลุแนว! (watchlist)"]
    for s in snaps:
        icon = GRADE_ICON.get(s.get("grade"), "⚪")
        lines.append("")
        lines.append(f"{icon} {s['symbol']} — {s['name']}")
        lines.append(f"💰 ปิด {s['price']:,.2f} ({_signed(s['day_change_pct'])})")
        broke = " · ".join(
            f"{_BREAK_TH[k]} ({s['levels'][k]:,.2f})" for k in s["new_breaks"])
        lines.append(f"📈 ทะลุ {broke}")
        if s.get("vol_ratio") is not None:
            fire = " 🔥" if s["vol_ratio"] >= 2 else ""
            lines.append(f"📊 วอลุ่ม {s['vol_ratio']:.1f}x เฉลี่ย 20 วัน{fire}")
        if s.get("dr_symbols"):
            lines.append(f"🇹🇭 DR: {s['dr_symbols']}")
    return "\n".join(lines)


def format_sl_breaks(snaps):
    """ข้อความเตือนหลุด SL จาก snapshot ที่ sl_break เป็นจริง — None ถ้าไม่มี"""
    if not snaps:
        return None
    lines = ["🛑 หลุด SL! (watchlist)"]
    for s in snaps:
        icon = GRADE_ICON.get(s.get("grade"), "⚪")
        lines.append("")
        lines.append(f"{icon} {s['symbol']} — {s['name']}")
        lines.append(f"💰 ปิด {s['price']:,.2f} ({_signed(s['day_change_pct'])}) · "
                     f"low {s['low']:,.2f}")
        lines.append(f"🛑 ต่ำกว่า SL (low วันงบ): {s['levels']['sl']:,.2f}")
        if s.get("dr_symbols"):
            lines.append(f"🇹🇭 DR: {s['dr_symbols']}")
    return "\n".join(lines)


def _compact_level(label, value, pct):
    """แนวต้านแบบย่อหนึ่งช่วง: "H5d 176.10 ✅" หรือ "H5d 190.00 (อีก 3.7%)" """
    if value is None:
        return f"{label} n/a"
    if pct is None:
        return f"{label} {value:,.2f}"
    if pct >= 0:
        return f"{label} {value:,.2f} ✅"
    return f"{label} {value:,.2f} (อีก {abs(pct)}%)"


def format_watch_detail(items, auto_dates=None):
    """ตาราง levels ของหุ้นที่ติดตาม (พิมพ์ "ติดตาม") — items: [(symbol, snap|None)]

    snap None = ดึงข้อมูลไม่ได้ · auto_dates: {symbol: วันเข้า} แยกกลุ่ม 🤖
    ความยาว: เพดาน manual+auto 40 ตัว × 3 บรรทัดสั้น ยังไม่ชน MAX_LEN
    """
    if not items:
        return None
    auto_dates = auto_dates or {}

    def block(sym, s):
        if s is None:
            return [f"⚠️ {sym} — ดึงข้อมูลไม่ได้"]
        icon = GRADE_ICON.get(s.get("grade"), "⚪")
        head = f"{icon} {sym} — {s['price']:,.2f} ({_signed(s['day_change_pct'])})"
        if sym in auto_dates:
            head += f" · เข้า {auto_dates[sym]}"
        lv = s.get("levels")
        if lv is None:
            note = ("⏳ รอวันตอบรับงบ" if s.get("pending_reaction")
                    else "ไม่มีงบใน 60 วัน — ไม่มีแนวให้เทียบ")
            return [head, f"   {note}"]
        lines = [head,
                 "   " + _compact_level("H5d", lv["high_5d"], lv["pct_vs_high_5d"])
                 + " · " + _compact_level("H3m", lv["high_3m"], lv["pct_vs_high_3m"])]
        tail = []
        if lv["sl"] is not None:
            tail.append(f"SL {lv['sl']:,.2f} (-{lv['sl_pct']}%)")
        if lv["low_5d"] is not None:
            mark = "🛑 หลุดแล้ว" if below_low_5d(lv) else "✅"
            tail.append(f"Low ก่อนงบ {lv['low_5d']:,.2f} {mark}")
        if tail:
            lines.append("   " + " · ".join(tail))
        return lines

    manual = [(s, snap) for s, snap in items if s not in auto_dates]
    auto = [(s, snap) for s, snap in items if s in auto_dates]
    lines = []
    if manual:
        lines.append(f"👀 ติดตามอยู่ {len(manual)} ตัว")
        for sym, snap in manual:
            lines += block(sym, snap)
    if auto:
        if lines:
            lines.append("")
        lines.append("🤖 อัตโนมัติจากสแกน A/B:")
        for sym, snap in auto:
            lines += block(sym, snap)
    lines += ["", "เตือนวันงบ 08:25 · แนว/หลุดแนว 08:20 · "
                  "เอาออก: เลิกติดตาม <ticker>"]
    return "\n".join(lines)


def format_low_breaks(snaps, removed=()):
    """เตือนหลุด Low 5 วันก่อนงบ (คายการตอบรับงบทั้งก้อน = setup จบ)

    removed: ตัวที่ถูกเอาออกจาก auto-watch เพราะปิดใต้แนวนี้ (รวมตัวที่หลุด
    ค้างมาหลายวันโดยไม่มี edge วันนี้ — ห้ามหายเงียบ) · ว่างทั้งคู่ → None
    """
    if not snaps and not removed:
        return None
    lines = ["⛔ หลุด Low 5 วันก่อนงบ! (watchlist)"]
    for s in snaps:
        icon = GRADE_ICON.get(s.get("grade"), "⚪")
        lines.append("")
        lines.append(f"{icon} {s['symbol']} — {s['name']}")
        lines.append(f"💰 ปิด {s['price']:,.2f} ({_signed(s['day_change_pct'])}) · "
                     f"low {s['low']:,.2f}")
        lines.append(f"⛔ ต่ำกว่า Low 5 วันก่อนงบ: {s['levels']['low_5d']:,.2f} "
                     "— คายการตอบรับงบทั้งก้อนแล้ว")
        if s.get("dr_symbols"):
            lines.append(f"🇹🇭 DR: {s['dr_symbols']}")
    if removed:
        lines += ["", f"🗑 เลิกติดตามอัตโนมัติ (setup จบ): {', '.join(removed)}"]
    return "\n".join(lines)


def format_open_report(items):
    """ยืนยันช่วงเปิดตลาด US สำหรับหุ้นที่ติดตาม — None ถ้าไม่มีข้อมูล"""
    if not items:
        return None
    lines = ["🇺🇸 ตลาด US เปิดแล้ว ~30 นาที (หุ้นที่ติดตาม)"]
    for it in items:
        icon = "🟢" if it["day_pct"] >= 0 else "🔴"
        line = f"{icon} {it['symbol']} {it['price']:,.2f} ({_signed(it['day_pct'])})"
        if it.get("gap_pct") is not None:
            line += f" · gap {_signed(it['gap_pct'])}"
        if it.get("above_open") is True:
            line += " · เหนือราคาเปิด ✅"
        elif it.get("above_open") is False:
            line += " · ต่ำกว่าราคาเปิด ⚠️"
        lines.append(line)
    lines.append("\n(ราคาระหว่างวัน อาจดีเลย์ ~15 นาที)")
    return "\n".join(lines)


def format_weekly(items):
    """สรุปผลหุ้นที่เคยแจ้ง (PEAD drift) — None ถ้าไม่มีสัญญาณในช่วงที่ดู"""
    if not items:
        return None
    items = sorted(items, key=lambda it: it["pct"], reverse=True)
    lines = ["📊 สรุปผลหุ้นที่บอทแจ้ง (30 วันล่าสุด)"]
    for it in items:
        icon = GRADE_ICON.get(it.get("grade"), "⚪")
        score = f" · {it['score']:.0f}" if it.get("score") is not None else ""
        lines.append("")
        lines.append(f"{icon} {it['symbol']} [เกรด {it['grade']}{score}] "
                     f"แจ้ง {it['flag_date']} @ {it['flag_price']:,.2f}")
        line = (f"   ตอนนี้ {it['price_now']:,.2f} → {_signed(it['pct'])} "
                f"({it['days']} วัน)")
        if it.get("sl_hit"):
            line += f" · 🛑 เคยหลุด SL {it['sl']:,.2f} เมื่อ {it['sl_hit']}"
        lines.append(line)
    n = len(items)
    avg = sum(it["pct"] for it in items) / n
    wins = sum(1 for it in items if it["pct"] > 0)
    lines += ["", f"รวม {n} ตัว · เฉลี่ย {_signed(avg)} · บวก {wins}/{n}"]
    return "\n".join(lines)


DR_PREMIUM_TH = 1.5             # |premium| เกินนี้ (%) ถึงติดป้ายแพง/ถูกกว่าปกติ


def format_dr(symbol, name, items, hidden=0):
    """รายงาน DR premium — items: [(dr_symbol, premium_dict | None)]

    hidden: จำนวน DR ที่ถูกตัดเพราะเกินเพดาน (แจ้งท้ายข้อความ ไม่ตัดเงียบ)
    """
    lines = [f"🇹🇭 DR Premium — {name} ({symbol})"]
    first = next((p for _, p in items if p), None)
    if first:
        lines.append(f"หุ้นแม่ ${first['us_price']:,.2f} ({first['us_date']}) · "
                     f"USDTHB {first['fx']:.2f}")
    for dr_sym, p in items:
        lines.append("")
        if p is None:
            lines.append(f"{dr_sym}: ข้อมูลไม่พอ (DR ใหม่/ซื้อขายเบาบาง "
                         "หรือดึงราคาไม่ได้)")
            continue
        lines.append(f"{dr_sym}: ฿{p['dr_price']:,.2f} ({p['dr_date']}) · "
                     f"วอลุ่ม {_fmt_volume(p['volume'])}")
        pct = p["premium_pct"]
        if pct > DR_PREMIUM_TH:
            verdict = "🔺 แพงกว่าปกติ"
        elif pct < -DR_PREMIUM_TH:
            verdict = "🔻 ถูกกว่าปกติ"
        else:
            verdict = "≈ ใกล้เคียงปกติ"
        lines.append(f"  อิง ratio ปกติ {p['fair']:,.2f} บาท → "
                     f"{_signed(pct)} {verdict}")
    if hidden:
        lines += ["", f"(ไม่แสดงอีก {hidden} DR — เกินเพดานต่อข้อความ)"]
    lines += ["", f"(เทียบค่ากลาง ratio DR/หุ้นแม่ ย้อนหลัง — "
                  "บวก = DR แพงกว่าช่วงที่ผ่านมา)"]
    return "\n".join(lines)


def format_stats(groups, total):
    """สถิติสะสมทุกสัญญาณ (จาก stats.summarize) — None ถ้ายังไม่มีที่ประเมินได้"""
    all_g = groups.get("all")
    if not all_g or not all_g["n"]:
        return None
    lines = ["📊 สถิติสะสมสัญญาณที่บอทแจ้ง",
             f"ทั้งหมด {total} สัญญาณ · ประเมินได้ {all_g['n']}"]
    for key, label in (("A", "เกรด A"), ("B", "เกรด B"), ("all", "รวมทุกเกรด")):
        g = groups.get(key)
        if not g or not g["n"]:
            continue
        lines += ["", f"{GRADE_ICON.get(key, '⚪')} {label} — {g['n']} ตัว"]
        for h in HORIZONS:
            hh = g["horizons"][h]
            if hh["n"]:
                lines.append(f"  +{h} วัน: เฉลี่ย {_signed(hh['avg'])} · "
                             f"ชนะ {hh['wins']}/{hh['n']}")
            else:
                lines.append(f"  +{h} วัน: ยังไม่มีตัวที่ถือถึง")
        if g["sl_n"]:
            lines.append(f"  🛑 เคยหลุด SL: {g['sl_hits']}/{g['sl_n']}")
    return "\n".join(lines)


_TIMING_TH = {"bmo": "ก่อนเปิดตลาด US", "amc": "หลังปิดตลาด US"}
_DAYS_TH = {0: "วันนี้", 1: "พรุ่งนี้"}


def format_reminders(items):
    """ข้อความเตือนวันงบจาก build_reminders — None ถ้าไม่มีอะไรต้องเตือน"""
    if not items:
        return None
    lines = ["📅 เตือนวันงบ (watchlist)"]
    for it in items:
        when = _DAYS_TH.get(it["days_to"], f"อีก {it['days_to']} วัน")
        line = f"• {it['symbol']} — งบ{when} ({it['date']})"
        label = _TIMING_TH.get(it["timing"])
        if label:
            line += f" {label}"
        lines.append(line)
    return "\n".join(lines)


def format_scan(scan):
    """คืน list ข้อความ (แต่ละฉบับ ≤ MAX_LEN ตัวอักษร) สำหรับส่ง Telegram"""
    skipped = scan["skipped_counts"]
    header = (
        f"📊 Earnings Screener {scan['from_date']} → {scan['to_date']}\n"
        f"Universe {scan['universe_size']} ตัว · ออกงบ {len(scan['reported_symbols'])} ตัว"
    )
    footer = f"ตกเกณฑ์: C={skipped['C']}, D={skipped['D']}"
    pending = scan.get("pending") or []
    blocked = [p for p in pending if p.get("reason") == "not_in_plan"]
    waiting = [p for p in pending if p.get("reason") != "not_in_plan"]
    if waiting:
        plist = ", ".join(f"{p['symbol']} ({p['date']})" for p in waiting)
        footer += f"\n⏳ รอวันตอบรับงบ (สแกนรอบถัดไป): {plist}"
    if blocked:
        plist = ", ".join(f"{p['symbol']} ({p['date']})" for p in blocked)
        footer += f"\n🔒 แผนฟรี FMP ไม่ครอบคลุม: {plist}"

    if not scan["candidates"]:
        return [f"{header}\n\n😴 ไม่มีหุ้นเข้าเกณฑ์เกรด A/B\n{footer}"]

    sep = "\n" + "─" * 28 + "\n"
    messages, current = [], header
    for block in (_format_candidate(c) for c in scan["candidates"]):
        if len(current) + len(sep) + len(block) > MAX_LEN:
            messages.append(current)
            current = block
        else:
            current += sep + block
    if len(current) + len(sep) + len(footer) <= MAX_LEN:
        messages.append(current + sep + footer)
    else:
        messages.append(current)
        messages.append(footer)
    return messages
