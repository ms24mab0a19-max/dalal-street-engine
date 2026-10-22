"""Validated loaders for the Dalal Street market definition files."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
STOCKS_PATH = ROOT / "stocks.json"
TIMELINE_PATH = ROOT / "timeline.json"

TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")


@dataclass(frozen=True, slots=True)
class Stock:
    ticker: str
    name: str
    sector: str
    base_price: float


@dataclass(frozen=True, slots=True)
class Shock:
    id: str
    round: int
    name: str
    description: str
    company_modifiers: dict[str, float]
    sector_modifiers: dict[str, float]

    def affects(self, stock: Stock) -> bool:
        return stock.ticker in self.company_modifiers or stock.sector in self.sector_modifiers


def _read_json(path: Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _modifier_map(value: Any, label: str, shock_id: str) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Shock '{shock_id}' must define {label} as an object.")
    modifiers: dict[str, float] = {}
    for key, modifier in value.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"Shock '{shock_id}' has an invalid {label} key.")
        if not _is_number(modifier) or modifier <= -1:
            raise ValueError(
                f"Shock '{shock_id}' has an invalid {label} value for {key}; "
                "use a decimal greater than -1 (0.15 means +15%)."
            )
        modifiers[key] = float(modifier)
    return modifiers


def load_stocks(path: str | Path = STOCKS_PATH) -> tuple[Stock, ...]:
    """Load and validate the listed companies from stocks.json."""

    raw = _read_json(Path(path))
    if not isinstance(raw, list) or not raw:
        raise ValueError("stocks.json must contain a non-empty list of companies.")

    stocks: list[Stock] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Stock #{index} must be a JSON object.")
        required = {"ticker", "name", "sector", "base_price"}
        missing = required - item.keys()
        if missing:
            raise ValueError(f"Stock #{index} is missing: {', '.join(sorted(missing))}.")

        ticker = item["ticker"]
        if not isinstance(ticker, str) or not TICKER_PATTERN.fullmatch(ticker):
            raise ValueError(f"Stock #{index} has an invalid ticker: {ticker!r}.")
        if ticker in seen:
            raise ValueError(f"Duplicate ticker in stocks.json: {ticker}.")
        seen.add(ticker)

        name = item["name"]
        sector = item["sector"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Stock {ticker} must have a non-empty name.")
        if not isinstance(sector, str) or not sector.strip():
            raise ValueError(f"Stock {ticker} must have a non-empty sector.")

        base_price = item["base_price"]
        if not _is_number(base_price) or base_price < 1:
            raise ValueError(f"Stock {ticker} must have a base_price of at least ₹1.00.")

        stocks.append(Stock(ticker, name.strip(), sector.strip(), float(base_price)))

    return tuple(stocks)


def load_timeline(
    path: str | Path = TIMELINE_PATH,
    stocks: tuple[Stock, ...] | list[Stock] | None = None,
) -> tuple[Shock, ...]:
    """Load and validate the round-indexed shocks from timeline.json."""

    raw = _read_json(Path(path))
    if not isinstance(raw, list) or not raw:
        raise ValueError("timeline.json must contain a non-empty list of shocks.")

    known_tickers = {stock.ticker for stock in stocks or ()}
    known_sectors = {stock.sector for stock in stocks or ()}
    shocks: list[Shock] = []
    seen_ids: set[str] = set()
    seen_rounds: set[int] = set()

    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Shock #{index} must be a JSON object.")
        required = {"id", "round", "name", "description"}
        missing = required - item.keys()
        if missing:
            raise ValueError(f"Shock #{index} is missing: {', '.join(sorted(missing))}.")

        shock_id = item["id"]
        if not isinstance(shock_id, str) or not shock_id.strip():
            raise ValueError(f"Shock #{index} must have a non-empty id.")
        if shock_id in seen_ids:
            raise ValueError(f"Duplicate shock id: {shock_id}.")
        seen_ids.add(shock_id)

        round_number = item["round"]
        if not isinstance(round_number, int) or isinstance(round_number, bool) or round_number < 1:
            raise ValueError(f"Shock '{shock_id}' must have a positive integer round.")
        if round_number in seen_rounds:
            raise ValueError(f"timeline.json has more than one shock for Round {round_number}.")
        seen_rounds.add(round_number)

        name = item["name"]
        description = item["description"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Shock '{shock_id}' must have a non-empty name.")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"Shock '{shock_id}' must have a non-empty description.")

        company_modifiers = _modifier_map(
            item.get("company_modifiers", {}), "company_modifiers", shock_id
        )
        sector_modifiers = _modifier_map(
            item.get("sector_modifiers", {}), "sector_modifiers", shock_id
        )
        if not company_modifiers and not sector_modifiers:
            raise ValueError(f"Shock '{shock_id}' does not affect any company or sector.")

        unknown_tickers = set(company_modifiers) - known_tickers
        if unknown_tickers:
            raise ValueError(
                f"Shock '{shock_id}' references unknown ticker(s): "
                f"{', '.join(sorted(unknown_tickers))}."
            )
        unknown_sectors = set(sector_modifiers) - known_sectors
        if unknown_sectors:
            raise ValueError(
                f"Shock '{shock_id}' references unknown sector(s): "
                f"{', '.join(sorted(unknown_sectors))}."
            )

        shocks.append(
            Shock(
                id=shock_id,
                round=round_number,
                name=name.strip(),
                description=description.strip(),
                company_modifiers=company_modifiers,
                sector_modifiers=sector_modifiers,
            )
        )

    return tuple(sorted(shocks, key=lambda shock: (shock.round, shock.id)))
