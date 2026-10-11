import html
import json
import math
import random
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


st.set_page_config(
    page_title="Dalal Street | Exchange Floor",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


ROOT = Path(__file__).resolve().parent
ALPHA = 0.08
GAMMA = 0.002
BETA = 0.25
NOISE_LIMIT = 0.007

def load_stocks(path=ROOT / "stocks.json"):
    with Path(path).open(encoding="utf-8") as stock_file:
        stocks = json.load(stock_file)
    if not isinstance(stocks, list) or not stocks:
        raise ValueError("stocks.json must contain a non-empty list of stocks.")
    required_fields = {"id", "name", "sector", "base_price"}
    identifiers = set()
    for stock in stocks:
        if not isinstance(stock, dict) or not required_fields.issubset(stock):
            raise ValueError("Each stock must define id, name, sector, and base_price.")
        if stock["id"] in identifiers:
            raise ValueError(f"Duplicate stock id: {stock['id']}")
        if not isinstance(stock["base_price"], (int, float)) or stock["base_price"] <= 0:
            raise ValueError(f"Stock {stock['id']} must have a positive base_price.")
        identifiers.add(stock["id"])
    return [{**stock, "symbol": stock["id"], "price": float(stock["base_price"])} for stock in stocks]


def load_shocks(path=ROOT / "shocks.json", sectors=None):
    with Path(path).open(encoding="utf-8") as shock_file:
        shocks = json.load(shock_file)
    if not isinstance(shocks, list):
        raise ValueError("shocks.json must contain a list of shock events.")
    known_sectors = set(sectors or ())
    for shock in shocks:
        required_fields = {"id", "name", "description", "sector_modifiers"}
        if not isinstance(shock, dict) or not required_fields.issubset(shock):
            raise ValueError("Each shock must define id, name, description, and sector_modifiers.")
        if not isinstance(shock["sector_modifiers"], dict):
            raise ValueError(f"Shock {shock['id']} must map sectors to percentage modifiers.")
        for sector, modifier in shock["sector_modifiers"].items():
            if known_sectors and sector not in known_sectors:
                raise ValueError(f"Shock {shock['id']} references unknown sector {sector}.")
            if not isinstance(modifier, (int, float)) or modifier <= -1:
                raise ValueError(f"Shock {shock['id']} has an invalid modifier for {sector}.")
    return shocks


try:
    STOCKS = load_stocks()
    SECTORS = sorted({stock["sector"] for stock in STOCKS})
    SHOCKS = load_shocks(sectors=SECTORS)
except (OSError, json.JSONDecodeError, ValueError) as error:
    st.error(f"Market data could not be loaded: {error}")
    st.stop()


def streak_multiplier(streak):
    if streak >= 3:
        return 1.75
    if streak == 2:
        return 1.35
    return 1.0


def calculate_round(stocks, prices, streaks, volumes):
    base_changes = {}
    next_streaks = {}
    for stock in stocks:
        stock_id = stock["id"]
        buy_volume, sell_volume = volumes[stock_id]
        net_demand = buy_volume - sell_volume
        direction = (net_demand > 0) - (net_demand < 0)
        previous_streak = streaks[stock_id]
        count = previous_streak["count"] + 1 if direction and direction == previous_streak["direction"] else (1 if direction else 0)
        trade_change = direction * ALPHA * (1 - math.exp(-GAMMA * abs(net_demand))) * streak_multiplier(count)
        base_changes[stock_id] = trade_change + random.uniform(-NOISE_LIMIT, NOISE_LIMIT)
        next_streaks[stock_id] = {"direction": direction, "count": count}

    next_prices = {}
    for stock in stocks:
        stock_id = stock["id"]
        peer_changes = [
            base_changes[peer["id"]]
            for peer in stocks
            if peer["sector"] == stock["sector"] and peer["id"] != stock_id
        ]
        sector_change = BETA * (sum(peer_changes) / len(peer_changes)) if peer_changes else 0.0
        next_prices[stock_id] = max(1.0, round(prices[stock_id] * (1 + base_changes[stock_id] + sector_change), 2))
    return next_prices, next_streaks


def _new_session():
    prices = {stock["symbol"]: stock["price"] for stock in STOCKS}
    return {
        "prices": prices,
        "previous_prices": prices.copy(),
        "round_number": 0,
        "event_number": 0,
        "streaks": {stock["symbol"]: {"direction": 0, "count": 0} for stock in STOCKS},
        "history": [{"event": 0, "label": "Opening board", **prices}],
        "last_movements": {
            stock["symbol"]: {"previous": stock["price"], "current": stock["price"]}
            for stock in STOCKS
        },
        "phase": "Order entry",
        "input_epoch": 0,
    }


if "market" not in st.session_state:
    st.session_state.market = _new_session()

market = st.session_state.market


st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;500;600;700;800&display=swap');
    :root {
        color-scheme: dark;
        --bg: #0e1117;
        --panel: #161b22;
        --line: #303944;
        --text: #e6edf3;
        --muted: #9aa7b5;
        --green: #3ddc84;
        --red: #ff6b6b;
        --gold: #f2c14e;
    }
    html, body, [class*="css"] { font-family: 'Manrope', sans-serif; }
    .stApp { background:var(--bg); color:var(--text); }
    [data-testid="stSidebar"] { background:#11161e; border-right:1px solid var(--line); }
    .block-container { max-width:1600px; padding-top:1.4rem; padding-bottom:2rem; }
    .masthead { display:flex; align-items:flex-end; justify-content:space-between; gap:1rem; border-bottom:1px solid var(--line); padding-bottom:1rem; margin-bottom:1.1rem; }
    .masthead h1 { font-size:2rem; line-height:1; margin:0; font-weight:800; color:var(--text); }
    .masthead p { margin:.45rem 0 0; color:var(--muted); font-size:.8rem; }
    .exchange-mark { color:var(--gold); font:500 .72rem 'DM Mono',monospace; line-height:1.6; text-align:right; }
    .section-label { color:var(--muted); font:500 .7rem 'DM Mono',monospace; text-transform:uppercase; }
    div[data-testid="stMetric"] { background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:.75rem .9rem; }
    div[data-testid="stMetricLabel"] { color:var(--muted); }
    div[data-testid="stMetricValue"] { color:var(--text); font-family:'DM Mono',monospace; }
    .stTabs [data-baseweb="tab-list"] { border-bottom:1px solid var(--line); gap:1rem; }
    .stTabs [data-baseweb="tab"] { height:3.1rem; color:var(--muted); }
    .stTabs [aria-selected="true"] { color:var(--gold); }
    .stock-card { min-height:172px; padding:1.1rem 1.25rem; margin:0 0 1rem; border:1px solid var(--line); border-left:4px solid var(--accent); border-radius:7px; background:linear-gradient(145deg,#1b222c,#141920); display:flex; flex-direction:column; justify-content:space-between; }
    .card-top { display:flex; justify-content:space-between; gap:.7rem; }
    .card-name { color:var(--text); font-size:1rem; font-weight:700; line-height:1.3; }
    .card-sector { color:var(--muted); margin-top:.25rem; font:400 .7rem 'DM Mono',monospace; }
    .card-price { color:var(--text); margin:.45rem 0; font:500 38px 'DM Mono',monospace; line-height:1.2; white-space:nowrap; }
    .card-bottom { display:flex; align-items:center; justify-content:space-between; gap:.5rem; flex-wrap:wrap; }
    .move-badge { padding:.32rem .55rem; border-radius:4px; font:500 .78rem 'DM Mono',monospace; white-space:nowrap; }
    .move-up { color:var(--green); background:#123323; }
    .move-down { color:var(--red); background:#3a1d22; }
    .move-flat { color:#c0cad4; background:#252d38; }
    .streak-badge,.price-input-caption { color:var(--muted); font:400 .68rem 'DM Mono',monospace; }
    div[data-testid="stForm"] { border:0; padding:0; }
    .mono, code { font-family:'DM Mono',monospace !important; }
    @media (max-width: 700px) {
        .masthead { align-items:flex-start; flex-direction:column; }
        .exchange-mark { text-align:left; }
        .masthead h1 { font-size:1.65rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _apply_shock(shock):
    previous_prices = market["prices"].copy()
    new_prices = previous_prices.copy()
    for stock in STOCKS:
        modifier = shock["sector_modifiers"].get(stock["sector"])
        if modifier is not None:
            stock_id = stock["id"]
            new_prices[stock_id] = max(1.0, round(previous_prices[stock_id] * (1 + modifier), 2))
    market["prices"] = new_prices
    market["last_movements"] = {
        stock["symbol"]: {"previous": previous_prices[stock["symbol"]], "current": new_prices[stock["symbol"]]}
        for stock in STOCKS
    }
    market["event_number"] += 1
    market["history"].append({"event": market["event_number"], "label": shock["name"], **new_prices})
    market["phase"] = f"News · {shock['name']}"


with st.sidebar:
    st.markdown("### DALAL STREET")
    st.caption("BOMBAY · EXCHANGE FLOOR")
    st.divider()
    st.metric("COMPLETED ROUNDS", market["round_number"])
    st.markdown(f"**PHASE**  \n{market['phase']}")
    st.markdown(f"**NEXT SLIP**  \nRound {market['round_number'] + 1}")
    st.divider()
    st.markdown("#### Breaking News")
    shocks_by_option = {f"{shock['name']} ({shock['id']})": shock for shock in SHOCKS}
    selected_shock_option = st.selectbox(
        "Scheduled shock",
        ["Select a news event"] + list(shocks_by_option),
        label_visibility="collapsed",
    )
    if selected_shock_option != "Select a news event":
        st.caption(shocks_by_option[selected_shock_option]["description"])
    shock_clicked = st.button(
        "Apply market shock",
        type="secondary",
        width="stretch",
        disabled=selected_shock_option == "Select a news event",
    )
    if shock_clicked and selected_shock_option != "Select a news event":
        _apply_shock(shocks_by_option[selected_shock_option])
        st.rerun()

    st.divider()
    if st.button("Restart simulation", width="stretch", help="Reset prices, streaks, and history"):
        st.session_state.market = _new_session()
        st.rerun()


st.markdown(
    """
    <div class="masthead">
            <div><h1>DALAL STREET</h1><p>THE BOMBAY EXCHANGE FLOOR · 80s / 90s MARKET SIMULATION</p></div>
            <div class="exchange-mark">BSE · MANUALLY RUN MARKET<br>PRICING DESK → BLACKBOARD</div>
    </div>
    """,
    unsafe_allow_html=True,
)

latest_movement = sum(
    movement["current"] - movement["previous"]
    for movement in market["last_movements"].values()
)
status_col, movement_col, listings_col = st.columns(3)
status_col.metric("BOARD STATUS", "OPEN", delta=market["phase"])
movement_col.metric("LAST BOARD MOVE", f"₹{latest_movement:+,.2f}", delta="Net across 10 listings")
listings_col.metric("LISTED COMPANIES", "10", delta="4 sectors")

board_tab, entry_tab, history_tab = st.tabs(
    ["01  Blackboard · Writer View", "02  Order Slip Entry", "03  Price History"]
)

with entry_tab:
    st.markdown("#### Pricing Desk")
    st.caption(
        f"Round {market['round_number'] + 1} · Enter buy and sell volumes for each listing. "
        "The Pricing Desk controls when each round is computed."
    )
    with st.form("order_slip", clear_on_submit=False):
        company_header, buy_header, sell_header = st.columns([3.8, 1, 1])
        company_header.markdown('<div class="section-label">Company / sector</div>', unsafe_allow_html=True)
        buy_header.markdown('<div class="section-label">Buy volume</div>', unsafe_allow_html=True)
        sell_header.markdown('<div class="section-label">Sell volume</div>', unsafe_allow_html=True)
        st.markdown("---")
        order_volumes = {}
        for stock in STOCKS:
            symbol = stock["symbol"]
            company_col, buy_col, sell_col = st.columns([3.8, 1, 1])
            with company_col:
                st.markdown(
                    f'<div class="stock-name">{stock["name"]}</div><div class="stock-meta">{stock["symbol"]} · {stock["sector"]} · ₹{market["prices"][symbol]:,.2f}</div>',
                    unsafe_allow_html=True,
                )
            with buy_col:
                buy_volume = st.number_input(
                    "Buy volume",
                    min_value=0,
                    max_value=1_000_000_000,
                    step=100,
                    value=0,
                    key=f"buy_{symbol}_{market['input_epoch']}",
                    label_visibility="collapsed",
                    help=f"{stock['name']} buy volume",
                )
            with sell_col:
                sell_volume = st.number_input(
                    "Sell volume",
                    min_value=0,
                    max_value=1_000_000_000,
                    step=100,
                    value=0,
                    key=f"sell_{symbol}_{market['input_epoch']}",
                    label_visibility="collapsed",
                    help=f"{stock['name']} sell volume",
                )
            order_volumes[symbol] = (int(buy_volume), int(sell_volume))
            st.markdown("---")
        compute_clicked = st.form_submit_button(
            "Compute Round",
            type="primary",
            width="stretch",
        )

    if compute_clicked:
        previous_prices = market["prices"].copy()
        new_prices, next_streaks = calculate_round(STOCKS, previous_prices, market["streaks"], order_volumes)
        market["round_number"] += 1
        market["event_number"] += 1
        market["prices"] = new_prices
        market["streaks"] = next_streaks
        market["last_movements"] = {
            stock["symbol"]: {"previous": previous_prices[stock["symbol"]], "current": new_prices[stock["symbol"]]}
            for stock in STOCKS
        }
        market["history"].append({"event": market["event_number"], "label": f"Round {market['round_number']}", **new_prices})
        market["phase"] = f"Round {market['round_number']} complete"
        market["input_epoch"] += 1
        st.rerun()

with board_tab:
    st.markdown("#### Current Board")
    st.caption(f"Round {market['round_number']} · {market['phase']} · All prices in ₹ INR")
    board_columns = st.columns(2, gap="medium")
    for index, stock in enumerate(STOCKS):
        stock_id = stock["id"]
        movement = market["last_movements"][stock_id]
        previous = movement["previous"]
        current = movement["current"]
        change = current - previous
        percent_change = (change / previous * 100) if previous else 0.0
        if change > 0:
            arrow, badge_class, accent = "▲", "move-up", "#3ddc84"
        elif change < 0:
            arrow, badge_class, accent = "▼", "move-down", "#ff6b6b"
        else:
            arrow, badge_class, accent = "—", "move-flat", "#687482"
        streak = market["streaks"][stock_id]
        streak_text = (
            f"{'BUY' if streak['direction'] > 0 else 'SELL'} STREAK · {streak['count']}"
            if streak["count"]
            else "NO ACTIVE STREAK"
        )
        card = f"""
        <article class="stock-card" style="--accent:{accent}">
          <div class="card-top">
            <div><div class="card-name">{html.escape(stock['name'])}</div><div class="card-sector">{html.escape(stock['sector'])} · {html.escape(stock_id)}</div></div>
          </div>
          <div class="card-price">₹{current:,.2f}</div>
          <div class="card-bottom">
            <span class="move-badge {badge_class}">{arrow} ₹{change:+,.2f} ({percent_change:+.2f}%)</span>
            <span class="streak-badge">{streak_text}</span>
          </div>
        </article>
        """
        with board_columns[index % 2]:
            st.markdown(card, unsafe_allow_html=True)

with history_tab:
    st.markdown("#### Market Trajectory · Sector Candlesticks")
    st.caption(
        "Choose a listing within each sector. Each candle spans one round or news event; "
        "open is the previous board price and close is the new board price."
    )
    sector_tabs = st.tabs(SECTORS)
    for sector_tab, sector in zip(sector_tabs, SECTORS):
        sector_stocks = [stock for stock in STOCKS if stock["sector"] == sector]
        with sector_tab:
            stock_by_option = {
                f"{stock['name']} ({stock['id']})": stock for stock in sector_stocks
            }
            selected_stock_option = st.selectbox(
                "Company",
                list(stock_by_option),
                key=f"history_stock_{sector}",
            )
            selected_stock = stock_by_option[selected_stock_option]
            selected_stock_id = selected_stock["id"]
            events = market["history"]
            closes = [snapshot[selected_stock_id] for snapshot in events]
            opens = [closes[0], *closes[:-1]]
            candle = go.Figure(
                data=[
                    go.Candlestick(
                        x=[snapshot["event"] for snapshot in events],
                        open=opens,
                        high=[max(open_price, close_price) for open_price, close_price in zip(opens, closes)],
                        low=[min(open_price, close_price) for open_price, close_price in zip(opens, closes)],
                        close=closes,
                        name=selected_stock["name"],
                        increasing_line_color="#3ddc84",
                        decreasing_line_color="#ff6b6b",
                        customdata=[snapshot["label"] for snapshot in events],
                        hovertemplate=(
                            "%{customdata}<br>Open: ₹%{open:.2f}<br>High: ₹%{high:.2f}"
                            "<br>Low: ₹%{low:.2f}<br>Close: ₹%{close:.2f}<extra></extra>"
                        ),
                    )
                ]
            )
            candle.update_layout(
                template="plotly_dark",
                height=450,
                margin={"l": 20, "r": 20, "t": 24, "b": 20},
                paper_bgcolor="#0e1117",
                plot_bgcolor="#0e1117",
                font={"color": "#e6edf3"},
                xaxis={
                    "title": "Round / news event",
                    "showgrid": False,
                    "rangeslider": {"visible": False},
                    "dtick": 1,
                },
                yaxis={
                    "title": "Board price (₹)",
                    "gridcolor": "#303944",
                    "tickprefix": "₹",
                    "fixedrange": False,
                },
                showlegend=False,
            )
            st.plotly_chart(candle, width="stretch", config={"displayModeBar": False})

    with st.expander("Event log"):
        event_rows = [
            {"Event": item["event"], "Update": item["label"]}
            for item in reversed(market["history"])
        ]
        st.dataframe(pd.DataFrame(event_rows), hide_index=True, width="stretch")