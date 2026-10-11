# Dalal Street

A manually operated 80s/90s Bombay Stock Exchange simulation with a writer-facing blackboard and a live price-history chart.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

## Market Data

- `stocks.json` defines the listings with `id`, `name`, `sector`, and `base_price` fields.
- `shocks.json` defines news events and decimal sector modifiers. For example, `0.15` is a 15% increase and `-0.10` is a 10% decrease.
- `pricing_formula.md` documents the round calculation and shock behavior.

The organizing team controls round timing and progression. Submit an order slip with **Compute Round** whenever a round is complete. Scheduled shocks apply immediately and do not advance the round counter; their price changes persist as the baseline for every subsequent round. Market state is kept in the active Streamlit session and can be reset with **Restart simulation**.

Price history is split into sector tabs with one candlestick chart per selected company. Each candle uses the previous event's closing price as its open and the new event price as its close; high and low span those two prices because the simulation does not collect intraround ticks.