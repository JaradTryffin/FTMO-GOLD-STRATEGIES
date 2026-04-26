"""
XAU/USD Order Block Backtester & Interactive Visualizer
Replays the OB-TRADING bot logic on 4 years of XAUUSD 1H data.
Output: xau_ob_visualizer.html  (open in any browser)

Run:
    cd "Trend Pullback Strategy"
    pip install plotly pandas numpy
    python3 xau_ob_visualizer.py
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG  — mirror your OB-TRADING bot settings
# ══════════════════════════════════════════════════════════════════════════════
DATA_FILE         = "../data/XAUUSD_H1_2022_2026.csv"
INITIAL_CAPITAL   = 10_000      # USD starting balance
RISK_PCT          = 0.75        # % of account risked per trade
RR_RATIO          = 3.0         # take-profit = RR × stop distance
SL_BUFFER_MULT    = 0.15        # ATR fraction added beyond OB wick for SL
ATR_LEN           = 14
HTF_EMA           = 50          # EMA for bullish/bearish bias
SWING_LOOKBACK    = 5           # bars each side to confirm swing high/low
OB_MAX_AGE        = 80          # bars before unvisited OB expires
OB_LOOKBACK       = 25          # bars back from swing to find the OB candle
MIN_OB_BODY_MULT  = 0.2         # OB candle body must be > ATR × this
SESSION_START     = 7           # 07:00 UTC  (London open)
SESSION_END       = 16          # 16:00 UTC  (NY afternoon)
MAX_TRADES_DAY    = 2
DAILY_LOSS_LIMIT  = 3.0         # % of account  (stop trading for the day)
BREAKEVEN_AT_1R   = True
TRAILING_AFTER_BE = True
TRAILING_ATR_MULT = 1.5
LOT_STEP          = 0.01        # minimum oz increment

OUTPUT_FILE       = "../visualizer/xau_ob_visualizer.html"


# ══════════════════════════════════════════════════════════════════════════════
#  DATA
# ══════════════════════════════════════════════════════════════════════════════
def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=['time'], index_col='time')
    df.columns = [c.lower() for c in df.columns]
    df = df[['open', 'high', 'low', 'close']].sort_index()
    return df


# ══════════════════════════════════════════════════════════════════════════════
#  INDICATORS
# ══════════════════════════════════════════════════════════════════════════════
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c, h, l, o = df['close'], df['high'], df['low'], df['open']

    # ATR
    tr        = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(ATR_LEN).mean()

    # EMA bias
    df['ema']       = c.ewm(span=HTF_EMA, adjust=False).mean()
    df['bull_bias'] = c > df['ema']
    df['bear_bias'] = c < df['ema']

    # Candle type
    df['body']     = (c - o).abs()
    df['bull_bar'] = c > o
    df['bear_bar'] = c < o

    # Session filter
    df['in_session'] = (df.index.hour >= SESSION_START) & (df.index.hour < SESSION_END)

    # Swing highs / lows (confirmed n bars after they form)
    n   = SWING_LOOKBACK
    sh  = pd.Series(False, index=df.index)
    sl_ = pd.Series(False, index=df.index)
    for i in range(n, len(df) - n):
        if h.iloc[i] == h.iloc[i - n: i + n + 1].max():
            sh.iloc[i] = True
        if l.iloc[i] == l.iloc[i - n: i + n + 1].min():
            sl_.iloc[i] = True
    df['is_swing_high'] = sh
    df['is_swing_low']  = sl_

    return df.dropna(subset=['atr', 'ema'])


# ══════════════════════════════════════════════════════════════════════════════
#  OB ENGINE  (mirrors ob_engine.py exactly)
# ══════════════════════════════════════════════════════════════════════════════
def _find_ob_candle(df, from_idx, ob_type, min_body):
    col  = 'bear_bar' if ob_type == 'bear' else 'bull_bar'
    stop = max(0, from_idx - OB_LOOKBACK)
    for j in range(from_idx, stop, -1):
        if df[col].iloc[j] and df['body'].iloc[j] >= min_body:
            ob_open  = df['open'].iloc[j]
            ob_close = df['close'].iloc[j]
            return {
                'ob_high'    : max(ob_open, ob_close),
                'ob_low'     : min(ob_open, ob_close),
                'wick_high'  : df['high'].iloc[j],
                'wick_low'   : df['low'].iloc[j],
                'formed_idx' : j,
                'formed_time': df.index[j],
            }
    return None


class OBEngine:
    def __init__(self):
        self._reset()

    def _reset(self):
        self.last_sh_price = None
        self.last_sh_idx   = -1
        self.last_sl_price = None
        self.last_sl_idx   = -1
        self.last_bull_bos = None
        self.last_bear_bos = None
        self.active_obs    = []
        self.all_obs       = []   # full history for visualisation

    def process_bar(self, df: pd.DataFrame, i: int):
        n        = SWING_LOOKBACK
        row      = df.iloc[i]
        min_body = row['atr'] * MIN_OB_BODY_MULT

        # Confirm swings
        conf_i = i - n
        if conf_i >= 0:
            if df['is_swing_high'].iloc[conf_i]:
                new_sh = df['high'].iloc[conf_i]
                if self.last_sh_price is None or new_sh != self.last_sh_price:
                    self.last_sh_price = new_sh
                    self.last_sh_idx   = conf_i
                    self.last_bull_bos = None
            if df['is_swing_low'].iloc[conf_i]:
                new_sl = df['low'].iloc[conf_i]
                if self.last_sl_price is None or new_sl != self.last_sl_price:
                    self.last_sl_price = new_sl
                    self.last_sl_idx   = conf_i
                    self.last_bear_bos = None

        # Bullish BOS → bull OB
        if (self.last_sh_price is not None
                and row['close'] > self.last_sh_price
                and self.last_bull_bos != self.last_sh_price):
            ob = _find_ob_candle(df, self.last_sh_idx, 'bear', min_body)
            if ob is not None:
                ob.update({'dir': 'bull', 'age': 0, 'mitigated': False,
                           'bos_price': self.last_sh_price, 'bos_time': df.index[i]})
                self.active_obs.append(ob)
                self.all_obs.append(ob)
            self.last_bull_bos = self.last_sh_price

        # Bearish BOS → bear OB
        if (self.last_sl_price is not None
                and row['close'] < self.last_sl_price
                and self.last_bear_bos != self.last_sl_price):
            ob = _find_ob_candle(df, self.last_sl_idx, 'bull', min_body)
            if ob is not None:
                ob.update({'dir': 'bear', 'age': 0, 'mitigated': False,
                           'bos_price': self.last_sl_price, 'bos_time': df.index[i]})
                self.active_obs.append(ob)
                self.all_obs.append(ob)
            self.last_bear_bos = self.last_sl_price

        # Age OBs, detect mitigation
        for ob in self.active_obs:
            ob['age'] += 1
            if ob['dir'] == 'bull' and row['close'] < ob['ob_low']:
                ob['mitigated'] = True
                ob.setdefault('expire_time', df.index[i])
            elif ob['dir'] == 'bear' and row['close'] > ob['ob_high']:
                ob['mitigated'] = True
                ob.setdefault('expire_time', df.index[i])

        # Remove aged-out / mitigated
        remaining = []
        for ob in self.active_obs:
            if ob['mitigated'] or ob['age'] >= OB_MAX_AGE:
                ob.setdefault('expire_time', df.index[i])
            else:
                remaining.append(ob)
        self.active_obs = remaining

    def get_triggered(self, df: pd.DataFrame, i: int) -> list:
        row       = df.iloc[i]
        triggered = []
        for ob in self.active_obs:
            if ob['dir'] == 'bull' and row['bull_bias']:
                if row['low'] <= ob['ob_high'] and row['close'] >= ob['ob_low']:
                    triggered.append(ob)
            elif ob['dir'] == 'bear' and row['bear_bias']:
                if row['high'] >= ob['ob_low'] and row['close'] <= ob['ob_high']:
                    triggered.append(ob)
        return triggered

    def mark_mitigated(self, ob: dict, ts=None):
        ob['mitigated'] = True
        if ts is not None:
            ob.setdefault('expire_time', ts)


# ══════════════════════════════════════════════════════════════════════════════
#  BACKTEST
# ══════════════════════════════════════════════════════════════════════════════
def _calc_qty(balance: float, entry: float, sl: float) -> float:
    risk_usd = balance * (RISK_PCT / 100)
    sl_dist  = abs(entry - sl)
    if sl_dist == 0:
        return LOT_STEP
    raw = risk_usd / sl_dist
    qty = max(LOT_STEP, (raw // LOT_STEP) * LOT_STEP)
    return round(qty, 2)


def run_backtest(df: pd.DataFrame):
    ob_eng       = OBEngine()
    balance      = INITIAL_CAPITAL
    equity       = []          # list of (timestamp, balance)
    trades       = []
    position     = None

    daily_pnl    = 0.0
    daily_trades = 0
    last_date    = None

    start = SWING_LOOKBACK * 2 + 10

    for i in range(start, len(df)):
        row      = df.iloc[i]
        ts       = df.index[i]
        price    = row['close']
        bar_high = row['high']
        bar_low  = row['low']
        atr      = row['atr']

        # ── Day reset ─────────────────────────────────────────
        today = ts.date()
        if last_date != today:
            daily_pnl    = 0.0
            daily_trades = 0
            last_date    = today

        # ── Manage open position ──────────────────────────────
        if position is not None:
            d       = position['dir']
            entry   = position['entry']
            sl      = position['sl']
            tp      = position['tp']
            sl_dist = position['sl_dist']
            qty     = position['qty']
            closed  = False
            exit_px = None
            reason  = ''

            if d == 'long':
                if bar_high >= tp:
                    exit_px, reason, closed = tp,  'TP', True
                elif bar_low <= sl:
                    exit_px, reason, closed = sl,  'SL', True
                else:
                    if BREAKEVEN_AT_1R and not position['be']:
                        if bar_high >= entry + sl_dist:
                            position['sl'] = entry + 0.10
                            position['be'] = True
                    if TRAILING_AFTER_BE and position['be']:
                        new_sl = price - atr * TRAILING_ATR_MULT
                        if new_sl > position['sl']:
                            position['sl'] = new_sl
            else:  # short
                if bar_low <= tp:
                    exit_px, reason, closed = tp,  'TP', True
                elif bar_high >= sl:
                    exit_px, reason, closed = sl,  'SL', True
                else:
                    if BREAKEVEN_AT_1R and not position['be']:
                        if bar_low <= entry - sl_dist:
                            position['sl'] = entry - 0.10
                            position['be'] = True
                    if TRAILING_AFTER_BE and position['be']:
                        new_sl = price + atr * TRAILING_ATR_MULT
                        if new_sl < position['sl']:
                            position['sl'] = new_sl

            if closed:
                pnl = (exit_px - entry) * qty if d == 'long' else (entry - exit_px) * qty
                balance   += pnl
                daily_pnl += pnl
                trades.append({
                    'entry_time': position['entry_time'],
                    'exit_time' : ts,
                    'dir'       : d,
                    'entry'     : entry,
                    'exit'      : exit_px,
                    'sl'        : position['initial_sl'],
                    'tp'        : tp,
                    'qty'       : qty,
                    'pnl'       : pnl,
                    'reason'    : reason,
                    'be'        : position['be'],
                })
                position = None

        equity.append((ts, balance))

        # ── Update OB engine ──────────────────────────────────
        ob_eng.process_bar(df, i)

        # ── Entry check ───────────────────────────────────────
        if position is not None:
            continue
        if not row['in_session']:
            continue
        if daily_trades >= MAX_TRADES_DAY:
            continue
        if daily_pnl <= -(balance * DAILY_LOSS_LIMIT / 100):
            continue

        triggered = ob_eng.get_triggered(df, i)
        if not triggered:
            continue

        ob        = triggered[0]
        direction = 'long' if ob['dir'] == 'bull' else 'short'
        entry     = ob['ob_high'] if direction == 'long' else ob['ob_low']
        sl_buf    = atr * SL_BUFFER_MULT
        sl        = (ob['wick_low'] - sl_buf if direction == 'long'
                     else ob['wick_high'] + sl_buf)
        sl_dist   = abs(entry - sl)

        if sl_dist < 0.50:   # minimum $0.50 SL distance for XAU
            continue

        tp  = (entry + sl_dist * RR_RATIO if direction == 'long'
               else entry - sl_dist * RR_RATIO)
        qty = _calc_qty(balance, entry, sl)

        position = {
            'dir'       : direction,
            'entry'     : entry,
            'sl'        : sl,
            'initial_sl': sl,
            'tp'        : tp,
            'sl_dist'   : sl_dist,
            'qty'       : qty,
            'be'        : False,
            'entry_time': ts,
        }
        ob_eng.mark_mitigated(ob, ts)
        daily_trades += 1

    # Close any position still open at end of data
    if position is not None:
        last_px = df['close'].iloc[-1]
        pnl = ((last_px - position['entry']) * position['qty']
               if position['dir'] == 'long'
               else (position['entry'] - last_px) * position['qty'])
        balance += pnl
        trades.append({
            'entry_time': position['entry_time'],
            'exit_time' : df.index[-1],
            'dir'       : position['dir'],
            'entry'     : position['entry'],
            'exit'      : last_px,
            'sl'        : position['initial_sl'],
            'tp'        : position['tp'],
            'qty'       : position['qty'],
            'pnl'       : pnl,
            'reason'    : 'END',
            'be'        : position['be'],
        })
        equity.append((df.index[-1], balance))

    trades_df = pd.DataFrame(trades)
    equity_df = pd.DataFrame(equity, columns=['time', 'balance'])
    return trades_df, equity_df, ob_eng.all_obs


# ══════════════════════════════════════════════════════════════════════════════
#  STATS
# ══════════════════════════════════════════════════════════════════════════════
def calc_stats(trades_df: pd.DataFrame, equity_df: pd.DataFrame) -> dict:
    if trades_df.empty:
        return {}

    wins  = trades_df[trades_df['pnl'] > 0]
    loses = trades_df[trades_df['pnl'] <= 0]

    win_rate = len(wins) / len(trades_df) * 100
    pf       = (wins['pnl'].sum() / abs(loses['pnl'].sum())
                if not loses.empty and loses['pnl'].sum() != 0 else float('inf'))

    eq   = equity_df['balance'].values
    peak = np.maximum.accumulate(eq)
    dd   = (eq - peak) / peak * 100
    max_dd = dd.min()

    daily = trades_df.copy()
    daily['day'] = daily['entry_time'].dt.date
    daily_ret = daily.groupby('day')['pnl'].sum()
    sharpe = (daily_ret.mean() / daily_ret.std() * np.sqrt(252)
              if len(daily_ret) > 1 else 0.0)

    return {
        'total_trades' : len(trades_df),
        'wins'         : len(wins),
        'losses'       : len(loses),
        'win_rate'     : win_rate,
        'profit_factor': pf,
        'avg_win'      : wins['pnl'].mean() if not wins.empty else 0,
        'avg_loss'     : loses['pnl'].mean() if not loses.empty else 0,
        'max_drawdown' : max_dd,
        'sharpe'       : sharpe,
        'total_return' : (equity_df['balance'].iloc[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100,
        'final_balance': equity_df['balance'].iloc[-1],
    }


# ══════════════════════════════════════════════════════════════════════════════
#  VISUALIZER
# ══════════════════════════════════════════════════════════════════════════════
def plot_results(df, trades_df, equity_df, all_obs, stats):
    print("  Building interactive chart (this may take a moment)...")

    # ── Subplots ─────────────────────────────────────────────
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.60, 0.25, 0.15],
        vertical_spacing=0.02,
        subplot_titles=(
            'XAU/USD 1H — Order Block Strategy',
            'Equity Curve',
            'Drawdown %',
        )
    )

    # ── Candlesticks ─────────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x                    = df.index,
        open                 = df['open'],
        high                 = df['high'],
        low                  = df['low'],
        close                = df['close'],
        name                 = 'XAUUSD',
        increasing_line_color= '#26a69a',
        decreasing_line_color= '#ef5350',
        showlegend           = False,
    ), row=1, col=1)

    # ── EMA ──────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x         = df.index,
        y         = df['ema'],
        name      = f'EMA({HTF_EMA})',
        line      = dict(color='#FFA726', width=1.2),
        hoverinfo = 'skip',
    ), row=1, col=1)

    # ── OB Zones (shapes) ────────────────────────────────────
    shapes = []
    for ob in all_obs:
        bull  = ob['dir'] == 'bull'
        fill  = 'rgba(38,166,154,0.12)'  if bull else 'rgba(239,83,80,0.12)'
        edge  = 'rgba(38,166,154,0.45)'  if bull else 'rgba(239,83,80,0.45)'
        x1    = ob.get('expire_time', df.index[-1])
        shapes.append(dict(
            type      = 'rect',
            xref      = 'x',
            yref      = 'y',
            x0        = ob['formed_time'],
            x1        = x1,
            y0        = ob['ob_low'],
            y1        = ob['ob_high'],
            fillcolor = fill,
            line      = dict(color=edge, width=0.5),
            layer     = 'below',
        ))

    # ── Trades ───────────────────────────────────────────────
    if not trades_df.empty:

        def _hover(row):
            return (
                f"<b>{row['dir'].upper()} {'✅' if row['pnl'] > 0 else '❌'}</b><br>"
                f"Entry:  {row['entry']:.2f}  →  Exit: {row['exit']:.2f}<br>"
                f"SL: {row['sl']:.2f}  |  TP: {row['tp']:.2f}<br>"
                f"Qty: {row['qty']:.2f} oz<br>"
                f"P&L: <b>${row['pnl']:+.2f}</b><br>"
                f"Reason: {row['reason']}{'  (BE moved)' if row['be'] else ''}<br>"
                f"In:  {row['entry_time'].strftime('%Y-%m-%d %H:%M')}<br>"
                f"Out: {row['exit_time'].strftime('%Y-%m-%d %H:%M')}"
            )

        subsets = [
            (trades_df[(trades_df['dir'] == 'long')  & (trades_df['pnl'] > 0)],
             '#26a69a', 'triangle-up',   'Long Win'),
            (trades_df[(trades_df['dir'] == 'long')  & (trades_df['pnl'] <= 0)],
             '#ef9a9a', 'triangle-up',   'Long Loss'),
            (trades_df[(trades_df['dir'] == 'short') & (trades_df['pnl'] > 0)],
             '#ef5350', 'triangle-down', 'Short Win'),
            (trades_df[(trades_df['dir'] == 'short') & (trades_df['pnl'] <= 0)],
             '#a5d6a7', 'triangle-down', 'Short Loss'),
        ]
        for subset, color, symbol, label in subsets:
            if subset.empty:
                continue
            fig.add_trace(go.Scatter(
                x         = subset['entry_time'],
                y         = subset['entry'],
                mode      = 'markers',
                name      = label,
                marker    = dict(symbol=symbol, size=11, color=color,
                                 line=dict(width=1, color='white')),
                text      = subset.apply(_hover, axis=1),
                hoverinfo = 'text',
            ), row=1, col=1)

        # SL / TP lines per trade
        for _, t in trades_df.iterrows():
            c = '#26a69a' if t['pnl'] > 0 else '#ef5350'
            for y_val, dash in [(t['sl'], 'dot'), (t['tp'], 'dash')]:
                shapes.append(dict(
                    type  = 'line',
                    xref  = 'x', yref = 'y',
                    x0    = t['entry_time'], x1 = t['exit_time'],
                    y0    = y_val,           y1 = y_val,
                    line  = dict(color=c, width=0.7, dash=dash),
                    layer = 'above',
                ))

    # ── Equity curve ─────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x         = equity_df['time'],
        y         = equity_df['balance'],
        name      = 'Equity',
        fill      = 'tozeroy',
        line      = dict(color='#42A5F5', width=1.5),
        fillcolor = 'rgba(66,165,245,0.08)',
    ), row=2, col=1)

    fig.add_hline(
        y=INITIAL_CAPITAL, line_dash='dot',
        line_color='gray', line_width=1, row=2, col=1,
    )

    # ── Drawdown ─────────────────────────────────────────────
    eq   = equity_df['balance'].values
    peak = np.maximum.accumulate(eq)
    dd   = (eq - peak) / peak * 100

    fig.add_trace(go.Scatter(
        x         = equity_df['time'],
        y         = dd,
        name      = 'Drawdown',
        fill      = 'tozeroy',
        line      = dict(color='#EF5350', width=1),
        fillcolor = 'rgba(239,83,80,0.18)',
    ), row=3, col=1)

    # ── Stats banner ─────────────────────────────────────────
    s = stats
    banner = (
        f"Trades: {s.get('total_trades',0)}  |  "
        f"Win Rate: {s.get('win_rate',0):.1f}%  |  "
        f"Profit Factor: {s.get('profit_factor',0):.2f}  |  "
        f"Max DD: {s.get('max_drawdown',0):.1f}%  |  "
        f"Return: {s.get('total_return',0):.1f}%  |  "
        f"Sharpe: {s.get('sharpe',0):.2f}  |  "
        f"Final: ${s.get('final_balance',0):,.0f}"
    )

    # ── Layout ───────────────────────────────────────────────
    fig.update_layout(
        title=dict(
            text=f'<b>XAU/USD OB Strategy Backtest</b>   '
                 f'<span style="font-size:12px;color:#aaa">{banner}</span>',
            font=dict(size=14),
        ),
        template          = 'plotly_dark',
        height            = 1050,
        shapes            = shapes,
        hovermode         = 'x unified',
        legend            = dict(orientation='h', y=1.03, x=0, bgcolor='rgba(0,0,0,0)'),
        paper_bgcolor     = '#0f0f1a',
        plot_bgcolor      = '#13131f',
        font              = dict(color='#d0d0e0', size=11),
        margin            = dict(l=65, r=20, t=90, b=40),
        xaxis_rangeslider_visible = False,
    )
    fig.update_xaxes(gridcolor='#1e1e30', zeroline=False, showspikes=True, spikecolor='#555')
    fig.update_yaxes(gridcolor='#1e1e30', zeroline=False)

    fig.write_html(OUTPUT_FILE, include_plotlyjs='cdn')
    print(f"  Saved → {OUTPUT_FILE}")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    print("═" * 55)
    print("  XAU/USD OB Visualizer")
    print("═" * 55)

    print("Loading data...")
    df = load_data(DATA_FILE)
    print(f"  {len(df):,} candles  |  {df.index[0].date()} → {df.index[-1].date()}")

    print("Calculating indicators...")
    df = add_indicators(df)
    print(f"  {len(df):,} bars after indicator warm-up")

    print("Running backtest...")
    trades_df, equity_df, all_obs = run_backtest(df)
    print(f"  {len(trades_df)} trades  |  {len(all_obs)} OB zones formed")

    stats = calc_stats(trades_df, equity_df)

    print("\n── Results ──────────────────────────────────────")
    print(f"  Total trades   : {stats.get('total_trades', 0)}")
    print(f"  Win rate       : {stats.get('win_rate', 0):.1f}%")
    print(f"  Profit factor  : {stats.get('profit_factor', 0):.2f}")
    print(f"  Avg win        : ${stats.get('avg_win', 0):.2f}")
    print(f"  Avg loss       : ${stats.get('avg_loss', 0):.2f}")
    print(f"  Max drawdown   : {stats.get('max_drawdown', 0):.2f}%")
    print(f"  Sharpe ratio   : {stats.get('sharpe', 0):.2f}")
    print(f"  Total return   : {stats.get('total_return', 0):.1f}%")
    print(f"  Final balance  : ${stats.get('final_balance', 0):,.2f}")
    print("─" * 49)

    plot_results(df, trades_df, equity_df, all_obs, stats)

    print(f"\n  Done! Open '{OUTPUT_FILE}' in your browser.")
    print("═" * 55)


if __name__ == '__main__':
    main()
