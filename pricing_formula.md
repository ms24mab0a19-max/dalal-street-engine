# Dalal Street — Pricing Engine

This document describes exactly how the exchange prices a round. The
implementation is in `engine.py`; company data is in `stocks.json` and the
automated shock schedule is in `timeline.json`.

All prices are in Indian rupees (₹). Percentages are decimals inside the
engine: `0.08` means **8%** and `-0.15` means **-15%**.

## Constants

| Symbol | Value | Meaning |
| --- | --- | --- |
| α (alpha) | `0.08` | Maximum single-round trade impact |
| γ (gamma) | `0.002` | Volume saturation rate |
| β (beta) | `0.25` | Sector contagion weight |
| noise limit | `0.007` | Ambient jitter of ±0.7% |
| floor | `1.00` | Lowest permitted board price |
| magnitude cap | `1,000,000,000` | Numerical-safety cap on `|N|` |

## 1. Net demand

For each company *i*:

$$
N_i = B_i - S_i
$$

where $B_i$ is the total buy volume on the order slip and $S_i$ is the total
sell volume. Net demand is a whole number and may be zero.

The demand direction is:

$$
d_i = \operatorname{sign}(N_i) \in \{-1, 0, +1\}
$$

## 2. Streak multiplier

A streak counts **consecutive rounds with the same non-zero direction**:

- A buy round after a buy round increments the buy streak.
- A sell round after a sell round increments the sell streak.
- A reversal starts a new streak at 1.
- A neutral round ($N_i = 0$) resets the streak to 0.

The streak used in a round is the updated streak after that round's direction
is counted. The multiplier is:

$$
M_i =
\begin{cases}
1.75 & \text{if streak}_i \ge 3 \\
1.35 & \text{if streak}_i = 2 \\
1.00 & \text{otherwise}
\end{cases}
$$

Streak state is independent per company. Scheduled shocks never change streaks.

## 3. Diminishing trade impact

Trade impact grows with volume but saturates, so doubling an already large
order does not double the price move:

$$
\Delta_{\text{trade},i}
= d_i \cdot \alpha \cdot \left(1 - e^{-\gamma |N_i|}\right) \cdot M_i
$$

With $\alpha = 0.08$ and $\gamma = 0.002$:

| Net demand | $1 - e^{-0.002|N|}$ | Impact at $M=1$ |
| ---: | ---: | ---: |
| 100 | 0.181 | 1.45% |
| 500 | 0.632 | 5.06% |
| 1,500 | 0.950 | 7.60% |
| ∞ | 1.000 | 8.00% |

A long streak raises the ceiling: 10.8% at streak 2 and 14.0% at streak 3 or
more. Net-demand magnitude is capped at $10^9$ for numerical safety; the
exponential is already fully saturated far below that, so the cap does not
change any realistic result.

## 4. Ambient noise

Each company receives an independent uniform jitter:

$$
\epsilon_i \sim \operatorname{Uniform}(-0.007,\ +0.007)
$$

The preliminary move combines trade impact and noise:

$$
r_i = \Delta_{\text{trade},i} + \epsilon_i
$$

Noise prevents the board from looking mechanically deterministic between
rounds.

## 5. Sector contagion

Every company is pulled toward the average preliminary move of its
**same-sector peers**:

$$
\Delta_{\text{sector},i}
= \beta \cdot \operatorname{mean}\left(\{r_j : j \ne i,\ \text{sector}_j = \text{sector}_i\}\right)
$$

with $\beta = 0.25$.

- The peer average uses $r_j$, which already includes noise.
- A company never contributes to its own contagion.
- A company with no same-sector peer receives zero contagion. In the current
  listing, only Auto and Pharma have peers.

## 6. Trade close and price floor

All companies are priced from the **same opening board**. A price updated
earlier in the loop is never used as an input for another company in the same
round.

$$
r_i^{\text{total}} = r_i + \Delta_{\text{sector},i}
$$

$$
P_{i,\text{trade}}
= \max\left(1.00,\ \operatorname{round}\left(P_{i,\text{open}} \cdot (1 + r_i^{\text{total}}),\ 2\right)\right)
$$

Prices are rounded to two decimals. The ₹1.00 floor is applied after rounding,
so no listing can ever reach zero or a negative price.

## 7. Automatic scheduled shocks

`timeline.json` maps a shock to a round. When **Compute Round** prices round
*n*, the engine looks up the shock whose `round` equals *n* and applies it
automatically after the trade close.

For each affected company:

$$
P_{i,\text{close}}
= \max\left(1.00,\ \operatorname{round}\left(P_{i,\text{trade}} \cdot (1 + m_i),\ 2\right)\right)
$$

where $m_i$ is the company modifier from `timeline.json`. Sector modifiers use
the same rule. If a shock defines both a sector and a company modifier, the
factors multiply:

$$
P_{i,\text{close}}
= \max\left(1.00,\ \operatorname{round}\left(P_{i,\text{trade}} \cdot (1 + m_{\text{sector}}) \cdot (1 + m_{\text{company}}),\ 2\right)\right)
$$

The resulting close becomes the **live baseline**:

- It is written into the board state immediately.
- The next round reads it as $P_{i,\text{open}}$, so trade impact, contagion, and
  noise all compound from the shocked level.
- Nothing wears off in later rounds. The shock is permanent unless the
  organizer restarts the simulation.
- A shock fires exactly once, on its scheduled round. Missing the round in the
  UI is impossible because the check happens inside `compute_round`.
- A shock does not advance the round counter separately and does not change
  streaks.
- Unaffected companies keep their trade close unchanged.

### Worked examples

With zero order flow and zero noise, only the timeline acts. Starting from the
base prices:

| Company | Base | Round 1 shock | New baseline |
| --- | ---: | ---: | ---: |
| Bharat Motors (BHMT) | ₹218.50 | +12% | ₹244.72 |
| Vahan Auto Parts (VAHN) | ₹92.75 | +8% | ₹100.17 |
| Meridian IT Services (MRDN) | ₹264.50 | +8% | ₹285.66 |
| Aravali Pharmaceuticals (ARVL) | ₹402.00 | -15% | ₹341.70 |

Konark Petrochemicals shows how two scheduled shocks compound on the live
price, not on the original base:

| Event | Calculation | Price |
| --- | --- | ---: |
| Base | — | ₹256.00 |
| Round 3 Gulf War shock | ₹256.00 × 1.25 | ₹320.00 |
| Round 4 peace/oil collapse | ₹320.00 × 0.70 | ₹224.00 |
| Round 5 with no scheduled shock | unchanged | ₹224.00 |

The Round 4 close is 12.5% below the original base because -30% was applied to
the already-shocked ₹320.00 level. The Round 5 value proves the shock does not
decay back toward ₹256.00.

In a live round, trade impact happens first. For example, if Bharat Motors
trades to ₹235.00 before its Round 1 shock, the close is:

$$
\operatorname{round}(₹235.00 \times 1.12, 2) = ₹263.20
$$

## 8. OHLC candles

The simulation does not collect intraround ticks, so candles are built from the
actual computed stages rather than invented data:

- **Open** = previous board close.
- **Trade close** = price after trade impact, noise, and sector contagion.
- **Close** = trade close after the scheduled shock, or the trade close when no
  shock is scheduled.
- **High** = maximum of open, trade close, and close.
- **Low** = minimum of open, trade close, and close.

This means a shock that reverses the trade move produces a real wick. If a
company opens at ₹100, trades up to ₹110, and then takes a -30% shock, its
candle is open ₹100, high ₹110, low ₹77.00, close ₹77.00.

Each completed round appends one OHLC record per company. The projector board
renders each company's close history as an inline sparkline; the full OHLC
record remains in the app state. Scheduled shocks are not surfaced in the UI.

## 9. Round sequence

For every **Compute Round** submission:

1. Read buy and sell volumes for all companies.
2. Compute net demand, direction, and updated streaks.
3. Compute $\Delta_{\text{trade},i}$ for each company.
4. Add independent ambient noise to produce $r_i$.
5. Compute each company's sector contagion from peer $r_j$ values.
6. Apply the total change to the opening price, round to 2 decimals, and enforce
   the ₹1.00 floor. This is the trade close.
7. Look up the shock for this round in `timeline.json`; if present, apply it to
   the trade close and re-apply the floor. This is the final close.
8. Commit the new board, append OHLC candles, and advance the round counter.

## 10. Manual rounds, automatic shocks

The application has **no timers and no auto-advance**. The organizing team
decides when a round closes, when the order slip is submitted, and when to
restart. The only automated part is the shock schedule: it is keyed to the
round number, so computing Round 3 always triggers the Gulf War shock exactly
once.
