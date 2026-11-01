"""
Exchange rates the project has documented. Only these currencies can be converted;
anything else returns None so callers can report "conversion unavailable" instead of guessing.

Rates live in data/exchange_rates.json (ECB reference rates, 1 EUR = x). To update them, edit that
file, or point EXCHANGE_RATES_FILE at another one. Rates older than EXCHANGE_RATES_MAX_AGE_DAYS
(default 30) are reported as outdated. They still convert, and callers show the warning.
"""
import json
import os
from datetime import date
from pathlib import Path
from typing import Optional

DEFAULT_RATES_FILE = Path(__file__).resolve().parents[2] / "data" / "exchange_rates.json"
RATES_FILE = Path(os.getenv("EXCHANGE_RATES_FILE") or DEFAULT_RATES_FILE)
MAX_AGE_DAYS = int(os.getenv("EXCHANGE_RATES_MAX_AGE_DAYS") or 30)

with open(RATES_FILE, encoding="utf-8") as _file:
    _config = json.load(_file)

RATES_SOURCE = _config["source"]
RATES_DATE = _config["date"]
EUR_RATES = _config["rates"]


def can_convert(from_currency: str, to_currency: str) -> bool:
    return from_currency in EUR_RATES and to_currency in EUR_RATES


def convert(amount: Optional[float], from_currency: str, to_currency: str) -> Optional[float]:
    """Amount in to_currency, or None when the amount or a rate is missing."""
    if amount is None:
        return None
    if from_currency == to_currency:
        return float(amount)
    if not can_convert(from_currency, to_currency):
        return None
    return float(amount) / EUR_RATES[from_currency] * EUR_RATES[to_currency]


def rates_info(today: Optional[date] = None) -> dict:
    age_days = ((today or date.today()) - date.fromisoformat(RATES_DATE)).days
    return {"source": RATES_SOURCE, "date": RATES_DATE, "age_days": age_days, "stale": age_days > MAX_AGE_DAYS}
