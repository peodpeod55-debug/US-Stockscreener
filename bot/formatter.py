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
