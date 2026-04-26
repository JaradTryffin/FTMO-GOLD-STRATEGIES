"""
╔══════════════════════════════════════════════════════════════╗
║   OB BACKTESTER — Order Block Strategy                      ║
║   With FTMO 2026 Challenge Simulator                        ║
║                                                              ║
║   HOW TO RUN:                                               ║
║   1. Open config.py                                         ║
║   2. Set ACTIVE_INSTRUMENT to the one you want              ║
║   3. python3 backtest.py                                    ║
╚══════════════════════════════════════════════════════════════╝

STRATEGY LOGIC:
  1. Detect swing highs/lows to define market structure
  2. Break of Structure (BOS) confirms directional bias
  3. Order Block = last opposite-colour candle before the impulse
     - Bullish OB: last bearish candle before a bullish BOS
     - Bearish OB: last bullish candle before a bearish BOS
  4. Enter when price retraces into the OB zone
  5. SL below/above OB candle wick | TP at configurable R:R

FTMO 2026 RULES SIMULATED:
  - No time limit
  - Minimum 2 trading days
  - 10% profit target
  - 5% max daily loss | 10% max total loss
  - Best Day Rule: no single day > 50% of profit target
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

from config import INSTRUMENTS, ACTIVE_INSTRUMENT

CONFIG = INSTRUMENTS[ACTIVE_INSTRUMENT]


# ══════════════════════════════════════════════════════════════════════════════
#  SYNTHETIC DATA  (fallback when DATA_FILE is None)
# ══════════════════════════════════════════════════════════════════════════════
def generate_synthetic_data(n_days=600):
    print("  No DATA_FILE set — generating synthetic data...")
    np.random.seed(42)
    n_bars         = n_days * 24
    price          = 2000.0
    prices         = []
    trend_dir      = 1
    trend_length   = 0
    vol_regime     = 1.0
    regime_counter = 0

    for i in range(n_bars):
        regime_counter += 1
        if regime_counter > np.random.randint(80, 200):
            vol_regime     = np.random.choice([0.7, 1.0, 1.4, 1.8], p=[0.2, 0.4, 0.3, 0.1])
            regime_counter = 0
        trend_length += 1
        if trend_length > np.random.randint(60, 250):
            trend_dir   *= -1
            trend_length = 0
        ret   = np.random.normal(0.008 * trend_dir * 2.0, 3.5 * vol_regime)
        price = max(1800, min(3200, price + ret))
        prices.append(price)

    start  = datetime(2024, 1, 2, 0, 0)
    times  = [start + timedelta(hours=i) for i in range(n_bars)]
    closes = np.array(prices)
    highs  = closes + np.abs(np.random.normal(0, 2.8, n_bars))
    lows   = closes - np.abs(np.random.normal(0, 2.8, n_bars))
    opens  = np.roll(closes, 1); opens[0] = closes[0]
    df     = pd.DataFrame({'open': opens, 'high': highs, 'low': lows,
                           'close': closes, 'volume': np.random.randint(1000, 50000, n_bars)},
                          index=times)
    df.index.name = 'datetime'
    return df


# ══════════════════════════════════════════════════════════════════════════════
#  DATA LOADER
# ══════════════════════════════════════════════════════════════════════════════
def load_data(filepath=None):
    if not filepath:
        return generate_synthetic_data()

    print(f"  Loading data from {filepath}...")
    df = pd.read_csv(filepath)
    df.columns = [c.lower().strip() for c in df.columns]

    time_col = next((c for c in df.columns if 'time' in c or 'date' in c), None)
    if time_col:
        df['datetime'] = pd.to_datetime(df[time_col], utc=True).dt.tz_localize(None)
        df.set_index('datetime', inplace=True)
        df.sort_index(inplace=True)

    col_map = {}
    for c in df.columns:
        if   'open'  in c: col_map[c] = 'open'
        elif 'high'  in c: col_map[c] = 'high'
        elif 'low'   in c: col_map[c] = 'low'
        elif 'close' in c: col_map[c] = 'close'
        elif 'vol'   in c: col_map[c] = 'volume'
    df.rename(columns=col_map, inplace=True)

    available = [c for c in ['open', 'high', 'low', 'close', 'volume'] if c in df.columns]
    df = df[available].apply(pd.to_numeric, errors='coerce').dropna()
    if 'volume' not in df.columns:
        df['volume'] = 1000

    print(f"  Loaded {len(df):,} bars | {df.index[0].date()} → {df.index[-1].date()}")
    return df


# ══════════════════════════════════════════════════════════════════════════════
#  INDICATORS
# ══════════════════════════════════════════════════════════════════════════════
def add_indicators(df, cfg):
    c, h, l, o = df['close'], df['high'], df['low'], df['open']

    # ATR
    tr        = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(cfg['ATR_LEN']).mean()

    # HTF bias via EMA
    df['htf_ema']   = c.ewm(span=cfg['HTF_EMA'], adjust=False).mean()
    df['bull_bias'] = c > df['htf_ema']
    df['bear_bias'] = c < df['htf_ema']

    # Candle properties
    df['body']     = (c - o).abs()
    df['bull_bar'] = c > o
    df['bear_bar'] = c < o

    # Session filter
    df['hour_gmt']   = df.index.hour
    df['in_session'] = ((df['hour_gmt'] >= cfg['SESSION_START']) &
                        (df['hour_gmt'] <  cfg['SESSION_END']))

    # Swing highs/lows — confirmed n bars after they form (no lookahead)
    n  = cfg['SWING_LOOKBACK']
    sh = pd.Series(False, index=df.index)
    sl = pd.Series(False, index=df.index)
    for i in range(n, len(df) - n):
        if h.iloc[i] == h.iloc[i - n: i + n + 1].max():
            sh.iloc[i] = True
        if l.iloc[i] == l.iloc[i - n: i + n + 1].min():
            sl.iloc[i] = True
    df['is_swing_high'] = sh
    df['is_swing_low']  = sl

    return df.dropna(subset=['atr', 'htf_ema'])


# ══════════════════════════════════════════════════════════════════════════════
#  ORDER BLOCK HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def find_ob_candle(df, from_idx, lookback, ob_type, min_body):
    """
    Search backwards from from_idx for the last candle of ob_type
    ('bear' for bullish OB, 'bull' for bearish OB) with body >= min_body.
    """
    col  = 'bear_bar' if ob_type == 'bear' else 'bull_bar'
    stop = max(0, from_idx - lookback)
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


# ══════════════════════════════════════════════════════════════════════════════
#  BACKTESTER
# ══════════════════════════════════════════════════════════════════════════════
def run_backtest(df, cfg):
    capital      = cfg['INITIAL_CAPITAL']
    trades       = []
    equity_curve = [capital]
    equity_dates = [df.index[0]]
    position     = None
    trades_today = 0
    last_date    = None

    n         = cfg['SWING_LOOKBACK']
    start_bar = n * 2 + 10

    last_sh_price = None
    last_sh_idx   = -1
    last_sl_price = None
    last_sl_idx   = -1
    last_bull_bos = None
    last_bear_bos = None
    active_obs    = []

    for i in range(start_bar, len(df)):
        row  = df.iloc[i]
        date = df.index[i].date()

        if date != last_date:
            trades_today = 0
            last_date    = date

        # ── Update confirmed swings (n bars ago) ──────────────
        conf_i = i - n
        if df['is_swing_high'].iloc[conf_i]:
            new_sh = df['high'].iloc[conf_i]
            if last_sh_price is None or new_sh != last_sh_price:
                last_sh_price = new_sh
                last_sh_idx   = conf_i
                last_bull_bos = None
        if df['is_swing_low'].iloc[conf_i]:
            new_sl = df['low'].iloc[conf_i]
            if last_sl_price is None or new_sl != last_sl_price:
                last_sl_price = new_sl
                last_sl_idx   = conf_i
                last_bear_bos = None

        # ── Detect BOS and create Order Blocks ────────────────
        min_body = row['atr'] * cfg['MIN_OB_BODY_MULT']

        if (last_sh_price is not None
                and row['close'] > last_sh_price
                and last_bull_bos != last_sh_price):
            ob = find_ob_candle(df, last_sh_idx, cfg['OB_LOOKBACK'], 'bear', min_body)
            if ob is not None:
                ob.update({'dir': 'bull', 'age': 0, 'mitigated': False,
                           'bos_price': last_sh_price})
                active_obs.append(ob)
            last_bull_bos = last_sh_price

        if (last_sl_price is not None
                and row['close'] < last_sl_price
                and last_bear_bos != last_sl_price):
            ob = find_ob_candle(df, last_sl_idx, cfg['OB_LOOKBACK'], 'bull', min_body)
            if ob is not None:
                ob.update({'dir': 'bear', 'age': 0, 'mitigated': False,
                           'bos_price': last_sl_price})
                active_obs.append(ob)
            last_bear_bos = last_sl_price

        # ── Age OBs and check mitigation ──────────────────────
        for ob in active_obs:
            ob['age'] += 1
            if ob['dir'] == 'bull' and row['close'] < ob['ob_low']:
                ob['mitigated'] = True
            elif ob['dir'] == 'bear' and row['close'] > ob['ob_high']:
                ob['mitigated'] = True
        active_obs = [ob for ob in active_obs
                      if not ob['mitigated'] and ob['age'] < cfg['OB_MAX_AGE']]

        # ── Manage open position ──────────────────────────────
        if position is not None:
            closed  = False
            pnl_pts = 0
            reason  = ''

            if position['dir'] == 'long':
                if row['low'] <= position['sl']:
                    pnl_pts = position['sl'] - position['entry']; closed = True; reason = 'SL'
                elif row['high'] >= position['tp']:
                    pnl_pts = position['tp'] - position['entry']; closed = True; reason = 'TP'
                else:
                    if cfg['BREAKEVEN_AT_1R'] and not position['be']:
                        if row['high'] >= position['entry'] + position['sl_dist']:
                            position['sl'] = position['entry'] + 0.5
                            position['be'] = True
                    if cfg['TRAILING_AFTER_BE'] and position['be']:
                        new_sl = row['close'] - row['atr'] * cfg['TRAILING_ATR_MULT']
                        if new_sl > position['sl']:
                            position['sl'] = new_sl
            else:
                if row['high'] >= position['sl']:
                    pnl_pts = position['entry'] - position['sl']; closed = True; reason = 'SL'
                elif row['low'] <= position['tp']:
                    pnl_pts = position['entry'] - position['tp']; closed = True; reason = 'TP'
                else:
                    if cfg['BREAKEVEN_AT_1R'] and not position['be']:
                        if row['low'] <= position['entry'] - position['sl_dist']:
                            position['sl'] = position['entry'] - 0.5
                            position['be'] = True
                    if cfg['TRAILING_AFTER_BE'] and position['be']:
                        new_sl = row['close'] + row['atr'] * cfg['TRAILING_ATR_MULT']
                        if new_sl < position['sl']:
                            position['sl'] = new_sl

            if row['hour_gmt'] >= cfg['SESSION_END'] and not closed:
                pnl_pts = ((row['close'] - position['entry']) if position['dir'] == 'long'
                           else (position['entry'] - row['close']))
                closed = True; reason = 'SessionEnd'

            if closed:
                pnl_usd  = pnl_pts * (position['lots'] / cfg['LOT_SIZE_UNIT']) * cfg['POINT_VALUE']
                capital += pnl_usd
                trades.append({
                    'entry_time'  : position['entry_time'],
                    'exit_time'   : df.index[i],
                    'direction'   : position['dir'],
                    'entry_price' : position['entry'],
                    'exit_price'  : (position['sl'] if reason == 'SL' else
                                     position['tp'] if reason == 'TP' else row['close']),
                    'sl'          : position['sl'],
                    'tp'          : position['tp'],
                    'lots'        : position['lots'],
                    'pnl_points'  : pnl_pts,
                    'pnl_dollars' : pnl_usd,
                    'pnl_pct'     : pnl_usd / (capital - pnl_usd) * 100,
                    'reason'      : reason,
                    'capital'     : capital,
                    'be_moved'    : position['be'],
                    'ob_formed'   : position['ob_time'],
                })
                position = None

        equity_curve.append(capital)
        equity_dates.append(df.index[i])

        # ── Check for OB entries ───────────────────────────────
        if position is None and trades_today < cfg['MAX_TRADES_DAY'] and row['in_session']:
            for ob in active_obs:
                if ob['mitigated']:
                    continue

                entry     = None
                sl        = None
                direction = None

                if ob['dir'] == 'bull' and row['bull_bias']:
                    if row['low'] <= ob['ob_high'] and row['close'] >= ob['ob_low']:
                        entry     = ob['ob_high']
                        sl        = ob['wick_low'] - row['atr'] * cfg['SL_BUFFER_MULT']
                        direction = 'long'

                elif ob['dir'] == 'bear' and row['bear_bias']:
                    if row['high'] >= ob['ob_low'] and row['close'] <= ob['ob_high']:
                        entry     = ob['ob_low']
                        sl        = ob['wick_high'] + row['atr'] * cfg['SL_BUFFER_MULT']
                        direction = 'short'

                if entry is not None and sl is not None:
                    sl_dist = abs(entry - sl)
                    if sl_dist < 0.5:
                        continue
                    tp   = (entry + sl_dist * cfg['RR_RATIO'] if direction == 'long'
                            else entry - sl_dist * cfg['RR_RATIO'])
                    risk = capital * (cfg['RISK_PCT'] / 100)
                    lots = max(0.01, round(
                        risk / (sl_dist * (1 / cfg['LOT_SIZE_UNIT']) * cfg['POINT_VALUE']), 2))

                    position = {
                        'dir'        : direction,
                        'entry'      : entry,
                        'entry_time' : df.index[i],
                        'sl'         : sl,
                        'tp'         : tp,
                        'sl_dist'    : sl_dist,
                        'lots'       : lots,
                        'be'         : False,
                        'ob_time'    : ob['formed_time'],
                    }
                    ob['mitigated'] = True
                    trades_today   += 1
                    break

    return pd.DataFrame(trades), pd.Series(equity_curve, index=equity_dates)


# ══════════════════════════════════════════════════════════════════════════════
#  PERFORMANCE METRICS
# ══════════════════════════════════════════════════════════════════════════════
def analyze_performance(tdf, equity_s, cfg):
    if tdf.empty:
        return {}
    wins = tdf[tdf['pnl_dollars'] > 0]
    loss = tdf[tdf['pnl_dollars'] <= 0]
    gp   = wins['pnl_dollars'].sum()
    gl   = loss['pnl_dollars'].sum()
    pf   = abs(gp / gl) if gl != 0 else 999
    wr   = len(wins) / len(tdf) * 100
    np_  = tdf['pnl_dollars'].sum()
    aw   = wins['pnl_dollars'].mean() if len(wins) else 0
    al   = loss['pnl_dollars'].mean() if len(loss) else 0
    rr   = abs(aw / al)               if al != 0  else 0

    rm   = equity_s.cummax()
    dd   = (equity_s - rm) / rm * 100
    mdd  = dd.min()
    mdd_d = (equity_s - rm).min()

    consec = 0; max_c = 0
    for r in (tdf['pnl_dollars'] > 0):
        consec = 0 if r else consec + 1
        max_c  = max(max_c, consec)

    tdf   = tdf.copy()
    tdf['month'] = pd.to_datetime(tdf['exit_time']).dt.to_period('M')
    monthly      = tdf.groupby('month')['pnl_dollars'].sum()
    dr           = equity_s.resample('D').last().pct_change().dropna()
    sharpe       = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0

    return {
        'total_trades'   : len(tdf),
        'win_rate'       : wr,
        'profit_factor'  : pf,
        'net_profit'     : np_,
        'net_profit_pct' : np_ / cfg['INITIAL_CAPITAL'] * 100,
        'gross_profit'   : gp,
        'gross_loss'     : gl,
        'avg_win'        : aw,
        'avg_loss'       : al,
        'actual_rr'      : rr,
        'max_dd_pct'     : mdd,
        'max_dd_dollar'  : mdd_d,
        'max_consec_loss': max_c,
        'monthly_returns': monthly,
        'sharpe'         : sharpe,
        'winners'        : len(wins),
        'losers'         : len(loss),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  FTMO 2026 MONTE CARLO SIMULATOR
# ══════════════════════════════════════════════════════════════════════════════
def simulate_ftmo_2026(tdf, cfg):
    if tdf.empty:
        return {}

    print("\n  Running FTMO 2026 Monte Carlo (unlimited time)...")

    cap0         = cfg['INITIAL_CAPITAL']
    target       = cap0 * cfg['FTMO_PROFIT_TARGET']  / 100
    max_dd_lim   = cap0 * cfg['FTMO_MAX_TOTAL_LOSS']  / 100
    max_dy_lim   = cap0 * cfg['FTMO_MAX_DAILY_LOSS']  / 100
    best_day_max = target * cfg['FTMO_BEST_DAY_RULE'] / 100
    min_days     = cfg['FTMO_MIN_DAYS']

    pnl_pct_seq = tdf['pnl_pct'].values
    n           = len(pnl_pct_seq)

    passes              = 0
    f_dd                = 0
    finals              = []
    trades_to_pass_list = []

    for _ in range(cfg['MC_SIMULATIONS']):
        bal         = cap0
        failed      = False
        passed      = False
        trade_days  = {}
        trade_count = 0
        day_counter = 0

        while trade_count < cfg['MC_MAX_TRADES']:
            pnl_pct = float(np.random.choice(pnl_pct_seq))
            pnl     = bal * pnl_pct / 100

            if trade_count % 2 == 0:
                day_counter += 1
            trade_day = day_counter
            trade_days[trade_day] = trade_days.get(trade_day, 0) + pnl

            bal         += pnl
            trade_count += 1

            if trade_days[trade_day] < -max_dy_lim:
                failed = True; f_dd += 1; break
            if (cap0 - bal) >= max_dd_lim:
                failed = True; f_dd += 1; break

            profit      = bal - cap0
            num_days    = len(trade_days)
            if profit >= target and num_days >= min_days:
                if max(trade_days.values()) <= best_day_max:
                    passed = True
                    passes += 1
                    trades_to_pass_list.append(trade_count)
                    break

        finals.append(bal - cap0)

    pass_rate          = passes / cfg['MC_SIMULATIONS'] * 100
    avg_trades_to_pass = np.mean(trades_to_pass_list) if trades_to_pass_list else 0
    trades_per_week    = n / ((pd.to_datetime(tdf['exit_time'].iloc[-1]) -
                               pd.to_datetime(tdf['entry_time'].iloc[0])).days / 7)
    avg_weeks_to_pass  = (avg_trades_to_pass / max(trades_per_week, 1)
                          if avg_trades_to_pass > 0 else 0)

    return {
        'pass_rate'         : pass_rate,
        'passes'            : passes,
        'fails_drawdown'    : f_dd,
        'avg_final_pnl'     : np.mean(finals),
        'avg_trades_to_pass': avg_trades_to_pass,
        'avg_weeks_to_pass' : avg_weeks_to_pass,
        'simulations'       : cfg['MC_SIMULATIONS'],
        'best_day_limit'    : best_day_max,
        'profit_target'     : target,
        'max_daily_loss'    : max_dy_lim,
        'max_total_loss'    : max_dd_lim,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  VISUALIZATION
# ══════════════════════════════════════════════════════════════════════════════
def plot_results(tdf, equity_s, metrics, ftmo, cfg):
    BG    = '#0d1117'; PANEL = '#161b22'; TEXT  = '#e6edf3'; MUTED = '#8b949e'
    GOLD  = '#FFD700'; GREEN = '#00ff88'; RED   = '#ff4444'; BLUE  = '#4488ff'

    fig = plt.figure(figsize=(22, 14), facecolor=BG)
    gs  = gridspec.GridSpec(3, 3, figure=fig, hspace=0.45, wspace=0.35)
    ax1 = fig.add_subplot(gs[0, :])
    ax2 = fig.add_subplot(gs[1, 0])
    ax3 = fig.add_subplot(gs[1, 1])
    ax4 = fig.add_subplot(gs[1, 2])
    ax5 = fig.add_subplot(gs[2, 0])
    ax6 = fig.add_subplot(gs[2, 1])
    ax7 = fig.add_subplot(gs[2, 2])

    for ax in [ax1, ax2, ax3, ax4, ax5, ax6, ax7]:
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=MUTED, labelsize=8)
        for s in ax.spines.values(): s.set_color('#30363d')

    # ── Equity Curve ─────────────────────────────────────────
    ax1.plot(equity_s.index, equity_s.values, color=GOLD, linewidth=2)
    ax1.fill_between(equity_s.index, equity_s.values, cfg['INITIAL_CAPITAL'],
                     alpha=0.15,
                     color=GREEN if equity_s.iloc[-1] > cfg['INITIAL_CAPITAL'] else RED)
    ax1.axhline(cfg['INITIAL_CAPITAL'], color=MUTED, linewidth=1, linestyle='--', alpha=0.5)
    ftmo_target = cfg['INITIAL_CAPITAL'] * (1 + cfg['FTMO_PROFIT_TARGET'] / 100)
    ftmo_loss   = cfg['INITIAL_CAPITAL'] * (1 - cfg['FTMO_MAX_TOTAL_LOSS'] / 100)
    ax1.axhline(ftmo_target, color=GREEN, linewidth=1, linestyle=':', alpha=0.7,
                label=f"FTMO Target (+{cfg['FTMO_PROFIT_TARGET']}%)")
    ax1.axhline(ftmo_loss,   color=RED,   linewidth=1, linestyle=':', alpha=0.7,
                label=f"FTMO Max Loss (-{cfg['FTMO_MAX_TOTAL_LOSS']}%)")
    ax1.legend(fontsize=7, facecolor=PANEL, labelcolor=TEXT, loc='upper left')
    ax1.set_title(f"Equity Curve — {cfg['name']} | {equity_s.index[0].date()} → {equity_s.index[-1].date()}",
                  color=TEXT, fontsize=13, pad=10)
    ax1.set_ylabel('Capital ($)', color=MUTED, fontsize=9)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'${x:,.0f}'))
    pct = (equity_s.iloc[-1] - cfg['INITIAL_CAPITAL']) / cfg['INITIAL_CAPITAL'] * 100
    col = GREEN if pct > 0 else RED
    ax1.annotate(f'Final: ${equity_s.iloc[-1]:,.2f} ({pct:+.2f}%)',
                 xy=(equity_s.index[-1], equity_s.iloc[-1]),
                 xytext=(-150, -25), textcoords='offset points',
                 color=col, fontsize=11, fontweight='bold',
                 arrowprops=dict(arrowstyle='->', color=col, lw=1.5))

    # ── Monthly Returns ───────────────────────────────────────
    if 'monthly_returns' in metrics and not metrics['monthly_returns'].empty:
        monthly = metrics['monthly_returns']
        cols_m  = [GREEN if v > 0 else RED for v in monthly.values]
        ax2.bar(range(len(monthly)), monthly.values, color=cols_m, alpha=0.85, width=0.7)
        ax2.set_title('Monthly P&L ($)', color=TEXT, fontsize=10, pad=8)
        ax2.set_xticks(range(len(monthly)))
        ax2.set_xticklabels([str(m)[-7:] for m in monthly.index],
                             rotation=45, ha='right', fontsize=6)
        ax2.axhline(0, color=MUTED, linewidth=0.8)
        ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'${x:.0f}'))

    # ── P&L Distribution ─────────────────────────────────────
    if not tdf.empty:
        wins_p = tdf[tdf['pnl_dollars'] > 0]['pnl_dollars']
        loss_p = tdf[tdf['pnl_dollars'] <= 0]['pnl_dollars']
        if len(wins_p): ax3.hist(wins_p, bins=20, color=GREEN, alpha=0.7,
                                 label=f'Wins ({len(wins_p)})', density=True)
        if len(loss_p): ax3.hist(loss_p, bins=20, color=RED,   alpha=0.7,
                                 label=f'Losses ({len(loss_p)})', density=True)
        ax3.axvline(0, color=MUTED, linewidth=1)
        ax3.set_title('P&L Distribution', color=TEXT, fontsize=10, pad=8)
        ax3.legend(fontsize=7, facecolor=PANEL, labelcolor=TEXT)

    # ── FTMO Pass Rate Gauge ──────────────────────────────────
    pr     = ftmo.get('pass_rate', 0)
    pc_col = GREEN if pr >= 65 else (GOLD if pr >= 45 else RED)
    theta  = np.linspace(0, np.pi, 100)
    ax4.plot(np.cos(theta), np.sin(theta), color='#30363d', linewidth=10)
    if pr > 0:
        tf = np.linspace(0, np.pi * pr / 100, 100)
        ax4.plot(np.cos(tf), np.sin(tf), color=pc_col, linewidth=10)
    ax4.set_xlim(-1.3, 1.3); ax4.set_ylim(-0.3, 1.2)
    ax4.set_aspect('equal'); ax4.axis('off')
    ax4.text(0,  0.38, f'{pr:.1f}%',     ha='center', color=pc_col, fontsize=28, fontweight='bold')
    ax4.text(0,  0.08, 'FTMO PASS RATE', ha='center', color=TEXT,   fontsize=9)
    ax4.text(0, -0.05, 'Unlimited Time', ha='center', color=GREEN,  fontsize=8, fontweight='bold')
    ax4.text(0, -0.18, f'{cfg["MC_SIMULATIONS"]:,} Monte Carlo Sims',
             ha='center', color=MUTED, fontsize=7)
    wks = ftmo.get('avg_weeks_to_pass', 0)
    if wks > 0:
        ax4.text(0, -0.28, f'Avg {wks:.1f} weeks to pass', ha='center', color=GOLD, fontsize=7)
    ax4.set_title('Challenge Probability (2026 Rules)', color=TEXT, fontsize=10, pad=8)

    # ── Drawdown ──────────────────────────────────────────────
    rm  = equity_s.cummax()
    dd  = (equity_s - rm) / rm * 100
    ax5.fill_between(dd.index, dd.values, 0, color=RED, alpha=0.6)
    ax5.plot(dd.index, dd.values, color=RED, linewidth=0.8)
    ax5.axhline(-cfg['FTMO_MAX_TOTAL_LOSS'], color=GOLD, linewidth=1.5, linestyle='--',
                label=f'Max Loss Limit (-{cfg["FTMO_MAX_TOTAL_LOSS"]}%)')
    ax5.axhline(-cfg['FTMO_MAX_DAILY_LOSS'], color=BLUE, linewidth=1,   linestyle=':',
                alpha=0.7, label=f'Daily Loss Limit (-{cfg["FTMO_MAX_DAILY_LOSS"]}%)')
    ax5.set_title('Drawdown (%)', color=TEXT, fontsize=10, pad=8)
    ax5.legend(fontsize=7, facecolor=PANEL, labelcolor=TEXT)

    # ── Trade Scatter ─────────────────────────────────────────
    if not tdf.empty:
        tc = [GREEN if p > 0 else RED for p in tdf['pnl_dollars']]
        ax6.scatter(range(len(tdf)), tdf['pnl_dollars'], c=tc, alpha=0.6, s=20)
        ax6.axhline(0, color=MUTED, linewidth=0.8)
        ax6t = ax6.twinx()
        ax6t.plot(range(len(tdf)), tdf['pnl_dollars'].cumsum(), color=GOLD, linewidth=1.5)
        ax6t.set_ylabel('Cumulative ($)', color=GOLD, fontsize=7)
        ax6t.tick_params(colors=GOLD, labelsize=7); ax6t.set_facecolor(PANEL)
        ax6.set_title('Trade P&L + Cumulative', color=TEXT, fontsize=10, pad=8)
        ax6.set_xlabel('Trade #', color=MUTED, fontsize=8)
        ax6.set_ylabel('P&L ($)', color=MUTED, fontsize=8)

    # ── Stats Table ───────────────────────────────────────────
    ax7.axis('off')
    def cv(v, g, b, hi=True):
        return GREEN if (v >= g if hi else v <= g) else (GOLD if (v >= b if hi else v <= b) else RED)

    rows = [
        ('── PERFORMANCE ──', '', BLUE),
        ('Total Trades',      str(metrics.get('total_trades', 0)),            TEXT),
        ('Win Rate',          f"{metrics.get('win_rate', 0):.1f}%",           cv(metrics.get('win_rate', 0), 40, 35)),
        ('Profit Factor',     f"{metrics.get('profit_factor', 0):.3f}",       cv(metrics.get('profit_factor', 0), 1.4, 1.2)),
        ('Actual RR',         f"{metrics.get('actual_rr', 0):.2f}:1",         cv(metrics.get('actual_rr', 0), 2.0, 1.5)),
        ('Net Profit',        f"${metrics.get('net_profit', 0):,.2f}",        GREEN if metrics.get('net_profit', 0) > 0 else RED),
        ('Net Profit %',      f"{metrics.get('net_profit_pct', 0):.2f}%",     GREEN if metrics.get('net_profit_pct', 0) > 0 else RED),
        ('Max Drawdown',      f"{metrics.get('max_dd_pct', 0):.2f}%",        cv(abs(metrics.get('max_dd_pct', 0)), 3, 8, False)),
        ('Consec. Losses',    str(metrics.get('max_consec_loss', 0)),          cv(metrics.get('max_consec_loss', 0), 5, 8, False)),
        ('Sharpe Ratio',      f"{metrics.get('sharpe', 0):.2f}",             cv(metrics.get('sharpe', 0), 1.5, 0.8)),
        ('── FTMO 2026 ──',  '', BLUE),
        ('Time Limit',        'NONE (Unlimited)',                              GREEN),
        ('Min Trading Days',  str(cfg['FTMO_MIN_DAYS']),                       GREEN),
        ('Profit Target',     f"${ftmo.get('profit_target', 0):,.0f} ({cfg['FTMO_PROFIT_TARGET']}%)", TEXT),
        ('Max Daily Loss',    f"${ftmo.get('max_daily_loss', 0):,.0f}",       TEXT),
        ('Best Day Limit',    f"${ftmo.get('best_day_limit', 0):,.0f}",       TEXT),
        ('Pass Rate',         f"{pr:.1f}%",                                    pc_col),
        ('Avg Weeks to Pass', f"{ftmo.get('avg_weeks_to_pass', 0):.1f} wks",  GOLD),
        ('Avg Final P&L',     f"${ftmo.get('avg_final_pnl', 0):,.2f}",       GREEN if ftmo.get('avg_final_pnl', 0) > 0 else RED),
    ]
    y = 0.99
    for label, val, col in rows:
        if val == '':
            ax7.text(0.02, y, label, transform=ax7.transAxes, color=BLUE, fontsize=8, fontweight='bold')
        else:
            ax7.text(0.02, y, label, transform=ax7.transAxes, color=MUTED, fontsize=8)
            ax7.text(0.98, y, val,   transform=ax7.transAxes, color=col,   fontsize=8,
                     fontweight='bold', ha='right')
        y -= 0.052

    fig.suptitle(f"{cfg['name']} — OB Strategy | FTMO 2026 Rules",
                 color=GOLD, fontsize=15, fontweight='bold', y=0.99)

    out = f"../results/reports/{cfg['slug']}_ob_report.png"
    plt.savefig(out, dpi=150, bbox_inches='tight', facecolor=BG)
    print(f"  Chart saved → {out}")
    plt.close()


# ══════════════════════════════════════════════════════════════════════════════
#  TERMINAL REPORT
# ══════════════════════════════════════════════════════════════════════════════
def print_report(metrics, ftmo, cfg):
    G = '\033[92m'; R = '\033[91m'; Y = '\033[93m'; B = '\033[94m'
    W = '\033[0m';  BOLD = '\033[1m'

    def c2(v, g, b, hi=True):
        return G if (v >= g if hi else v <= g) else (Y if (v >= b if hi else v <= b) else R)

    pr  = ftmo.get('pass_rate', 0)
    wr  = metrics.get('win_rate', 0)
    pf  = metrics.get('profit_factor', 0)
    rr  = metrics.get('actual_rr', 0)
    dd  = abs(metrics.get('max_dd_pct', 0))
    np_ = metrics.get('net_profit', 0)
    sh  = metrics.get('sharpe', 0)

    print(f"\n{BOLD}{'═'*58}{W}")
    print(f"{BOLD}{Y}  {cfg['name'].upper()} — OB BACKTEST REPORT{W}")
    print(f"{BOLD}{'═'*58}{W}")

    print(f"\n{B}  FTMO 2026 RULES APPLIED{W}")
    print(f"  Time Limit:          {G}NONE — Unlimited{W}")
    print(f"  Min Trading Days:    {G}{cfg['FTMO_MIN_DAYS']} days{W}")
    print(f"  Profit Target:       {cfg['FTMO_PROFIT_TARGET']}% (${cfg['INITIAL_CAPITAL']*cfg['FTMO_PROFIT_TARGET']/100:,.0f})")
    print(f"  Max Daily Loss:      {cfg['FTMO_MAX_DAILY_LOSS']}% (${cfg['INITIAL_CAPITAL']*cfg['FTMO_MAX_DAILY_LOSS']/100:,.0f})")
    print(f"  Max Total Loss:      {cfg['FTMO_MAX_TOTAL_LOSS']}% (${cfg['INITIAL_CAPITAL']*cfg['FTMO_MAX_TOTAL_LOSS']/100:,.0f})")
    print(f"  Best Day Rule:       Max ${ftmo.get('best_day_limit', 0):,.0f}/day")
    print(f"  Challenge Type:      {cfg['FTMO_PHASE']}")

    print(f"\n{B}  STRATEGY CONFIG{W}")
    print(f"  Swing Lookback:      {cfg['SWING_LOOKBACK']} bars each side")
    print(f"  OB Max Age:          {cfg['OB_MAX_AGE']} bars")
    print(f"  Risk:Reward:         1:{cfg['RR_RATIO']}")
    print(f"  HTF Bias EMA:        {cfg['HTF_EMA']}-period")
    print(f"  Session (GMT):       {cfg['SESSION_START']}:00 – {cfg['SESSION_END']}:00")

    print(f"\n{B}  PERFORMANCE{W}")
    print(f"  Total Trades:        {metrics.get('total_trades', 0)}")
    print(f"  Win Rate:            {c2(wr,40,35)}{wr:.1f}%{W}")
    print(f"  Profit Factor:       {c2(pf,1.4,1.2)}{pf:.3f}{W}")
    print(f"  Actual RR:           {c2(rr,2.0,1.5)}{rr:.2f}:1{W}")
    print(f"  Net Profit:          {G if np_>0 else R}${np_:,.2f} ({np_/cfg['INITIAL_CAPITAL']*100:+.2f}%){W}")
    print(f"  Avg Win:             {G}${metrics.get('avg_win', 0):,.2f}{W}")
    print(f"  Avg Loss:            {R}${metrics.get('avg_loss', 0):,.2f}{W}")
    print(f"  Max Drawdown:        {c2(dd,3,8,False)}{dd:.2f}%{W}")
    print(f"  Consec. Losses:      {metrics.get('max_consec_loss', 0)}")
    print(f"  Sharpe Ratio:        {c2(sh,1.5,0.8)}{sh:.2f}{W}")

    print(f"\n{B}  MONTHLY RETURNS{W}")
    if 'monthly_returns' in metrics:
        for m, v in metrics['monthly_returns'].items():
            bar = '█' * min(int(abs(v) / 20), 30)
            print(f"  {str(m)[-7:]}:  {G if v>0 else R}{bar} ${v:+.2f}{W}")

    print(f"\n{B}  FTMO 2026 MONTE CARLO ({cfg['MC_SIMULATIONS']:,} sims){W}")
    pc = G if pr >= 65 else (Y if pr >= 45 else R)
    print(f"  Pass Rate:           {pc}{BOLD}{pr:.1f}%{W}")
    print(f"  Passed:              {G}{ftmo.get('passes', 0):,}{W}")
    print(f"  Failed (Drawdown):   {R}{ftmo.get('fails_drawdown', 0):,}{W}")
    wks = ftmo.get('avg_weeks_to_pass', 0)
    if wks > 0:
        print(f"  Avg Weeks to Pass:   {Y}{wks:.1f} weeks{W}")
    print(f"  Avg Final P&L:       ${ftmo.get('avg_final_pnl', 0):,.2f}")

    print(f"\n{B}  FTMO READINESS{W}")
    checks = [
        ("Profit Factor > 1.3",      pf >= 1.3),
        ("Win Rate > 35%",           wr >= 35),
        ("Max DD < 8%",              dd < 8),
        ("Max DD < FTMO 10% limit",  dd < 10),
        ("Consec. Losses < 8",       metrics.get('max_consec_loss', 0) < 8),
        ("Positive Net Profit",      np_ > 0),
        ("Passes Monte Carlo > 50%", pr >= 50),
    ]
    for chk, ok in checks:
        print(f"  {G+'✓' if ok else R+'✗'}{W}  {chk}")

    score   = sum(1 for _, ok in checks if ok)
    verdict = (f"{G}{BOLD}READY for FTMO challenge!{W}"        if score >= 6 else
               f"{Y}{BOLD}ALMOST READY — strong foundation{W}" if score >= 5 else
               f"{Y}{BOLD}GOOD PROGRESS — keep refining{W}"    if score >= 4 else
               f"{R}{BOLD}NEEDS MORE WORK{W}")
    print(f"\n  Verdict: {verdict}")
    print(f"\n{'═'*58}\n")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    print(f"\n╔══════════════════════════════════════════════════════╗")
    print(f"║   OB Backtester — {ACTIVE_INSTRUMENT:<34}║")
    print(f"║   {CONFIG['name']:<52}║")
    print(f"╚══════════════════════════════════════════════════════╝\n")

    print("► Step 1: Loading data...")
    df = load_data(CONFIG['DATA_FILE'])

    print("\n► Step 2: Calculating indicators + swing structure...")
    df = add_indicators(df, CONFIG)
    print(f"  {df['is_swing_high'].sum()} swing highs | {df['is_swing_low'].sum()} swing lows")

    print("\n► Step 3: Running backtest...")
    tdf, equity_s = run_backtest(df, CONFIG)
    if tdf.empty:
        print("  No trades. Try adjusting SWING_LOOKBACK or OB_MAX_AGE in config.py.")
        return
    longs  = (tdf['direction'] == 'long').sum()
    shorts = (tdf['direction'] == 'short').sum()
    print(f"  {len(tdf)} trades ({longs} longs, {shorts} shorts)")

    print("\n► Step 4: Analysing performance...")
    metrics = analyze_performance(tdf, equity_s, CONFIG)

    print("\n► Step 5: Running FTMO 2026 Monte Carlo...")
    ftmo = simulate_ftmo_2026(tdf, CONFIG)

    print("\n► Step 6: Generating chart...")
    plot_results(tdf, equity_s, metrics, ftmo, CONFIG)

    print_report(metrics, ftmo, CONFIG)

    trades_out = f"../results/trades/{CONFIG['slug']}_ob_trades.csv"
    tdf.to_csv(trades_out, index=False)
    print(f"  Trade log → {trades_out}\n")


if __name__ == '__main__':
    main()
