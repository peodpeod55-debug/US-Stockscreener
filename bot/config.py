"""อ่าน config จาก .env / environment variables"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Config:
    telegram_token: str
    chat_id: str
    fmp_api_key: str
    lookback_days: int = 2
    max_api_calls: int = 200


def load_config(env_path: Path | None = None) -> Config:
    load_dotenv(env_path or PROJECT_ROOT / ".env")
    required = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "FMP_API_KEY"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise ValueError(f"missing config keys: {', '.join(missing)}")
    return Config(
        telegram_token=os.environ["TELEGRAM_BOT_TOKEN"],
        chat_id=os.environ["TELEGRAM_CHAT_ID"],
        fmp_api_key=os.environ["FMP_API_KEY"],
        lookback_days=int(os.environ.get("SCAN_LOOKBACK_DAYS", "2")),
        max_api_calls=int(os.environ.get("MAX_API_CALLS", "200")),
    )
