"""จัดข้อความ Telegram (plain text ภาษาไทย)"""
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


def format_scan(scan):
    """คืน list ข้อความ (แต่ละฉบับ ≤ MAX_LEN ตัวอักษร) สำหรับส่ง Telegram"""
    skipped = scan["skipped_counts"]
    header = (
        f"📊 Earnings Screener {scan['from_date']} → {scan['to_date']}\n"
        f"Universe {scan['universe_size']} ตัว · ออกงบ {len(scan['reported_symbols'])} ตัว"
    )
    footer = f"ตกเกณฑ์: C={skipped['C']}, D={skipped['D']}"
    pending = scan.get("pending") or []
    if pending:
        plist = ", ".join(f"{p['symbol']} ({p['date']})" for p in pending)
        footer += f"\n⏳ รอวันตอบรับงบ (สแกนรอบถัดไป): {plist}"

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
