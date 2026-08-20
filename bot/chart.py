"""วาดกราฟแท่งเทียน PNG แนบข้อความแจ้ง (สแกน/ทะลุแนว/หลุด SL/lookup)

ใช้แท่งราคาที่ job เพิ่งดึง (ผ่าน fetch_cache) — ไม่มี API call เพิ่ม
ข้อความบนภาพเป็นอังกฤษล้วน (ฟอนต์ default ของ matplotlib ไม่มี glyph ไทย)
"""
import io
import logging

import matplotlib

matplotlib.use("Agg")           # headless — ห้ามมีหน้าต่าง GUI (บอท/CI)

import mplfinance as mpf        # noqa: E402
import pandas as pd             # noqa: E402

CHART_BARS = 120                # ~6 เดือน เห็นฐาน 3M + บริบทก่อนงบ

logger = logging.getLogger("bot.chart")

_LEVEL_COLORS = (("high_5d", "#2e7d32"), ("high_3m", "#1565c0"),
                 ("sl", "#c62828"))


def build_chart_png(symbol, prices, levels=None, last_n=CHART_BARS):
    """PNG กราฟแท่งเทียน + เส้นแนว (high_5d/high_3m/SL) + เส้นวันตอบรับงบ

    prices: list[dict] most-recent-first (convention เดียวกับ levels.py)
    คืน None ถ้าแท่งไม่พอ
    """
    if not prices or len(prices) < 2:
        return None
    plotted = list(reversed(prices[:last_n]))       # เก่า → ใหม่
    df = pd.DataFrame(plotted)
    df.index = pd.to_datetime(df["date"])
    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low",
                            "close": "Close", "volume": "Volume"})
    df = df[["Open", "High", "Low", "Close", "Volume"]]

    levels = levels or {}
    hline_vals, hline_colors = [], []
    for key, color in _LEVEL_COLORS:
        if levels.get(key) is not None:
            hline_vals.append(levels[key])
            hline_colors.append(color)
    kwargs = {}
    if hline_vals:
        kwargs["hlines"] = dict(hlines=hline_vals, colors=hline_colors,
                                linestyle="--", linewidths=1.0, alpha=0.8)
    rd = levels.get("reaction_date")
    if rd and plotted[0]["date"] <= rd <= plotted[-1]["date"]:
        kwargs["vlines"] = dict(vlines=[rd], colors=["#757575"],
                                linestyle=":", linewidths=1.0, alpha=0.8)

    buf = io.BytesIO()
    mpf.plot(df, type="candle", style="yahoo", volume=True,
             title=f"{symbol}  {prices[0]['close']:,.2f}",
             figsize=(10, 6), tight_layout=True, closefig=True,
             savefig=dict(fname=buf, format="png", dpi=100), **kwargs)
    return buf.getvalue()
