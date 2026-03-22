"""
╔══════════════════════════════════════════════════════════════╗
║   GOLD V3 — Trend Pullback Backtester                       ║
║   With Real Lot Sizing + FTMO 2026 Challenge Simulator       ║
║   Strategy: EMA Trend + EMA8 Pullback + Rejection Candle    ║
╚══════════════════════════════════════════════════════════════╝

FTMO 2026 RULES (Updated):
  - NO time limit (unlimited trading period)
  - Minimum 2 trading days only
  - 10% profit target
  - 5% max daily loss
  - 10% max total loss
  - Best Day Rule: no single day > 50% of profit target
  - EAs and bots are allowed

HOW TO USE WITH REAL DATA:
1. On TradingView → XAUUSD 1H chart
2. Click Export Data → ISO format
3. Save as CSV
4. Change DATA_FILE below to your CSV path
5. Run: python3 gold_v3_backtest.py
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
CONFIG = {
    # ── Data ──────────────────────────────────────────────────
    "DATA_FILE"           : "xauusd_1h.csv.csv",   # None = use synthetic data

    # ── Account ───────────────────────────────────────────────
    "INITIAL_CAPITAL"     : 10_000,
    "RISK_PCT"            : 1.0,           # % risk per trade
    "LOT_SIZE_UNIT"       : 0.01,          # 0.01 lots = $1/point on Gold
    "POINT_VALUE"         : 1.0,

    # ── Strategy — EMA ────────────────────────────────────────
    "EMA_FAST"            : 21,
    "EMA_SLOW"            : 50,
    "EMA_PB"              : 8,

    # ── Strategy — Entry ──────────────────────────────────────
    "ATR_SL_MULT"         : 1.2,
    "RR_RATIO"            : 2.5,
    "MIN_CANDLE_BODY"     : 0.5,
    "RSI_LEN"             : 14,
    "RSI_BULL_MIN"        : 45,
    "RSI_BULL_MAX"        : 70,
    "RSI_BEAR_MIN"        : 30,
    "RSI_BEAR_MAX"        : 55,

    # ── Strategy — Session (GMT) ───────────────────────────────
    "SESSION_START"       : 7,
    "SESSION_END"         : 16,

    # ── Risk Management ───────────────────────────────────────
    "MAX_TRADES_DAY"      : 2,
    "BREAKEVEN_AT_1R"     : True,
    "TRAILING_AFTER_BE"   : True,

    # ── FTMO 2026 Rules ───────────────────────────────────────
    # Source: ftmo.com (confirmed March 2026)
    "FTMO_PROFIT_TARGET"  : 10.0,     # 10% profit target
    "FTMO_MAX_DAILY_LOSS" : 5.0,      # 5% max daily loss
    "FTMO_MAX_TOTAL_LOSS" : 10.0,     # 10% max total loss
    "FTMO_MIN_DAYS"       : 2,        # minimum 2 trading days (free trial)
    "FTMO_TIME_LIMIT"     : None,     # NO time limit in 2026
    "FTMO_BEST_DAY_RULE"  : 50.0,     # single day cannot be >50% of profit target
    "FTMO_PHASE"          : "1-Step", # 1-Step or 2-Step

    # ── Monte Carlo ───────────────────────────────────────────
    "MC_SIMULATIONS"      : 1000,
    "MC_MAX_TRADES"       : 300,      # max trades to simulate per run (no time limit)
}


# ═══════════════════════════════════════════════════════════════
#  DATA LOADER
# ═══════════════════════════════════════════════════════════════
def generate_gold_data(n_days=600):
    print("  Generating synthetic Gold data...")
    np.random.seed(42)
    n_bars         = n_days * 24
    price          = 2000.0
    prices         = []
    trend          = 0.008
    vol            = 3.5
    vol_regime     = 1.0
    regime_counter = 0
    trend_dir      = 1
    trend_length   = 0

    for i in range(n_bars):
        regime_counter += 1
        if regime_counter > np.random.randint(80, 200):
            vol_regime     = np.random.choice([0.7,1.0,1.4,1.8], p=[0.2,0.4,0.3,0.1])
            regime_counter = 0
        trend_length += 1
        if trend_length > np.random.randint(60, 250):
            trend_dir    *= -1
            trend_length  = 0
        ret   = np.random.normal(trend * trend_dir * 2.0, vol * vol_regime)
        price = max(1800, min(3200, price + ret))
        prices.append(price)

    start  = datetime(2024, 1, 2, 0, 0)
    times  = [start + timedelta(hours=i) for i in range(n_bars)]
    closes = np.array(prices)
    highs  = closes + np.abs(np.random.normal(0, vol * 0.8, n_bars))
    lows   = closes - np.abs(np.random.normal(0, vol * 0.8, n_bars))
    opens  = np.roll(closes, 1); opens[0] = closes[0]

    df = pd.DataFrame({'open':opens,'high':highs,'low':lows,'close':closes,
                       'volume':np.random.randint(1000,50000,n_bars)}, index=times)
    df.index.name = 'datetime'
    return df


def load_data(filepath=None):
    if filepath:
        print(f"  Loading real data from {filepath}...")
        df = pd.read_csv(filepath)
        df.columns = [c.lower().strip() for c in df.columns]
        time_col = next((c for c in df.columns if 'time' in c or 'date' in c), None)
        if time_col:
            df['datetime'] = pd.to_datetime(df[time_col], utc=True).dt.tz_localize(None)
            df.set_index('datetime', inplace=True)
            df.sort_index(inplace=True)
        col_map = {}
        for c in df.columns:
            if 'open'  in c: col_map[c] = 'open'
            elif 'high'  in c: col_map[c] = 'high'
            elif 'low'   in c: col_map[c] = 'low'
            elif 'close' in c: col_map[c] = 'close'
            elif 'vol'   in c: col_map[c] = 'volume'
        df.rename(columns=col_map, inplace=True)
        available = [c for c in ['open','high','low','close','volume'] if c in df.columns]
        df = df[available].apply(pd.to_numeric, errors='coerce').dropna()
        if 'volume' not in df.columns:
            df['volume'] = 1000
        print(f"  Loaded {len(df):,} bars | {df.index[0].date()} → {df.index[-1].date()}")
        return df
    return generate_gold_data()


# ═══════════════════════════════════════════════════════════════
#  INDICATORS
# ═══════════════════════════════════════════════════════════════
def add_indicators(df, cfg):
    c, h, l, o = df['close'], df['high'], df['low'], df['open']

    df['ema_fast'] = c.ewm(span=cfg['EMA_FAST'], adjust=False).mean()
    df['ema_slow'] = c.ewm(span=cfg['EMA_SLOW'], adjust=False).mean()
    df['ema_pb']   = c.ewm(span=cfg['EMA_PB'],   adjust=False).mean()

    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()

    delta = c.diff()
    gain  = delta.clip(lower=0).rolling(cfg['RSI_LEN']).mean()
    loss  = (-delta.clip(upper=0)).rolling(cfg['RSI_LEN']).mean()
    df['rsi'] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))

    df['body']       = (c - o).abs()
    df['upper_wick'] = h - pd.concat([c, o], axis=1).max(axis=1)
    df['lower_wick'] = pd.concat([c, o], axis=1).min(axis=1) - l

    df['bull_trend']   = (df['ema_fast'] > df['ema_slow']) & (c > df['ema_slow'])
    df['bear_trend']   = (df['ema_fast'] < df['ema_slow']) & (c < df['ema_slow'])
    df['trend_strong'] = (df['ema_fast'] - df['ema_slow']).abs() > df['atr'] * 0.3

    df['pb_touch_bull'] = (l <= df['ema_pb']) & (c > df['ema_pb'])
    df['pb_touch_bear'] = (h >= df['ema_pb']) & (c < df['ema_pb'])

    swing_h = h.rolling(20).max()
    swing_l = l.rolling(20).min()
    swing_s = (swing_h - swing_l).clip(lower=0.01)
    df['pb_deep_bull'] = (swing_h - l) / swing_s >= 0.25
    df['pb_deep_bear'] = (h - swing_l) / swing_s >= 0.25

    min_body = df['atr'] * cfg['MIN_CANDLE_BODY']
    bull_rej = (df['lower_wick'] >= df['body']*1.5) & (c > (h+l)/2) & (df['body'] >= min_body)
    bull_eng = (c > o) & (c > o.shift()) & (o < c.shift()) & (df['body'] >= min_body)
    bear_rej = (df['upper_wick'] >= df['body']*1.5) & (c < (h+l)/2) & (df['body'] >= min_body)
    bear_eng = (c < o) & (c < o.shift()) & (o > c.shift()) & (df['body'] >= min_body)
    df['bull_candle'] = bull_rej | bull_eng
    df['bear_candle'] = bear_rej | bear_eng

    df['hour_gmt']   = df.index.hour
    df['in_session'] = (df['hour_gmt'] >= cfg['SESSION_START']) & \
                       (df['hour_gmt'] < cfg['SESSION_END'])
    df['rsi_ok_l']   = (df['rsi'] > cfg['RSI_BULL_MIN']) & (df['rsi'] < cfg['RSI_BULL_MAX'])
    df['rsi_ok_s']   = (df['rsi'] > cfg['RSI_BEAR_MIN']) & (df['rsi'] < cfg['RSI_BEAR_MAX'])

    df['long_signal']  = (df['bull_trend'] & df['trend_strong'] & df['pb_touch_bull'] &
                          df['pb_deep_bull'] & df['bull_candle'] & df['in_session'] & df['rsi_ok_l'])
    df['short_signal'] = (df['bear_trend'] & df['trend_strong'] & df['pb_touch_bear'] &
                          df['pb_deep_bear'] & df['bear_candle'] & df['in_session'] & df['rsi_ok_s'])
    return df.dropna()


# ═══════════════════════════════════════════════════════════════
#  BACKTESTER
# ═══════════════════════════════════════════════════════════════
def run_backtest(df, cfg):
    capital      = cfg['INITIAL_CAPITAL']
    trades       = []
    equity_curve = [capital]
    equity_dates = [df.index[0]]
    position     = None
    trades_today = 0
    last_date    = None

    for i in range(50, len(df)):
        row  = df.iloc[i]
        date = df.index[i].date()

        if date != last_date:
            trades_today = 0
            last_date    = date

        if position is not None:
            closed  = False
            pnl_pts = 0
            reason  = ''

            if position['dir'] == 'long':
                if row['low'] <= position['sl']:
                    pnl_pts = position['sl'] - position['entry']; closed=True; reason='SL'
                elif row['high'] >= position['tp']:
                    pnl_pts = position['tp'] - position['entry']; closed=True; reason='TP'
                else:
                    if cfg['BREAKEVEN_AT_1R'] and not position['be']:
                        if row['high'] >= position['entry'] + position['sl_dist']:
                            position['sl'] = position['entry'] + 0.5
                            position['be'] = True
                    if cfg['TRAILING_AFTER_BE'] and position['be']:
                        new_sl = row['close'] - row['atr'] * cfg['ATR_SL_MULT']
                        if new_sl > position['sl']:
                            position['sl'] = new_sl
            else:
                if row['high'] >= position['sl']:
                    pnl_pts = position['entry'] - position['sl']; closed=True; reason='SL'
                elif row['low'] <= position['tp']:
                    pnl_pts = position['entry'] - position['tp']; closed=True; reason='TP'
                else:
                    if cfg['BREAKEVEN_AT_1R'] and not position['be']:
                        if row['low'] <= position['entry'] - position['sl_dist']:
                            position['sl'] = position['entry'] - 0.5
                            position['be'] = True
                    if cfg['TRAILING_AFTER_BE'] and position['be']:
                        new_sl = row['close'] + row['atr'] * cfg['ATR_SL_MULT']
                        if new_sl < position['sl']:
                            position['sl'] = new_sl

            if row['hour_gmt'] >= cfg['SESSION_END'] and not closed:
                pnl_pts = (row['close']-position['entry']) if position['dir']=='long' \
                          else (position['entry']-row['close'])
                closed=True; reason='SessionEnd'

            if closed:
                pnl_usd  = pnl_pts * (position['lots'] / cfg['LOT_SIZE_UNIT']) * cfg['POINT_VALUE']
                capital += pnl_usd
                trades.append({
                    'entry_time'  : position['entry_time'],
                    'exit_time'   : df.index[i],
                    'direction'   : position['dir'],
                    'entry_price' : position['entry'],
                    'exit_price'  : (position['sl'] if reason=='SL' else
                                    position['tp'] if reason=='TP' else row['close']),
                    'sl'          : position['sl'],
                    'tp'          : position['tp'],
                    'lots'        : position['lots'],
                    'pnl_points'  : pnl_pts,
                    'pnl_dollars' : pnl_usd,
                    'reason'      : reason,
                    'capital'     : capital,
                    'be_moved'    : position['be'],
                })
                position = None

        equity_curve.append(capital)
        equity_dates.append(df.index[i])

        if position is None and trades_today < cfg['MAX_TRADES_DAY']:
            for sig, direction in [('long_signal','long'), ('short_signal','short')]:
                if row[sig]:
                    sl_dist = row['atr'] * cfg['ATR_SL_MULT']
                    sl  = row['close'] - sl_dist if direction=='long' else row['close'] + sl_dist
                    tp  = row['close'] + sl_dist * cfg['RR_RATIO'] if direction=='long' \
                          else row['close'] - sl_dist * cfg['RR_RATIO']
                    risk = capital * (cfg['RISK_PCT']/100)
                    lots = max(0.01, round(risk / (sl_dist * (1/cfg['LOT_SIZE_UNIT']) * cfg['POINT_VALUE']), 2))
                    position = {'dir':direction, 'entry':row['close'], 'entry_time':df.index[i],
                                'sl':sl, 'tp':tp, 'sl_dist':sl_dist, 'lots':lots, 'be':False}
                    trades_today += 1
                    break

    return pd.DataFrame(trades), pd.Series(equity_curve, index=equity_dates)


# ═══════════════════════════════════════════════════════════════
#  PERFORMANCE METRICS
# ═══════════════════════════════════════════════════════════════
def analyze_performance(tdf, equity_s, cfg):
    if tdf.empty:
        return {}
    wins = tdf[tdf['pnl_dollars'] > 0]
    loss = tdf[tdf['pnl_dollars'] <= 0]
    gp   = wins['pnl_dollars'].sum()
    gl   = loss['pnl_dollars'].sum()
    pf   = abs(gp/gl) if gl != 0 else 999
    wr   = len(wins)/len(tdf)*100
    np_  = tdf['pnl_dollars'].sum()
    aw   = wins['pnl_dollars'].mean() if len(wins) else 0
    al   = loss['pnl_dollars'].mean() if len(loss) else 0
    rr   = abs(aw/al) if al != 0 else 0

    rm   = equity_s.cummax()
    dd   = ((equity_s - rm)/rm*100)
    mdd  = dd.min()
    mdd_d = (equity_s - rm).min()

    consec=0; max_c=0
    for r in (tdf['pnl_dollars'] > 0):
        consec = 0 if r else consec+1
        max_c  = max(max_c, consec)

    tdf = tdf.copy()
    tdf['month']  = pd.to_datetime(tdf['exit_time']).dt.to_period('M')
    monthly       = tdf.groupby('month')['pnl_dollars'].sum()
    dr            = equity_s.resample('D').last().pct_change().dropna()
    sharpe        = dr.mean()/dr.std()*np.sqrt(252) if dr.std()>0 else 0

    return {
        'total_trades': len(tdf), 'win_rate': wr, 'profit_factor': pf,
        'net_profit': np_, 'net_profit_pct': np_/cfg['INITIAL_CAPITAL']*100,
        'gross_profit': gp, 'gross_loss': gl, 'avg_win': aw, 'avg_loss': al,
        'actual_rr': rr, 'max_dd_pct': mdd, 'max_dd_dollar': mdd_d,
        'max_consec_loss': max_c, 'monthly_returns': monthly, 'sharpe': sharpe,
        'winners': len(wins), 'losers': len(loss),
    }


# ═══════════════════════════════════════════════════════════════
#  FTMO 2026 MONTE CARLO SIMULATOR
#  Key changes vs old version:
#  - NO time limit (unlimited trades until target hit or DD breach)
#  - Min 2 trading days (not 4)
#  - Best Day Rule: no day > 50% of profit target
#  - Simulates realistic trade frequency from real backtest data
# ═══════════════════════════════════════════════════════════════
def simulate_ftmo_2026(tdf, cfg):
    if tdf.empty:
        return {}

    print("\n  Running FTMO 2026 Monte Carlo (unlimited time)...")

    cap0       = cfg['INITIAL_CAPITAL']
    target     = cap0 * cfg['FTMO_PROFIT_TARGET']  / 100   # $1,000 on $10k
    max_dd_lim = cap0 * cfg['FTMO_MAX_TOTAL_LOSS']  / 100   # $1,000
    max_dy_lim = cap0 * cfg['FTMO_MAX_DAILY_LOSS']  / 100   # $500
    best_day_max = target * cfg['FTMO_BEST_DAY_RULE'] / 100  # $500 (50% of target)
    min_days   = cfg['FTMO_MIN_DAYS']                         # 2 days
    max_trades = cfg['MC_SIMULATIONS']

    pnl_seq    = tdf['pnl_dollars'].values
    n          = len(pnl_seq)

    passes       = 0
    f_dd         = 0
    f_best_day   = 0
    finals       = []
    trades_to_pass_list = []

    for _ in range(cfg['MC_SIMULATIONS']):
        bal         = cap0
        failed      = False
        passed      = False
        trade_days  = {}    # day_number → daily_pnl
        trade_count = 0
        day_counter = 0

        # Simulate trades one by one — no time limit
        # Stop only when: target hit OR drawdown breached OR max sim trades reached
        while trade_count < cfg['MC_MAX_TRADES']:
            # Pick a random trade from real history
            pnl = float(np.random.choice(pnl_seq))

            # Assign to a trading day (sequential days)
            if trade_count % 2 == 0:  # ~2 trades per day based on our backtest
                day_counter += 1
            trade_day = day_counter
            trade_days[trade_day] = trade_days.get(trade_day, 0) + pnl

            # ── Check Best Day Rule ──────────────────────────
            if trade_days[trade_day] > best_day_max:
                # Not a failure — just means this day's profit is too high
                # to count as valid completion. We continue trading.
                pass

            bal += pnl
            trade_count += 1

            # ── Check Max Daily Loss ─────────────────────────
            if trade_days[trade_day] < -max_dy_lim:
                failed = True
                f_dd  += 1
                break

            # ── Check Max Total Loss ─────────────────────────
            if (cap0 - bal) >= max_dd_lim:
                failed = True
                f_dd  += 1
                break

            # ── Check Profit Target + Min Days ───────────────
            profit = bal - cap0
            trading_days_count = len(trade_days)

            if profit >= target and trading_days_count >= min_days:
                # Verify Best Day Rule
                max_single_day = max(trade_days.values())
                if max_single_day <= best_day_max:
                    passed = True
                    passes += 1
                    trades_to_pass_list.append(trade_count)
                    break
                # If best day rule violated, keep trading to dilute it

        if not passed and not failed:
            # Ran out of simulated trades — inconclusive
            pass

        finals.append(bal - cap0)

    pass_rate    = passes / cfg['MC_SIMULATIONS'] * 100
    avg_trades_to_pass = np.mean(trades_to_pass_list) if trades_to_pass_list else 0
    # Convert trades to estimated weeks (5-6 trades/week from our backtest)
    trades_per_week    = n / ((pd.to_datetime(tdf['exit_time'].iloc[-1]) -
                               pd.to_datetime(tdf['entry_time'].iloc[0])).days / 7)
    avg_weeks_to_pass  = avg_trades_to_pass / max(trades_per_week, 1) if avg_trades_to_pass > 0 else 0

    return {
        'pass_rate'          : pass_rate,
        'passes'             : passes,
        'fails_drawdown'     : f_dd,
        'fails_best_day'     : f_best_day,
        'avg_final_pnl'      : np.mean(finals),
        'avg_trades_to_pass' : avg_trades_to_pass,
        'avg_weeks_to_pass'  : avg_weeks_to_pass,
        'simulations'        : cfg['MC_SIMULATIONS'],
        'best_day_limit'     : best_day_max,
        'profit_target'      : target,
        'max_daily_loss'     : max_dy_lim,
        'max_total_loss'     : max_dd_lim,
    }


# ═══════════════════════════════════════════════════════════════
#  VISUALIZATION
# ═══════════════════════════════════════════════════════════════
def plot_results(tdf, equity_s, metrics, ftmo, cfg):
    BG='#0d1117'; PANEL='#161b22'; TEXT='#e6edf3'; MUTED='#8b949e'
    GOLD='#FFD700'; GREEN='#00ff88'; RED='#ff4444'; BLUE='#4488ff'

    fig = plt.figure(figsize=(22, 14), facecolor=BG)
    gs  = gridspec.GridSpec(3, 3, figure=fig, hspace=0.45, wspace=0.35)
    ax1 = fig.add_subplot(gs[0, :])
    ax2 = fig.add_subplot(gs[1, 0])
    ax3 = fig.add_subplot(gs[1, 1])
    ax4 = fig.add_subplot(gs[1, 2])
    ax5 = fig.add_subplot(gs[2, 0])
    ax6 = fig.add_subplot(gs[2, 1])
    ax7 = fig.add_subplot(gs[2, 2])

    for ax in [ax1,ax2,ax3,ax4,ax5,ax6,ax7]:
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=MUTED, labelsize=8)
        for s in ax.spines.values(): s.set_color('#30363d')

    # ── Equity Curve ─────────────────────────────────────────
    ax1.plot(equity_s.index, equity_s.values, color=GOLD, linewidth=2)
    ax1.fill_between(equity_s.index, equity_s.values, cfg['INITIAL_CAPITAL'],
                     alpha=0.15, color=GREEN if equity_s.iloc[-1]>cfg['INITIAL_CAPITAL'] else RED)
    ax1.axhline(cfg['INITIAL_CAPITAL'], color=MUTED, linewidth=1, linestyle='--', alpha=0.5)

    # FTMO target and loss lines
    ftmo_target = cfg['INITIAL_CAPITAL'] * (1 + cfg['FTMO_PROFIT_TARGET']/100)
    ftmo_loss   = cfg['INITIAL_CAPITAL'] * (1 - cfg['FTMO_MAX_TOTAL_LOSS']/100)
    ax1.axhline(ftmo_target, color=GREEN, linewidth=1, linestyle=':', alpha=0.7,
                label=f"FTMO Target (+{cfg['FTMO_PROFIT_TARGET']}%)")
    ax1.axhline(ftmo_loss,   color=RED,   linewidth=1, linestyle=':', alpha=0.7,
                label=f"FTMO Max Loss (-{cfg['FTMO_MAX_TOTAL_LOSS']}%)")
    ax1.legend(fontsize=7, facecolor=PANEL, labelcolor=TEXT, loc='upper left')
    ax1.set_title('Equity Curve — GOLD V3 | Real XAUUSD (Jan 2024 – Mar 2026)',
                  color=TEXT, fontsize=13, pad=10)
    ax1.set_ylabel('Capital ($)', color=MUTED, fontsize=9)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x,_: f'${x:,.0f}'))
    pct = (equity_s.iloc[-1]-cfg['INITIAL_CAPITAL'])/cfg['INITIAL_CAPITAL']*100
    col = GREEN if pct>0 else RED
    ax1.annotate(f'Final: ${equity_s.iloc[-1]:,.2f} ({pct:+.2f}%)',
                 xy=(equity_s.index[-1], equity_s.iloc[-1]),
                 xytext=(-150,-25), textcoords='offset points',
                 color=col, fontsize=11, fontweight='bold',
                 arrowprops=dict(arrowstyle='->', color=col, lw=1.5))

    # ── Monthly Returns ───────────────────────────────────────
    if 'monthly_returns' in metrics and not metrics['monthly_returns'].empty:
        monthly = metrics['monthly_returns']
        cols_m  = [GREEN if v>0 else RED for v in monthly.values]
        ax2.bar(range(len(monthly)), monthly.values, color=cols_m, alpha=0.85, width=0.7)
        ax2.set_title('Monthly P&L ($)', color=TEXT, fontsize=10, pad=8)
        ax2.set_xticks(range(len(monthly)))
        ax2.set_xticklabels([str(m)[-7:] for m in monthly.index],
                             rotation=45, ha='right', fontsize=6)
        ax2.axhline(0, color=MUTED, linewidth=0.8)
        ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x,_: f'${x:.0f}'))

    # ── P&L Distribution ─────────────────────────────────────
    if not tdf.empty:
        wins_p = tdf[tdf['pnl_dollars']>0]['pnl_dollars']
        loss_p = tdf[tdf['pnl_dollars']<=0]['pnl_dollars']
        if len(wins_p)>0: ax3.hist(wins_p, bins=30, color=GREEN, alpha=0.7,
                                    label=f'Wins ({len(wins_p)})', density=True)
        if len(loss_p)>0: ax3.hist(loss_p, bins=30, color=RED,   alpha=0.7,
                                    label=f'Losses ({len(loss_p)})', density=True)
        ax3.axvline(0, color=MUTED, linewidth=1)
        ax3.set_title('P&L Distribution', color=TEXT, fontsize=10, pad=8)
        ax3.legend(fontsize=7, facecolor=PANEL, labelcolor=TEXT)

    # ── FTMO Pass Rate Gauge ──────────────────────────────────
    pr     = ftmo.get('pass_rate', 0)
    pc_col = GREEN if pr>=65 else (GOLD if pr>=45 else RED)
    theta  = np.linspace(0, np.pi, 100)
    ax4.plot(np.cos(theta), np.sin(theta), color='#30363d', linewidth=10)
    if pr > 0:
        tf = np.linspace(0, np.pi*pr/100, 100)
        ax4.plot(np.cos(tf), np.sin(tf), color=pc_col, linewidth=10)
    ax4.set_xlim(-1.3,1.3); ax4.set_ylim(-0.3,1.2)
    ax4.set_aspect('equal'); ax4.axis('off')
    ax4.text(0, 0.38, f'{pr:.1f}%',    ha='center', color=pc_col,  fontsize=28, fontweight='bold')
    ax4.text(0, 0.08, 'FTMO PASS RATE',ha='center', color=TEXT,    fontsize=9)
    ax4.text(0,-0.05, 'Unlimited Time', ha='center', color=GREEN,   fontsize=8, fontweight='bold')
    ax4.text(0,-0.18, f'{cfg["MC_SIMULATIONS"]:,} Monte Carlo Sims',
             ha='center', color=MUTED, fontsize=7)
    wks = ftmo.get('avg_weeks_to_pass', 0)
    if wks > 0:
        ax4.text(0,-0.28, f'Avg {wks:.1f} weeks to pass',
                 ha='center', color=GOLD, fontsize=7)
    ax4.set_title('Challenge Probability (2026 Rules)', color=TEXT, fontsize=10, pad=8)

    # ── Drawdown ──────────────────────────────────────────────
    rm  = equity_s.cummax()
    dd  = (equity_s - rm)/rm*100
    ax5.fill_between(dd.index, dd.values, 0, color=RED, alpha=0.6)
    ax5.plot(dd.index, dd.values, color=RED, linewidth=0.8)
    ax5.axhline(-cfg['FTMO_MAX_TOTAL_LOSS'], color=GOLD, linewidth=1.5,
                linestyle='--', label=f'Max Loss Limit (-{cfg["FTMO_MAX_TOTAL_LOSS"]}%)')
    ax5.axhline(-cfg['FTMO_MAX_DAILY_LOSS'], color=BLUE, linewidth=1,
                linestyle=':', alpha=0.7, label=f'Daily Loss Limit (-{cfg["FTMO_MAX_DAILY_LOSS"]}%)')
    ax5.set_title('Drawdown (%)', color=TEXT, fontsize=10, pad=8)
    ax5.legend(fontsize=7, facecolor=PANEL, labelcolor=TEXT)

    # ── Trade Scatter ─────────────────────────────────────────
    if not tdf.empty:
        tc = [GREEN if p>0 else RED for p in tdf['pnl_dollars']]
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
        return GREEN if (v>=g if hi else v<=g) else (GOLD if (v>=b if hi else v<=b) else RED)

    rows = [
        ('── PERFORMANCE ──',   '',    BLUE),
        ('Total Trades',        str(metrics.get('total_trades',0)), TEXT),
        ('Win Rate',            f"{metrics.get('win_rate',0):.1f}%",    cv(metrics.get('win_rate',0),50,45)),
        ('Profit Factor',       f"{metrics.get('profit_factor',0):.3f}",cv(metrics.get('profit_factor',0),1.4,1.2)),
        ('Actual RR',           f"{metrics.get('actual_rr',0):.2f}:1",  cv(metrics.get('actual_rr',0),1.8,1.4)),
        ('Net Profit',          f"${metrics.get('net_profit',0):,.2f}",  GREEN if metrics.get('net_profit',0)>0 else RED),
        ('Net Profit %',        f"{metrics.get('net_profit_pct',0):.2f}%", GREEN if metrics.get('net_profit_pct',0)>0 else RED),
        ('Max Drawdown',        f"{metrics.get('max_dd_pct',0):.2f}%",  cv(abs(metrics.get('max_dd_pct',0)),3,8,False)),
        ('Consec. Losses',      str(metrics.get('max_consec_loss',0)),   cv(metrics.get('max_consec_loss',0),5,8,False)),
        ('Sharpe Ratio',        f"{metrics.get('sharpe',0):.2f}",        cv(metrics.get('sharpe',0),1.5,0.8)),
        ('── FTMO 2026 ──',     '',    BLUE),
        ('Time Limit',          'NONE (Unlimited)',  GREEN),
        ('Min Trading Days',    str(cfg['FTMO_MIN_DAYS']),  GREEN),
        ('Profit Target',       f"${ftmo.get('profit_target',0):,.0f} ({cfg['FTMO_PROFIT_TARGET']}%)", TEXT),
        ('Max Daily Loss',      f"${ftmo.get('max_daily_loss',0):,.0f}", TEXT),
        ('Best Day Limit',      f"${ftmo.get('best_day_limit',0):,.0f}", TEXT),
        ('Pass Rate',           f"{pr:.1f}%",  pc_col),
        ('Avg Weeks to Pass',   f"{ftmo.get('avg_weeks_to_pass',0):.1f} weeks", GOLD),
        ('Avg Final P&L',       f"${ftmo.get('avg_final_pnl',0):,.2f}",  GREEN if ftmo.get('avg_final_pnl',0)>0 else RED),
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

    fig.suptitle('GOLD V3 — FTMO 2026 Rules | No Time Limit | Real XAUUSD Backtest',
                 color=GOLD, fontsize=15, fontweight='bold', y=0.99)
    plt.savefig('gold_v3_report.png', dpi=150, bbox_inches='tight', facecolor=BG)
    print("  Chart saved → gold_v3_report.png")
    plt.close()


# ═══════════════════════════════════════════════════════════════
#  PRINT REPORT
# ═══════════════════════════════════════════════════════════════
def print_report(metrics, ftmo, cfg):
    G='\033[92m'; R='\033[91m'; Y='\033[93m'; B='\033[94m'; W='\033[0m'; BOLD='\033[1m'
    def c2(v,g,b,hi=True):
        return G if (v>=g if hi else v<=g) else (Y if (v>=b if hi else v<=b) else R)

    pr  = ftmo.get('pass_rate', 0)
    wr  = metrics.get('win_rate', 0)
    pf  = metrics.get('profit_factor', 0)
    rr  = metrics.get('actual_rr', 0)
    dd  = abs(metrics.get('max_dd_pct', 0))
    np_ = metrics.get('net_profit', 0)
    sh  = metrics.get('sharpe', 0)

    print(f"\n{BOLD}{'═'*58}{W}")
    print(f"{BOLD}{Y}  GOLD V3 — FTMO 2026 BACKTEST REPORT{W}")
    print(f"{BOLD}{'═'*58}{W}")

    print(f"\n{B}  FTMO 2026 RULES APPLIED{W}")
    print(f"  Time Limit:          {G}NONE — Unlimited trading period{W}")
    print(f"  Min Trading Days:    {G}{cfg['FTMO_MIN_DAYS']} days{W}")
    print(f"  Profit Target:       {cfg['FTMO_PROFIT_TARGET']}% (${cfg['INITIAL_CAPITAL']*cfg['FTMO_PROFIT_TARGET']/100:,.0f})")
    print(f"  Max Daily Loss:      {cfg['FTMO_MAX_DAILY_LOSS']}% (${cfg['INITIAL_CAPITAL']*cfg['FTMO_MAX_DAILY_LOSS']/100:,.0f})")
    print(f"  Max Total Loss:      {cfg['FTMO_MAX_TOTAL_LOSS']}% (${cfg['INITIAL_CAPITAL']*cfg['FTMO_MAX_TOTAL_LOSS']/100:,.0f})")
    print(f"  Best Day Rule:       Max ${ftmo.get('best_day_limit',0):,.0f}/day ({cfg['FTMO_BEST_DAY_RULE']}% of target)")
    print(f"  Challenge Type:      {cfg['FTMO_PHASE']}")

    print(f"\n{B}  STRATEGY PERFORMANCE{W}")
    print(f"  Total Trades:        {metrics.get('total_trades',0)}")
    print(f"  Win Rate:            {c2(wr,50,45)}{wr:.1f}%{W}")
    print(f"  Profit Factor:       {c2(pf,1.4,1.2)}{pf:.3f}{W}")
    print(f"  Actual RR:           {c2(rr,1.8,1.4)}{rr:.2f}:1{W}")
    print(f"  Net Profit:          {G if np_>0 else R}${np_:,.2f} ({np_/cfg['INITIAL_CAPITAL']*100:+.2f}%){W}")
    print(f"  Avg Win:             {G}${metrics.get('avg_win',0):,.2f}{W}")
    print(f"  Avg Loss:            {R}${metrics.get('avg_loss',0):,.2f}{W}")
    print(f"  Max Drawdown:        {c2(dd,3,8,False)}{dd:.2f}% (${abs(metrics.get('max_dd_dollar',0)):,.2f}){W}")
    print(f"  Consec. Losses:      {metrics.get('max_consec_loss',0)}")
    print(f"  Sharpe Ratio:        {c2(sh,1.5,0.8)}{sh:.2f}{W}")

    print(f"\n{B}  MONTHLY RETURNS{W}")
    if 'monthly_returns' in metrics:
        for m, v in metrics['monthly_returns'].items():
            bar = '█' * min(int(abs(v)/20), 30)
            print(f"  {str(m)[-7:]}:  {G if v>0 else R}{bar} ${v:+.2f}{W}")

    print(f"\n{B}  FTMO 2026 MONTE CARLO ({cfg['MC_SIMULATIONS']:,} simulations){W}")
    pc = G if pr>=65 else (Y if pr>=45 else R)
    print(f"  Pass Rate:           {pc}{BOLD}{pr:.1f}%{W}")
    print(f"  Passed:              {G}{ftmo.get('passes',0):,}{W}")
    print(f"  Failed (Drawdown):   {R}{ftmo.get('fails_drawdown',0):,}{W}")
    wks = ftmo.get('avg_weeks_to_pass', 0)
    if wks > 0:
        print(f"  Avg Weeks to Pass:   {Y}{wks:.1f} weeks{W}")
    print(f"  Avg Final P&L:       ${ftmo.get('avg_final_pnl',0):,.2f}")

    print(f"\n{B}  FTMO READINESS CHECKS{W}")
    checks = [
        ("Profit Factor > 1.3",       pf >= 1.3),
        ("Win Rate > 45%",            wr >= 45),
        ("Max DD < 8%",               dd < 8),
        ("Max DD < FTMO 10% limit",   dd < 10),
        ("Consec. Losses < 8",        metrics.get('max_consec_loss',0) < 8),
        ("Positive Net Profit",       np_ > 0),
        ("Passes Monte Carlo > 50%",  pr >= 50),
    ]
    for chk, ok in checks:
        print(f"  {G+'✓' if ok else R+'✗'}{W}  {chk}")

    score   = sum(1 for _,ok in checks if ok)
    verdict = (f"{G}{BOLD}READY for FTMO challenge!{W}"         if score >= 6 else
               f"{Y}{BOLD}ALMOST READY — strong foundation{W}"  if score >= 5 else
               f"{Y}{BOLD}GOOD PROGRESS — keep refining{W}"     if score >= 4 else
               f"{R}{BOLD}NEEDS MORE WORK{W}")
    print(f"\n  Verdict: {verdict}")
    print(f"\n{'═'*58}\n")


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    print("\n╔══════════════════════════════════════════════════════╗")
    print("║   GOLD V3 — Backtester + FTMO 2026 Simulator        ║")
    print("║   Rules: No time limit | 2 min days | Best Day Rule  ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    print("► Step 1: Loading data...")
    df = load_data(CONFIG['DATA_FILE'])

    print("\n► Step 2: Calculating indicators...")
    df = add_indicators(df, CONFIG)
    sigs = df['long_signal'].sum() + df['short_signal'].sum()
    print(f"  {sigs} signals detected ({df['long_signal'].sum()} longs, {df['short_signal'].sum()} shorts)")

    print("\n► Step 3: Running backtest with real Gold lot sizing...")
    tdf, equity_s = run_backtest(df, CONFIG)
    print(f"  {len(tdf)} trades executed")

    print("\n► Step 4: Analyzing performance...")
    metrics = analyze_performance(tdf, equity_s, CONFIG)

    print("\n► Step 5: Running FTMO 2026 Monte Carlo (no time limit)...")
    ftmo = simulate_ftmo_2026(tdf, CONFIG)

    print("\n► Step 6: Generating charts...")
    plot_results(tdf, equity_s, metrics, ftmo, CONFIG)

    print_report(metrics, ftmo, CONFIG)

    if not tdf.empty:
        tdf.to_csv('gold_v3_trades.csv', index=False)
        print("  Trade log → gold_v3_trades.csv\n")


if __name__ == '__main__':
    main()
