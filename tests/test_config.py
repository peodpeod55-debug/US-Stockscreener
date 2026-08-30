import pytest

from bot.config import load_config


def test_load_config_from_env(tmp_path, monkeypatch):
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "FMP_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "TELEGRAM_BOT_TOKEN=tok123\nTELEGRAM_CHAT_ID=111\nFMP_API_KEY=fmp456\n"
    )
    cfg = load_config(env)
    assert cfg.telegram_token == "tok123"
    assert cfg.chat_id == "111"
    assert cfg.fmp_api_key == "fmp456"
    assert cfg.lookback_days == 2


def test_load_config_tolerates_utf8_bom(tmp_path, monkeypatch):
    """ไฟล์ .env ที่เซฟจาก Notepad/PowerShell มักมี BOM — ต้องไม่ทำให้ key แรกพัง"""
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "FMP_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_bytes(
        b"\xef\xbb\xbfTELEGRAM_BOT_TOKEN=tok123\nTELEGRAM_CHAT_ID=111\nFMP_API_KEY=fmp456\n"
    )
    cfg = load_config(env)
    assert cfg.telegram_token == "tok123"


def test_finnhub_key_is_optional(tmp_path, monkeypatch):
    """FINNHUB_API_KEY ไม่บังคับ — ไม่มี = "" (บอทข้ามแหล่ง Finnhub เงียบ ๆ)"""
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "FMP_API_KEY", "FINNHUB_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=tok\nTELEGRAM_CHAT_ID=1\nFMP_API_KEY=f\n")
    assert load_config(env).finnhub_api_key == ""
    env.write_text("TELEGRAM_BOT_TOKEN=tok\nTELEGRAM_CHAT_ID=1\nFMP_API_KEY=f\n"
                   "FINNHUB_API_KEY=fh-key\n")
    assert load_config(env).finnhub_api_key == "fh-key"


def test_rescore_settings_default_and_override(tmp_path, monkeypatch):
    """เกณฑ์ไทยมีชีวิต: SET_QUALIFY_MIN (ข้ามเกณฑ์แจ้งครั้งแรก) + RESCORE_DAYS (กรอบคิดซ้ำ)"""
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "FMP_API_KEY",
              "SET_QUALIFY_MIN", "RESCORE_DAYS"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=tok\nTELEGRAM_CHAT_ID=1\nFMP_API_KEY=f\n")
    cfg = load_config(env)
    assert cfg.set_qualify_min == 10
    assert cfg.rescore_days == 14
    env.write_text("TELEGRAM_BOT_TOKEN=tok\nTELEGRAM_CHAT_ID=1\nFMP_API_KEY=f\n"
                   "SET_QUALIFY_MIN=12\nRESCORE_DAYS=7\n")
    cfg = load_config(env)
    assert cfg.set_qualify_min == 12
    assert cfg.rescore_days == 7


def test_load_config_missing_raises(tmp_path, monkeypatch):
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "FMP_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=tok\n")
    with pytest.raises(ValueError, match="TELEGRAM_CHAT_ID"):
        load_config(env)
