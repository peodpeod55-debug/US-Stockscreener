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


def test_load_config_missing_raises(tmp_path, monkeypatch):
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "FMP_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=tok\n")
    with pytest.raises(ValueError, match="TELEGRAM_CHAT_ID"):
        load_config(env)
