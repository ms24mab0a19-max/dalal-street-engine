# Dalal Street

An 80s/90s Bombay Stock Exchange simulation for **E-Club, NIT Warangal**. The
floor is driven manually by the organizing team: no timers and no
auto-advancing rounds. Scheduled shocks fire silently inside the engine from
`timeline.json`.

## Run

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
streamlit run app.py
```

The dark theme lives in `.streamlit/config.toml`, so Streamlit widgets share the
`#0e1117` background.

## Single-screen layout

There are no tabs and no sidebar. The app opens directly to one
projector-optimized screen. Ten compact cards form a 5-column × 2-row grid; each
shows the ticker, company name, a 26px price, a ▲/▼ badge with the exact rupee
and percentage move, and an inline SVG sparkline built from the base price and
every completed round close. The full board and order slip fit a 1920×1080
viewport without scrolling.

Below the board is the batch-auction order slip. Buy and sell volumes are laid
out in the same 5-column × 2-row grid. **Compute Round** applies trade impact,
noise, sector contagion, and any timeline shock, then refreshes the board and
sparklines immediately. Shocks are never shown in the UI; they apply silently in
the engine.

The **RESET** button in the header clears prices, streaks, and every candle and
reopens at the base prices in `stocks.json`.

## Files

| File | Purpose |
| --- | --- |
| `stocks.json` | The 10 listed companies: ticker, name, sector, base price |
| `timeline.json` | Round-indexed shocks with company/sector modifiers |
| `pricing_formula.md` | Full mathematical engine, shock compounding, and OHLC rules |
| `market_data.py` | Validated loaders for both JSON files |
| `engine.py` | Pure pricing engine, automatic timeline lookup, OHLC output |
| `app.py` | Single-screen Streamlit board and batch-auction order slip |
| `tests/test_engine.py` | 300+ Monte Carlo and invariant checks with PNG output |
| `requirements-dev.txt` | Pytest and matplotlib for the stress suite |

## Automated stress suite

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

The suite runs 4 market regimes × 25 random seeds × 20 rounds (2,000 priced
rounds) and checks every company every round for:

- prices never below the ₹1.00 floor and never non-finite;
- valid OHLC candles (`high >= open/close/trade`, `low` below all of them);
- scheduled shocks landing on exactly Rounds 1–4 with the correct modifiers;
- cumulative shock persistence across later rounds;
- streak multipliers at 1.0/1.35/1.75 and the 14% trade-impact ceiling;
- pathological 40-digit volumes without overflow.

The suite also writes high-resolution dark-mode trajectory plots to
`tests/output_plots/`:

- `extreme_bullish_trajectories.png`
- `extreme_bearish_trajectories.png`
- `volatile_trajectories.png`
- `random_trajectories.png`

Each PNG contains one panel per company, all 25 Monte Carlo paths, the median
path, and gold bands over the scheduled shock rounds. The plots are regenerated
on every test run.

## Market data

`stocks.json` entries require `ticker`, `name`, `sector`, and a `base_price` of
at least ₹1.00.

`timeline.json` entries require `id`, `round`, `name`, `description`, plus at
least one of `company_modifiers` (keyed by ticker) or `sector_modifiers` (keyed
by sector). Modifiers are decimals: `0.18` is +18% and `-0.14` is -14%. Rounds
must be unique.

Both files are validated at startup. Invalid tickers, sectors, duplicate IDs,
duplicate rounds, or modifiers of `-1` or lower stop the app with a readable
error instead of silently corrupting the market.

## Shock semantics

A shock is applied to the round's **trade close** and becomes the next round's
opening baseline. It is cumulative and permanent: Konark's Round 3 +25% is
followed by a Round 4 -30% on the already-raised price, and no later round
drifts back toward the pre-shock level. See `pricing_formula.md` for the exact
worked numbers.
