"""The Dalal Street pricing engine.

The engine is deliberately free of Streamlit so the market mathematics can be
tested and reasoned about independently from the user interface.

Modified per stress-test requirements:
- Net demand normalized by stock base_price (baseline liquidity)
- Upper price ceiling safeguard (4x base price per round)
- Cumulative timeline shocks apply cleanly as percentage modifiers
- apply_shock handles None (no-shock) gracefully
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Mapping, Sequence

from market_data import Shock, Stock

ALPHA = 0.08
GAMMA = 0.002
BETA = 0.25
NOISE_LIMIT = 0.007
PRICE_FLOOR = 1.0
PRICE_CEILING_MULT = 4.0  # max 4x base price per round unless shock dictates


# The exponential is fully saturated long before this volume. Capping the
# magnitude keeps absurd integer inputs from raising during float conversion.
MAX_VOLUME_MAGNITUDE = 1_000_000_000


@dataclass(frozen=True, slots=True)
class RoundResult:
    prices: dict[str, float]
    streaks: dict[str, dict[str, int]]
    shock: Shock | None
    open_prices: dict[str, float]
    trade_prices: dict[str, float]
    high_prices: dict[str, float]
    low_prices: dict[str, float]


def streak_multiplier(streak: int) -> float:
    """Multiplier applied to a trade impact based on the current run length."""

    if streak >= 3:
        return 1.75
    if streak == 2:
        return 1.35
    return 1.0


def _next_streak(previous: Mapping[str, int], direction: int) -> tuple[int, int]:
    if direction == 0:
        return 0, 0
    if direction == previous.get("direction", 0):
        return direction, previous.get("count", 0) + 1
    return direction, 1


def shock_for_round(
    timeline: Sequence[Shock], round_number: int
) -> Shock | None:
    """Return the scheduled shock for a round, if the timeline has one."""

    return next((shock for shock in timeline if shock.round == round_number), None)


def compute_round(
    stocks: Sequence[Stock],
    prices: Mapping[str, float],
    streaks: Mapping[str, Mapping[str, int]],
    volumes: Mapping[str, tuple[int, int]],
    *,
    round_number: int,
    timeline: Sequence[Shock] = (),
    rng: random.Random | None = None,
) -> RoundResult:
    """Compute one round from a single opening board.

    ``volumes`` maps each ticker to ``(buy_volume, sell_volume)``. Trade
    pricing, noise, and sector contagion produce a trade close first. If
    ``timeline`` contains a shock for ``round_number``, that shock is applied
    to the trade close immediately, shifting the baseline permanently.

    OHLC is derived from the two observable stages of the round: the opening
    board and the trade close, plus the final close after any shock. Because
    the simulation has no intraround ticks, the high and low are the extremes
    of those actual computed prices (the shock-stage close can produce a wick).

    Net demand is normalized by the stock's base_price (baseline liquidity)
    so that absolute volume inputs do not cause disproportionate % moves on
    lower-priced scrips.

    The effective gamma is GAMMA * |N| / base_price, so that a given absolute
    net demand N produces a % impact proportional to the stock's price level.
    Higher-priced stocks get relatively smaller % moves for the same absolute
    volume, while lower-priced stocks get relatively larger % moves — which
    prevents runaway 50%+ distortions on low-priced scrips while still
    allowing meaningful price discovery.
    """

    rng = rng or random
    preliminary: dict[str, float] = {}
    next_streaks: dict[str, dict[str, int]] = {}

    for stock in stocks:
        buy, sell = volumes.get(stock.ticker, (0, 0))
        net_demand = int(buy) - int(sell)
        direction = (net_demand > 0) - (net_demand < 0)
        streak_direction, streak_count = _next_streak(
            streaks.get(stock.ticker, {}), direction
        )
        multiplier = streak_multiplier(streak_count)

        # --- NET DEMAND NORMALIZATION by baseline liquidity (base_price) ---
        # Effective gamma = GAMMA * |N| / base_price. A given absolute net
        # demand N produces a % impact inversely proportional to the stock's
        # base price. This prevents the exponential from saturating on small-
        # priced scrips while still allowing meaningful moves on large-priced
        # stocks.
        effective_gamma = GAMMA * min(abs(net_demand), MAX_VOLUME_MAGNITUDE) / max(stock.base_price, 1.0)
        trade_change = (
            direction * ALPHA * (1 - math.exp(-effective_gamma)) * multiplier
        )

        noise = rng.uniform(-NOISE_LIMIT, NOISE_LIMIT)
        preliminary[stock.ticker] = trade_change + noise
        next_streaks[stock.ticker] = {
            "direction": streak_direction,
            "count": streak_count,
        }

    trade_prices: dict[str, float] = {}
    for stock in stocks:
        peers = [
            preliminary[other.ticker]
            for other in stocks
            if other.sector == stock.sector and other.ticker != stock.ticker
        ]
        sector_change = BETA * (sum(peers) / len(peers)) if peers else 0.0
        total_change = preliminary[stock.ticker] + sector_change
        trade_prices[stock.ticker] = max(
            PRICE_FLOOR,
            min(
                PRICE_CEILING_MULT * stock.base_price,
                round(prices[stock.ticker] * (1 + total_change), 2),
            ),
        )

    # Apply scheduled shock if one exists for this round
    scheduled_shock = shock_for_round(timeline, round_number)
    if scheduled_shock is not None:
        final_prices = apply_shock(stocks, trade_prices, scheduled_shock)
    else:
        final_prices = dict(trade_prices)

    # Enforce ceiling on final prices after shock compounding
    for stock in stocks:
        final_prices[stock.ticker] = min(
            PRICE_CEILING_MULT * stock.base_price,
            final_prices[stock.ticker],
        )

    opening = {stock.ticker: float(prices[stock.ticker]) for stock in stocks}
    high_prices = {
        stock.ticker: max(
            opening[stock.ticker],
            trade_prices[stock.ticker],
            final_prices[stock.ticker],
        )
        for stock in stocks
    }
    low_prices = {
        stock.ticker: min(
            opening[stock.ticker],
            trade_prices[stock.ticker],
            final_prices[stock.ticker],
        )
        for stock in stocks
    }

    return RoundResult(
        prices=final_prices,
        streaks=next_streaks,
        shock=scheduled_shock,
        open_prices=opening,
        trade_prices=trade_prices,
        high_prices=high_prices,
        low_prices=low_prices,
    )


def apply_shock(
    stocks: Sequence[Stock], prices: Mapping[str, float], shock: Shock | None
) -> dict[str, float]:
    """Apply a scheduled shock to the live board.

    The shaken prices are returned as the new baseline. Nothing records a
    temporary modifier, so later rounds naturally compound from this level.
    Company and sector modifiers are multiplied together if both apply.

    If shock is None, returns prices unchanged (clamped to floor/ceiling).
    Prices are clamped to [PRICE_FLOOR, PRICE_CEILING_MULT * base_price].
    """

    if shock is None:
        # No shock: just clamp to bounds
        result = dict(prices)
        for stock in stocks:
            result[stock.ticker] = max(
                PRICE_FLOOR,
                min(PRICE_CEILING_MULT * stock.base_price, round(result[stock.ticker], 2)),
            )
        return result

    shocked_prices = dict(prices)
    for stock in stocks:
        sector_modifier = shock.sector_modifiers.get(stock.sector)
        company_modifier = shock.company_modifiers.get(stock.ticker)
        if sector_modifier is None and company_modifier is None:
            # No modifier applies to this stock; keep price but still clamp
            shocked_prices[stock.ticker] = max(
                PRICE_FLOOR,
                min(PRICE_CEILING_MULT * stock.base_price, round(prices[stock.ticker], 2)),
            )
            continue
        factor = 1.0
        if sector_modifier is not None:
            factor *= 1 + sector_modifier
        if company_modifier is not None:
            factor *= 1 + company_modifier
        shocked_prices[stock.ticker] = max(
            PRICE_FLOOR,
            min(
                PRICE_CEILING_MULT * stock.base_price,
                round(prices[stock.ticker] * factor, 2),
            ),
        )
    return shocked_prices