# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Gold (XAUUSD) algorithmic trading backtester and FTMO challenge simulator. It validates whether an EMA Trend + Pullback + Rejection Candle strategy can pass FTMO's 2026 funded trading challenges (1-Step or 2-Step).

## Running the Backtest

```bash
# Install dependencies
pip install -r requirements.txt

# Run the backtester (from project root or the strategy directory)
cd "Trend Pullback Strategy"
python3 gold_v3_backtest.py
```

**Outputs generated:**
- `gold_v3_report.png` — visual dashboard (equity curve, FTMO pass rate gauge, drawdown, monthly P&L)
- `gold_v3_trades.csv` — full trade log with entry/exit prices, P&L, and drawdown

## Data

- Price data file: `Trend Pullback Strategy/xauusd_1h.csv.csv` — real XAUUSD 1H OHLCV data from TradingView (ISO export format)
- To update data: export from TradingView → XAUUSD 1H → Export Data → ISO format, save as CSV, update `CONFIG["DATA_FILE"]`
- If `DATA_FILE` is `None`, synthetic data is generated via `generate_gold_data()`

## Architecture

The entire strategy is in a single file: `Trend Pullback Strategy/gold_v3_backtest.py`

**Execution flow:**
1. `load_data()` — loads CSV or calls `generate_gold_data()`
2. `add_indicators()` — computes EMA(8/21/50), ATR(14), RSI(14), candle body ratios
3. `run_backtest()` — bar-by-bar event loop; manages open positions (breakeven, trailing stop, session exit) before checking for new entries
4. `analyze_performance()` — computes all metrics: win rate, profit factor, max drawdown, Sharpe ratio
5. `simulate_ftmo_2026()` — Monte Carlo with 1,000 simulations drawing from historical trade P&L distribution, evaluates FTMO rule compliance per sim
6. `plot_results()` — generates the 6-panel matplotlib dashboard

## Strategy Logic (CONFIG keys)

All parameters live in the `CONFIG` dict at the top of `gold_v3_backtest.py`.

**Entry (Long):** EMA21 > EMA50, price > EMA50, price touches EMA8 pullback, deep pullback (≥25% of swing range), bull rejection/engulfing candle, RSI 45–70, within session hours (07:00–16:00 GMT)

**Entry (Short):** Mirror logic with RSI 30–55

**Risk per trade:** `RISK_PCT` (1.0%) of current equity → dynamic lot sizing via `LOT_SIZE_UNIT` (0.01 lots = $1/point)

**Stop loss:** `ATR × ATR_SL_MULT` (1.2); Take profit: `RR_RATIO` (2.5) × stop distance

**Exit conditions (checked in order each bar):** stop loss, take profit, session end (16:00 GMT), trailing stop (activated after breakeven at 1R)

## FTMO 2026 Rules (simulated)

| Parameter | Value |
|---|---|
| Profit target | 10% |
| Max daily loss | 5% |
| Max total drawdown | 10% |
| Min trading days | 2 |
| Time limit | None |
| Best day rule | Single day ≤ 50% of profit target |

## Key Tuning Levers

To improve FTMO pass rate, adjust in `CONFIG`:
- `RR_RATIO` — risk/reward (higher = fewer wins needed)
- `ATR_SL_MULT` — stop distance (tighter = more risk of stop-outs)
- `RSI_BULL_MIN/MAX`, `RSI_BEAR_MIN/MAX` — entry quality filter
- `MAX_TRADES_DAY` — daily trade cap (reduces daily loss exposure)
- `MC_SIMULATIONS` — increase for more stable pass-rate estimates
