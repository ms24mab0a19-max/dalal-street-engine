# Dalal Street Pricing Engine

All prices are denominated in Indian rupees. A round calculates all stock movements from the same opening board, then commits the resulting prices together. Percentage changes are decimals during calculation (for example, `0.01` means `+1%`).

## Net Demand

For stock $i$ in a round:

$$
N_i = B_i - S_i
$$

where $B_i$ is the submitted buy volume and $S_i$ is the submitted sell volume. The demand direction is $d_i = \operatorname{sign}(N_i)$.

## Streak Multiplier

A streak counts consecutive rounds with the same non-zero demand direction. A neutral round resets the streak; a reversal starts a new streak at one.

$$
M_i =
\begin{cases}
1.75 & \text{if streak}_i \ge 3 \\
1.35 & \text{if streak}_i = 2 \\
1.00 & \text{otherwise}
\end{cases}
$$

## Diminishing Trade Impact

Trade impact saturates as volume grows:

$$
\Delta_{\text{trade},i} = d_i \cdot \alpha \cdot \left(1 - e^{-\gamma |N_i|}\right) \cdot M_i
$$

with $\alpha = 0.08$ and $\gamma = 0.002$.

## Ambient Noise

Each stock receives an independent uniform percentage jitter:

$$
\epsilon_i \sim \operatorname{Uniform}(-0.007, +0.007)
$$

The preliminary percentage move is $r_i = \Delta_{\text{trade},i} + \epsilon_i$.

## Sector Contagion

Peer movement is the arithmetic mean of preliminary percentage moves for the other stocks in the same sector:

$$
\Delta_{\text{sector},i} = \beta \cdot \operatorname{mean}\left(r_j : j \ne i,\; sector_j = sector_i\right)
$$

with $\beta = 0.25$. A stock with no same-sector peers receives zero contagion.

## Price Update and Floor

All stocks use the same opening board for the round. Prices are rounded to two decimal places and floored at ₹1.00:

$$
P_{i,\text{new}} = \max\left(1.00,\; \operatorname{round}\left(P_{i,\text{old}} \cdot \left(1 + r_i + \Delta_{\text{sector},i}\right), 2\right)\right)
$$

## Cumulative Breaking News Shocks

Applying a scheduled shock immediately multiplies each affected sector's current prices by $1 + m$, where $m$ is the sector modifier in `shocks.json`:

$$
P_{i,\text{shocked}} = \max\left(1.00,\; \operatorname{round}\left(P_{i,\text{current}} \cdot (1 + m), 2\right)\right)
$$

The shocked value replaces the active price for that stock. It is not a temporary overlay: subsequent round calculations use $P_{i,\text{shocked}}$ as $P_{i,\text{old}}$, so its effect persists and later shocks compound on the then-current price. A shock is recorded as a market event but does not count as a pricing round or alter demand streaks.