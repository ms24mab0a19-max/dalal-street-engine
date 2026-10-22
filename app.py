"""Dalal Street — an 80s/90s Bombay Stock Exchange floor simulator.

Run with: streamlit run app.py

The application has two tabs:
  Tab 1 — 📊 Live Market Board: projector-optimized, zero-scrolling view
  of all 10 stocks in a compact 5×2 grid with giant prices, movement
  badges (▲/▼), and inline sparklines.  Timeline shocks apply silently
  and automatically in the background when rounds advance.  Read-only.

  Tab 2 — 🔐 Pricing Desk Controls: restricted admin entry tab.  A password
  ("dalal1990") must be entered before the Order Slip form and "Compute
  Round" button are revealed.  Correct password unlocks the form; incorrect
  shows "Access Restricted to Pricing Desk".  RESET button available here.
"""

from __future__ import annotations

import html
import os
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from engine import compute_round, streak_multiplier
from market_data import Stock, load_stocks, load_timeline

st.set_page_config(
    page_title="Dalal Street | Bombay Exchange Floor",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #

try:
    STOCKS: tuple[Stock, ...] = load_stocks()
    TIMELINE = load_timeline(stocks=STOCKS)
except (OSError, ValueError) as error:
    st.error(f"Market data could not be loaded: {error}")
    st.stop()


# --------------------------------------------------------------------------- #
# Session state & initialisation – MUST happen before tabs reference market
# --------------------------------------------------------------------------- #

@dataclass(frozen=False, slots=True)
class Candle:
    round_number: int
    open_prices: dict[str, float]
    high_prices: dict[str, float]
    low_prices: dict[str, float]
    close_prices: dict[str, float]


@dataclass(frozen=False, slots=True)
class Market:
    prices: dict[str, float]
    previous_prices: dict[str, float]
    round_number: int
    streaks: dict[str, dict[str, int]]
    candles: list[Candle]
    input_epoch: int = 0


def new_market() -> Market:
    opening = {stock.ticker: stock.base_price for stock in STOCKS}
    return Market(
        prices=dict(opening),
        previous_prices=dict(opening),
        round_number=0,
        streaks={stock.ticker: {"direction": 0, "count": 0} for stock in STOCKS},
        candles=[],
    )


def _restart_simulation() -> None:
    st.session_state.market = new_market()
    st.session_state.flash = "Simulation reset to the opening board."
    st.session_state.pwd_correct = False


def money(value: float) -> str:
    return f"₹{value:,.2f}"


def change_text(change: float, percent: float) -> str:
    if change > 0:
        return f"+₹{change:,.2f} ({percent:+.2f}%)"
    if change < 0:
        return f"-₹{abs(change):,.2f} ({percent:+.2f}%)"
    return f"₹0.00 ({percent:+.2f}%)"


# Initialise market in session state before any tab references it
if "market" not in st.session_state:
    st.session_state.market = new_market()
market: Market = st.session_state.market


# --------------------------------------------------------------------------- #
# Password protection state
# --------------------------------------------------------------------------- #

# Read password from Streamlit secret or environment; fall back to default
_DEFAULT_PWD = "dalal1990"

# Safely check for secrets without crashing if secrets.toml is missing locally
try:
    _pwd_from_secrets = st.secrets.get("PricingDeskPassword", None)
except Exception:
    _pwd_from_secrets = None

PWD = _pwd_from_secrets or os.getenv("PRICING_DESK_PWD", _DEFAULT_PWD)


if "pwd_correct" not in st.session_state:
    st.session_state.pwd_correct = False


def check_password() -> bool:
    """Verify the entered admin password against the configured secret."""
    entered = st.session_state.get("entered_pwd", "")
    if entered == PWD:
        st.session_state.pwd_correct = True
        return True
    elif entered != "":
        st.session_state.pwd_correct = False
    return False


# --------------------------------------------------------------------------- #
# Sparkline SVG helper
# --------------------------------------------------------------------------- #


def sparkline_svg(ticker: str, values: list[float], color: str) -> str:
    """A lightweight inline SVG sparkline, sized to the card width."""

    width, height = 240.0, 44.0
    pad_x, pad_y = 2.0, 5.0
    if len(values) == 1:
        xs = [pad_x, width - pad_x]
        ys = [height / 2, height / 2]
    else:
        low, high = min(values), max(values)
        span = high - low
        step = (width - 2 * pad_x) / (len(values) - 1)
        xs = [pad_x + index * step for index in range(len(values))]
        if span == 0:
            ys = [height / 2] * len(values)
        else:
            ys = [
                pad_y + (high - value) / span * (height - 2 * pad_y)
                for value in values
            ]

    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = (
        f"{xs[0]:.1f},{height - pad_y:.1f} "
        f"{points} "
        f"{xs[-1]:.1f},{height - pad_y:.1f}"
    )
    gradient_id = f"spark-{ticker}"

    return (
        f'<svg class="sparkline" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'preserveAspectRatio="none" aria-hidden="true">'
        f"<defs>"
        f'<linearGradient id="{gradient_id}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{color}" stop-opacity="0.28"/>'
        f'<stop offset="100%" stop-color="{color}" stop-opacity="0"/>'
        f"</linearGradient>"
        f"</defs>"
        f'<polygon points="{area}" fill="url(#{gradient_id})"/>'
        f'<polyline points="{points}" fill="none" stroke="{color}" '
        f'stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" '
        f'vector-effect="non-scaling-stroke"/>'
        f'<line x1="{xs[-1]:.1f}" y1="{pad_y:.1f}" '
        f'x2="{xs[-1]:.1f}" y2="{height - pad_y:.1f}" '
        f'stroke="{color}" stroke-width="1.6" stroke-opacity="0.35" '
        f'vector-effect="non-scaling-stroke"/>'
        f'<circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="2.1" fill="{color}"/>'
        f"</svg>"
    )


# --------------------------------------------------------------------------- #
# Theme & CSS
# --------------------------------------------------------------------------- #

st.markdown(
    """
    <style>
    :root {
        color-scheme: dark;
        --bg: #0e1117;
        --panel: #151b24;
        --panel-raised: #1a212b;
        --line: #26303d;
        --text: #e6edf3;
        --muted: #93a1b0;
        --green: #3ddc84;
        --red: #ff6b6b;
        --gold: #f2c14e;
        --mono: ui-monospace, "SFMono-Regular", "Cascadia Mono", "Roboto Mono", Consolas, monospace;
    }
    html, body, .stApp, [data-testid="stAppViewContainer"] {
        background: var(--bg);
        color: var(--text);
    }
    [data-testid="stHeader"] { display: none; }
    [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
    [data-testid="stSidebarCollapseButton"] { display: none !important; }
    .block-container {
        max-width: 1900px;
        padding: 0.65rem 1.1rem 0.7rem;
    }
    .topbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
        min-height: 46px;
        margin-bottom: 0.55rem;
        padding-bottom: 0.45rem;
        border-bottom: 1px solid var(--line);
    }
    .brand-block { display: flex; align-items: baseline; gap: 0.75rem; flex-wrap: wrap; }
    .brand {
        color: var(--text);
        font-size: 1.42rem;
        font-weight: 800;
        line-height: 1;
        letter-spacing: 0.06em;
    }
    .brand-sub {
        color: var(--muted);
        font: 500 0.6rem var(--mono);
        letter-spacing: 0.16em;
        text-transform: uppercase;
    }
    .round-pill {
        display: flex;
        align-items: baseline;
        gap: 0.5rem;
        color: var(--gold);
        font: 600 0.7rem var(--mono);
        letter-spacing: 0.1em;
        white-space: nowrap;
    }
    .round-pill .round-number {
        font-size: 1.2rem;
        letter-spacing: 0.02em;
        color: #ffffff;
    }
    .round-pill .round-note {
        color: var(--muted);
        font-weight: 400;
        font-size: 0.6rem;
        letter-spacing: 0.05em;
    }

    /* ---- PROJECTOR DASHBOARD TAB (read-only) ---- */

    .board-grid {
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 9px;
    }
    .stock-card {
        display: flex;
        flex-direction: column;
        min-width: 0;
        height: 158px;
        padding: 9px 11px 7px;
        border: 1px solid var(--line);
        border-left: 3px solid var(--accent);
        border-radius: 8px;
        background: linear-gradient(150deg, var(--panel-raised) 0%, #11161e 100%);
        box-shadow: 0 6px 18px rgba(0, 0, 0, 0.2);
    }
    .card-top {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.4rem;
    }
    .ticker {
        color: var(--gold);
        font: 700 0.82rem var(--mono);
        letter-spacing: 0.12em;
    }
    .move-badge {
        flex: 0 0 auto;
        padding: 0.17rem 0.34rem;
        border-radius: 3px;
        font: 600 0.62rem var(--mono);
        white-space: nowrap;
    }
    .move-up { color: var(--green); background: #102c1f; }
    .move-down { color: var(--red); background: #331a1e; }
    .move-flat { color: #b7c2ce; background: #232c37; }
    .stock-name {
        margin-top: 0.2rem;
        color: var(--muted);
        font-size: 0.72rem;
        font-weight: 600;
        line-height: 1.25;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .card-price {
        margin: 0.02rem 0 0.1rem;
        color: #ffffff;
        font: 600 26px/1.2 var(--mono);
        letter-spacing: -0.03em;
        white-space: nowrap;
    }
    .spark-wrap {
        margin-top: auto;
        height: 44px;
        border-top: 1px solid #1f2731;
        padding-top: 2px;
    }
    .sparkline { display: block; width: 100%; height: 40px; }

    @media (max-width: 1500px) {
        .stock-card { height: 154px; padding: 8px 9px 6px; }
        .card-price { font-size: 24px; }
        .move-badge { font-size: 0.58rem; }
    }
    @media (max-width: 1150px) {
        .board-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    }
    @media (max-width: 760px) {
        .board-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .brand-sub { display: none; }
    }

    /* ---- PRICING DESK TAB ---- */

    .desk-head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 0.75rem;
        margin: 0.55rem 0 0.35rem;
    }
    .desk-title {
        color: var(--text);
        font: 700 0.78rem var(--mono);
        letter-spacing: 0.1em;
        text-transform: uppercase;
    }
    .desk-note {
        color: var(--muted);
        font: 400 0.62rem var(--mono);
        letter-spacing: 0.04em;
    }
    div[data-testid="stForm"] {
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 0.55rem 0.65rem 0.5rem;
        background: var(--panel);
    }
    .slip-cell { min-height: 1.5rem; }
    .slip-title {
        display: flex;
        align-items: baseline;
        gap: 0.35rem;
        min-width: 0;
    }
    .slip-title .ticker { font-size: 0.7rem; }
    .slip-name {
        color: var(--muted);
        font-size: 0.66rem;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .slip-price {
        margin-left: auto;
        color: var(--gold);
        font: 600 0.65rem var(--mono);
        white-space: nowrap;
    }
    div[data-testid="stForm"] label p {
        color: var(--muted);
        font-size: 0.55rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }
    div[data-testid="stForm"] div[data-baseweb="input"] input {
        font-family: var(--mono);
        font-size: 0.78rem;
    }
    div[data-testid="stFormSubmitButton"] button {
        min-height: 2.3rem;
        font-size: 0.74rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }
    .stButton > button {
        min-height: 2rem;
        padding: 0.2rem 0.7rem;
        font: 600 0.62rem var(--mono);
        letter-spacing: 0.08em;
    }
    .block-container [data-testid="stHorizontalBlock"] { gap: 0.45rem; }

    @media (max-width: 1500px) {
        .stock-card { height: 154px; padding: 8px 9px 6px; }
        .card-price { font-size: 24px; }
        .move-badge { font-size: 0.58rem; }
    }
    .pwd-box {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 1rem;
        margin: 1rem 0;
    }
    .access-denied {
        color: var(--red);
        font-weight: 600;
        font-size: 0.9rem;
        margin-top: 0.5rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# Helpers pulled from the original app
# --------------------------------------------------------------------------- #

flash_message = st.session_state.pop("flash", None)
if flash_message:
    st.toast(flash_message)


# --------------------------------------------------------------------------- #
# Tab 1 — 📊 Live Market Board (projector dashboard, read-only)
# --------------------------------------------------------------------------- #

tab_dashboard, tab_desk = st.tabs(["01 · 📊 Live Market Board", "02 · 🔐 Pricing Desk Controls"])

with tab_dashboard:
    # ------------------------------------------------------------------- #
    # Single-screen board: 5 columns x 2 rows — read only, no RESET button
    # ------------------------------------------------------------------- #
    market: Market = st.session_state.market

    cards: list[str] = []
    for stock in STOCKS:
        current = market.prices[stock.ticker]
        previous = market.previous_prices[stock.ticker]
        change = current - previous
        percent = (change / previous * 100) if previous else 0.0

        if change > 0:
            arrow, badge_class, accent = "▲", "move-up", "#3ddc84"
        elif change < 0:
            arrow, badge_class, accent = "▼", "move-down", "#ff6b6b"
        else:
            arrow, badge_class, accent = "•", "move-flat", "#5b6673"

        values = [stock.base_price] + [
            candle.close_prices[stock.ticker] for candle in market.candles
        ]
        sparkline = sparkline_svg(stock.ticker, values, accent)

        cards.append(
            f'<article class="stock-card" style="--accent:{accent}">'
            f'<div class="card-top">'
            f'<span class="ticker">{html.escape(stock.ticker)}</span>'
            f'<span class="move-badge {badge_class}">{arrow} '
            f"{change_text(change, percent)}</span>"
            f"</div>"
            f'<div class="stock-name">{html.escape(stock.name)}</div>'
            f'<div class="card-price">{money(current)}</div>'
            f'<div class="spark-wrap">{sparkline}</div>'
            f"</article>"
        )

    st.markdown(f'<div class="board-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Tab 2 — 🔐 Pricing Desk Controls (password-protected, with RESET)
# --------------------------------------------------------------------------- #

with tab_desk:
    next_round = market.round_number + 1

    # ---- Password challenge ----
    if not st.session_state.pwd_correct:
        st.markdown(
            f'<div class="pwd-box">'
            f'<label>Admin Password</label>'
            f'<input type="password" '
            f'placeholder="Enter admin password" '
            f'id="pwd_input" '
            f'style="width:100%;padding:0.5rem;font-size:1rem;border-radius:4px;border:1px solid var(--line);background:var(--panel);color:var(--text);"'
            f'/>'
            f"</div>",
            unsafe_allow_html=True,
        )
        # Consolidated password entry - single text_input widget
        entered_pwd = st.text_input(
            "Enter admin password to access Pricing Desk",
            value=st.session_state.get("entered_pwd", ""),
            key="entered_pwd",
            placeholder="Enter admin password",
        )
        if st.button("Unlock", help="Enter the admin password to access the Pricing Desk"):
            if entered_pwd == PWD:
                st.session_state.pwd_correct = True
                st.rerun()
            else:
                st.session_state.pwd_correct = False
                st.error("Access Restricted to Pricing Desk")
        st.markdown('<p class="access-denied">Access Restricted to Pricing Desk</p>', unsafe_allow_html=True)
        st.stop()

    # ---- Authenticated: show the Order Slip form + RESET ----
    # RESET button in the Pricing Desk tab only
    if st.button("RESET", help="Restart the simulation from the base prices in stocks.json"):
        _restart_simulation()
        st.rerun()

    st.markdown(
        f'<div class="desk-head">'
        f'<span class="desk-title">PRICING DESK · ORDER SLIP</span>'
        f'<span class="desk-note">Round {next_round} · buy / sell volumes</span>'
        f"</div>",
        unsafe_allow_html=True,
    )

    order_volumes: dict[str, tuple[int, int]] = {}
    with st.form("order_slip", clear_on_submit=False):
        for row_start in range(0, len(STOCKS), 5):
            form_columns = st.columns(5, gap="small")
            for column, stock in zip(form_columns, STOCKS[row_start : row_start + 5]):
                with column:
                    st.markdown(
                        f'<div class="slip-cell">'
                        f'<div class="slip-title">'
                        f'<span class="ticker">{html.escape(stock.ticker)}</span>'
                        f'<span class="slip-name">{html.escape(stock.name)}</span>'
                        f'<span class="slip-price">{money(market.prices[stock.ticker])}</span>'
                        f"</div></div>",
                        unsafe_allow_html=True,
                    )
                    buy_col, sell_col = st.columns(2, gap="small")
                    with buy_col:
                        buy_volume = st.number_input(
                            "Buy",
                            min_value=0,
                            max_value=10_000_000,
                            value=0,
                            step=100,
                            key=f"buy_{stock.ticker}_{market.input_epoch}",
                            help=f"Buy volume for {stock.name}",
                        )
                    with sell_col:
                        sell_volume = st.number_input(
                            "Sell",
                            min_value=0,
                            max_value=10_000_000,
                            value=0,
                            step=100,
                            key=f"sell_{stock.ticker}_{market.input_epoch}",
                            help=f"Sell volume for {stock.name}",
                        )
                    order_volumes[stock.ticker] = (int(buy_volume), int(sell_volume))

        submitted = st.form_submit_button(
            f"COMPUTE ROUND {next_round}",
            type="primary",
            width="stretch",
        )

    if submitted:
        result = compute_round(
            STOCKS,
            market.prices,
            market.streaks,
            order_volumes,
            round_number=next_round,
            timeline=TIMELINE,
        )
        market.previous_prices = dict(market.prices)  # now OK: frozen=False
        market.prices = dict(result.prices)
        market.round_number = next_round
        market.streaks = result.streaks
        market.candles.append(
            Candle(
                round_number=next_round,
                open_prices=result.open_prices,
                high_prices=result.high_prices,
                low_prices=result.low_prices,
                close_prices=result.prices,
            )
        )
        market.input_epoch += 1
        st.session_state.flash = f"Round {next_round} computed."
        st.session_state.pwd_correct = True  # keep unlocked after compute
        st.rerun()