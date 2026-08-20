#!/usr/bin/env python3
"""
FMP API Client for Earnings Trade Analyzer

Provides rate-limited access to Financial Modeling Prep API endpoints
for post-earnings trade analysis and scoring.

Features:
- Rate limiting (0.3s between requests)
- Automatic retry on 429 errors
- Session caching for duplicate requests
- API call budget enforcement
- Batch profile support
- Earnings calendar fetching
"""

import os
import sys
import time
from typing import Optional

try:
    import requests
except ImportError:
    print("ERROR: requests library not found. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)


# --- FMP endpoint fallback: stable (new users) -> v3 (legacy users) ---


def _stable_eod_url(base, symbols_str, params):
    """stable/historical-price-eod/full?symbol=SPY (ignores timeseries; caller slices)"""
    params.pop("timeseries", None)
    params["symbol"] = symbols_str
    return base, params


def _stable_hist_url(base, symbols_str, params):
    """stable/historical-price-full?symbol=SPY&timeseries=90"""
    params["symbol"] = symbols_str
    return base, params


def _v3_hist_url(base, symbols_str, params):
    """api/v3/historical-price-full/SPY?timeseries=90"""
    return f"{base}/{symbols_str}", params


_FMP_ENDPOINTS = {
    "historical": [
        # 2026-08: FMP retired historical-price-full for new keys; eod/full is current
        ("https://financialmodelingprep.com/stable/historical-price-eod/full", _stable_eod_url),
        ("https://financialmodelingprep.com/stable/historical-price-full", _stable_hist_url),
        ("https://financialmodelingprep.com/api/v3/historical-price-full", _v3_hist_url),
    ],
}


class ApiCallBudgetExceeded(Exception):
    """Raised when the API call budget has been exhausted."""

    pass


class FMPClient:
    """Client for Financial Modeling Prep API with rate limiting, caching, and budget control"""

    BASE_URL = "https://financialmodelingprep.com/api/v3"
    STABLE_URL = "https://financialmodelingprep.com/stable"
    RATE_LIMIT_DELAY = 0.3  # 300ms between requests
    US_EXCHANGES = ["NYSE", "NASDAQ", "AMEX", "NYSEArca", "BATS", "NMS", "NGM", "NCM"]

    _ENDPOINT_FAILURE_THRESHOLD = 3  # disable endpoint after N consecutive failures

    def __init__(self, api_key: Optional[str] = None, max_api_calls: int = 200):
        self.api_key = api_key or os.getenv("FMP_API_KEY")
        if not self.api_key:
            raise ValueError(
                "FMP API key required. Set FMP_API_KEY environment variable "
                "or pass api_key parameter."
            )
        self.session = requests.Session()
        self.session.headers.update({"apikey": self.api_key})
        self.cache = {}
        self.last_call_time = 0
        self.rate_limit_reached = False
        self.retry_count = 0
        self.max_retries = 1
        self.api_calls_made = 0
        self.max_api_calls = max_api_calls
        # FMP free tier restricts some symbols (HTTP 402) — callers can
        # reset + inspect this flag to distinguish "not covered" from "not found"
        self.saw_402 = False
        # HTTP status of the most recent request (None if no response)
        self.last_status = None
        # Circuit breaker: track consecutive failures per endpoint URL prefix
        self._endpoint_failures: dict[str, int] = {}
        self._disabled_endpoints: set[str] = set()

    def _rate_limited_get(
        self, url: str, params: Optional[dict] = None, quiet: bool = False
    ) -> Optional[dict]:
        """Execute a rate-limited GET request with budget enforcement."""
        self.last_status = None
        if self.rate_limit_reached:
            return None

        if self.api_calls_made >= self.max_api_calls:
            raise ApiCallBudgetExceeded(
                f"API call budget exceeded: {self.api_calls_made}/{self.max_api_calls} calls used."
            )

        if params is None:
            params = {}

        elapsed = time.time() - self.last_call_time
        if elapsed < self.RATE_LIMIT_DELAY:
            time.sleep(self.RATE_LIMIT_DELAY - elapsed)

        try:
            response = self.session.get(url, params=params, timeout=30)
            self.last_call_time = time.time()
            self.api_calls_made += 1
            self.last_status = response.status_code

            if response.status_code == 200:
                self.retry_count = 0
                return response.json()
            elif response.status_code == 429:
                self.retry_count += 1
                if self.retry_count <= self.max_retries:
                    print("WARNING: Rate limit exceeded. Waiting 60 seconds...", file=sys.stderr)
                    time.sleep(60)
                    return self._rate_limited_get(url, params, quiet=quiet)
                else:
                    print("ERROR: Daily API rate limit reached.", file=sys.stderr)
                    self.rate_limit_reached = True
                    return None
            else:
                if response.status_code == 402:
                    self.saw_402 = True
                if not quiet:
                    print(
                        f"ERROR: API request failed: {response.status_code} - {response.text[:200]}",
                        file=sys.stderr,
                    )
                return None
        except requests.exceptions.Timeout:
            print(f"WARNING: Request timed out for {url}", file=sys.stderr)
            return None
        except requests.exceptions.RequestException as e:
            print(f"ERROR: Request exception: {e}", file=sys.stderr)
            return None

    def _request_with_fallback(self, endpoint_key, symbols_str, extra_params=None):
        """Try stable endpoint first, fall back to v3 for legacy users.

        Returns parsed JSON in v3-compatible shape, or None if all fail.
        Non-last endpoints use quiet=True to suppress expected 403 stderr.
        """
        params = dict(extra_params) if extra_params else {}
        endpoints = _FMP_ENDPOINTS[endpoint_key]
        is_single = "," not in symbols_str

        for i, (base_url, url_builder) in enumerate(endpoints):
            # Circuit breaker: skip endpoints with too many consecutive failures
            if base_url in self._disabled_endpoints:
                continue

            url, final_params = url_builder(base_url, symbols_str, dict(params))
            is_last = i == len(endpoints) - 1
            data = self._rate_limited_get(url, final_params, quiet=not is_last)
            if not data:  # falsy (None, [], {}) -- try next endpoint
                if self.last_status == 402:
                    # 402 = symbol not in plan, not a broken endpoint: don't
                    # count toward the circuit breaker, and the fallback
                    # endpoints can't serve a plan-blocked symbol either
                    return None
                self._record_endpoint_failure(base_url)
                continue

            # Shape validation: reject truthy-but-wrong-shape responses
            valid = True
            if endpoint_key == "historical":
                if isinstance(data, list) and isinstance(data[0], dict) and "close" in data[0]:
                    # stable eod flat-list format (most-recent-first) -> v3 single format
                    self._endpoint_failures[base_url] = 0
                    return {"symbol": symbols_str, "historical": data}
                if not isinstance(data, dict):
                    valid = False
                elif "historicalStockList" in data:
                    # stable batch format -> v3 single format (exact match only)
                    norm = symbols_str.replace("-", ".")
                    found = None
                    for entry in data["historicalStockList"]:
                        if entry.get("symbol", "").replace("-", ".") == norm:
                            found = {
                                "symbol": entry.get("symbol"),
                                "historical": entry.get("historical", []),
                            }
                            break
                    if found:
                        self._endpoint_failures[base_url] = 0
                        return found
                    valid = False
                elif "historical" not in data:
                    valid = False
                elif is_single and data.get("symbol"):
                    if data["symbol"].replace("-", ".") != symbols_str.replace("-", "."):
                        valid = False

            if valid:
                self._endpoint_failures[base_url] = 0
                return data
            self._record_endpoint_failure(base_url)
        return None

    def _record_endpoint_failure(self, base_url: str) -> None:
        """Track consecutive failures and disable endpoint after threshold."""
        failures = self._endpoint_failures.get(base_url, 0) + 1
        self._endpoint_failures[base_url] = failures
        if failures >= self._ENDPOINT_FAILURE_THRESHOLD:
            self._disabled_endpoints.add(base_url)

    def get_earnings_calendar(self, from_date: str, to_date: str) -> Optional[list]:
        """Fetch earnings calendar for a date range.

        Args:
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)

        Returns:
            List of earnings announcements or None on failure.
        """
        cache_key = f"earnings_{from_date}_{to_date}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        url = f"{self.STABLE_URL}/earnings-calendar"
        params = {"from": from_date, "to": to_date}
        data = self._rate_limited_get(url, params)
        if data:
            self.cache[cache_key] = data
        return data

    def get_company_profiles(self, symbols: list[str]) -> dict[str, dict]:
        """Fetch company profiles one symbol at a time (stable API requires individual requests).

        Args:
            symbols: List of ticker symbols

        Returns:
            Dictionary mapping symbol to profile data.
        """
        profiles = {}
        url = f"{self.STABLE_URL}/profile"

        for symbol in symbols:
            cache_key = f"profile_{symbol}"
            if cache_key in self.cache:
                profiles[symbol] = self.cache[cache_key]
                continue

            data = self._rate_limited_get(url, {"symbol": symbol})
            if data and isinstance(data, list) and len(data) > 0:
                profile = data[0]
                self.cache[cache_key] = profile
                profiles[symbol] = profile

        return profiles

    @staticmethod
    def _valid_earnings_rows(data) -> bool:
        return (
            isinstance(data, list)
            and len(data) > 0
            and isinstance(data[0], dict)
            and "date" in data[0]
        )

    def get_earnings_dates(self, symbol: str) -> Optional[list]:
        """Fetch past + upcoming earnings dates for one symbol.

        Tries stable/earnings first (new keys), falls back to
        api/v3/historical/earning_calendar/{symbol} (legacy keys).

        Returns:
            List of dicts with at least a "date" key, or None on failure.
        """
        cache_key = f"earnings_dates_{symbol}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        data = self._rate_limited_get(
            f"{self.STABLE_URL}/earnings", {"symbol": symbol}, quiet=True
        )
        if not self._valid_earnings_rows(data):
            data = self._rate_limited_get(
                f"{self.BASE_URL}/historical/earning_calendar/{symbol}"
            )
        if self._valid_earnings_rows(data):
            self.cache[cache_key] = data
            return data
        return None

    def get_quote(self, symbol: str) -> Optional[dict]:
        """Fetch a live quote for one symbol (stable/quote, no caching).

        Returns:
            Dict with price/open/previousClose etc., or None on failure.
        """
        data = self._rate_limited_get(
            f"{self.STABLE_URL}/quote", {"symbol": symbol}, quiet=True
        )
        if (isinstance(data, list) and data and isinstance(data[0], dict)
                and data[0].get("price") is not None):
            return data[0]
        return None

    def get_historical_prices(self, symbol: str, days: int = 250) -> Optional[list[dict]]:
        """Fetch historical daily OHLCV data for a symbol.

        Args:
            symbol: Ticker symbol
            days: Number of trading days to fetch (default: 250)

        Returns:
            List of price dicts (most-recent-first) or None on failure.
        """
        cache_key = f"prices_{symbol}_{days}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        data = self._request_with_fallback("historical", symbol, {"timeseries": days})
        if data and "historical" in data:
            result = data["historical"][:days]
            self.cache[cache_key] = result
            return result
        return None

    def get_api_stats(self) -> dict:
        """Return API usage statistics."""
        return {
            "cache_entries": len(self.cache),
            "api_calls_made": self.api_calls_made,
            "max_api_calls": self.max_api_calls,
            "rate_limit_reached": self.rate_limit_reached,
        }
