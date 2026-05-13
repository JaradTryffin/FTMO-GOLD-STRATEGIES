"""
╔══════════════════════════════════════════════════════════════╗
║   WALK-FORWARD VALIDATION                                    ║
║   In-Sample: 2022–2023  |  Out-of-Sample: 2024–2026         ║
║                                                              ║
║   HOW TO RUN:                                               ║
║   cd scripts && python3 walk_forward.py                     ║
╚══════════════════════════════════════════════════════════════╝

Splits the dataset at a fixed date cutoff.
Same params run on both halves independently (capital resets each).
Degradation between IS and OOS reveals overfitting.
"""

import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import warnings
warnings.filterwarnings('ignore')

from config import INSTRUMENTS, ACTIVE_INSTRUMENT
from backtest import load_data, add_indicators, run_backtest, analyze_performance, simulate_ftmo_2026

CONFIG = INSTRUMENTS[ACTIVE_INSTRUMENT]

SPLIT_DATE = "2024-01-01"   # everything before = IS, on/after = OOS


# ══════════════════════════════════════════════════════════════════════════════
#  SPLIT
# ══════════════════════════════════════════════════════════════════════════════
def split_data(df, split_date):
    cutoff = pd.Timestamp(split_date)
    df_is  = df[df.index < cutoff].copy()
    df_oos = df[df.index >= cutoff].copy()
    return df_is, df_oos


# ══════════════════════════════════════════════════════════════════════════════
#  TERMINAL REPORT
# ══════════════════════════════════════════════════════════════════════════════
def print_comparison(m_is, m_oos, ftmo_is, ftmo_oos, is_range, oos_range):
    G = '\033[92m'; R = '\033[91m'; Y = '\033[93m'; B = '\033[94m'
    W = '\033[0m';  BOLD = '\033[1m'; MUTED = '\033[90m'

    def flag(is_val, oos_val, higher_is_better=True):
        delta = oos_val - is_val
        pct   = (delta / abs(is_val) * 100) if is_val != 0 else 0
        if higher_is_better:
            col = G if delta >= 0 else (Y if pct > -20 else R)
        else:
            col = G if delta <= 0 else (Y if pct < 20 else R)
        arrow = '▲' if delta >= 0 else '▼'
        return f"{col}{arrow}{abs(pct):.0f}%{W}"

    print(f"\n{BOLD}{'═'*66}{W}")
    print(f"{BOLD}{Y}  WALK-FORWARD VALIDATION — {CONFIG['name'].upper()}{W}")
    print(f"{BOLD}{'═'*66}{W}")
    print(f"\n  Split date: {SPLIT_DATE}")
    print(f"  {'In-Sample:':<22}{is_range}")
    print(f"  {'Out-of-Sample:':<22}{oos_range}")
    print(f"  Capital resets to ${CONFIG['INITIAL_CAPITAL']:,} at start of each period\n")

    hdr = f"  {'Metric':<26}{'In-Sample':>14}{'Out-of-Sample':>16}{'Change':>10}"
    print(f"{B}{hdr}{W}")
    print(f"  {'─'*64}")

    def row(label, key, fmt='.1f', suffix='', higher=True, multiply=1):
        iv = m_is.get(key, 0) * multiply
        ov = m_oos.get(key, 0) * multiply
        iv_s = f"{iv:{fmt}}{suffix}"
        ov_s = f"{ov:{fmt}}{suffix}"
        chg  = flag(iv, ov, higher)
        print(f"  {label:<26}{iv_s:>14}{ov_s:>16}{chg:>18}")

    print(f"  {'Trades':<26}{m_is.get('total_trades',0):>14}{m_oos.get('total_trades',0):>16}")
    row("Win Rate",         'win_rate',       fmt='.1f', suffix='%')
    row("Profit Factor",    'profit_factor',  fmt='.3f')
    row("Actual RR",        'actual_rr',      fmt='.2f', suffix=':1')
    row("Net Profit",       'net_profit',     fmt=',.0f', suffix='', higher=True)
    row("Net Profit %",     'net_profit_pct', fmt='.1f', suffix='%')
    row("Max Drawdown",     'max_dd_pct',     fmt='.2f', suffix='%', higher=False)
    row("Consec Losses",    'max_consec_loss',fmt='.0f',              higher=False)
    row("Sharpe Ratio",     'sharpe',         fmt='.2f')

    print(f"\n  {'─'*64}")
    print(f"  {'FTMO Pass Rate':<26}{ftmo_is.get('pass_rate',0):>13.1f}%"
          f"{ftmo_oos.get('pass_rate',0):>15.1f}%"
          f"{flag(ftmo_is.get('pass_rate',0), ftmo_oos.get('pass_rate',0)):>18}")
    print(f"  {'Avg Weeks to Pass':<26}{ftmo_is.get('avg_weeks_to_pass',0):>13.1f}wk"
          f"{ftmo_oos.get('avg_weeks_to_pass',0):>14.1f}wk")

    print(f"\n  {'─'*64}")
    wr_drop  = m_oos.get('win_rate', 0)      - m_is.get('win_rate', 0)
    pf_drop  = m_oos.get('profit_factor', 0) - m_is.get('profit_factor', 0)
    dd_delta = m_oos.get('max_dd_pct', 0)    - m_is.get('max_dd_pct', 0)

    degraded = (wr_drop < -10) or (pf_drop < -1.0) or (dd_delta < -3)
    if m_oos.get('profit_factor', 0) >= 1.5 and m_oos.get('win_rate', 0) >= 45:
        verdict = f"{G}{BOLD}ROBUST — OOS holds up. Strategy has real edge.{W}"
    elif m_oos.get('profit_factor', 0) >= 1.2 and m_oos.get('win_rate', 0) >= 40:
        verdict = f"{Y}{BOLD}MODERATE — OOS acceptable, not exceptional.{W}"
    else:
        verdict = f"{R}{BOLD}OVERFIT — OOS degraded significantly. Do not trade live.{W}"

    print(f"\n  Verdict: {verdict}")
    print(f"\n{'═'*66}\n")


# ══════════════════════════════════════════════════════════════════════════════
#  CHART
# ══════════════════════════════════════════════════════════════════════════════
def plot_walkforward(eq_is, eq_oos, tdf_is, tdf_oos, m_is, m_oos, ftmo_is, ftmo_oos, cfg):
    BG    = '#0d1117'; PANEL = '#161b22'; TEXT  = '#e6edf3'; MUTED = '#8b949e'
    GOLD  = '#FFD700'; GREEN = '#00ff88'; RED   = '#ff4444'; BLUE  = '#4488ff'
    ORANGE = '#ff9900'

    fig = plt.figure(figsize=(22, 12), facecolor=BG)
    gs  = gridspec.GridSpec(2, 3, figure=fig, hspace=0.45, wspace=0.35)
    ax_eq  = fig.add_subplot(gs[0, :])
    ax_dd  = fig.add_subplot(gs[1, 0])
    ax_pnl = fig.add_subplot(gs[1, 1])
    ax_tbl = fig.add_subplot(gs[1, 2])

    for ax in [ax_eq, ax_dd, ax_pnl, ax_tbl]:
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=MUTED, labelsize=8)
        for s in ax.spines.values(): s.set_color('#30363d')

    # ── Combined equity ───────────────────────────────────────
    ax_eq.plot(eq_is.index,  eq_is.values,  color=BLUE,   linewidth=2, label='In-Sample (2022–2023)')
    ax_eq.plot(eq_oos.index, eq_oos.values, color=ORANGE, linewidth=2, label='Out-of-Sample (2024–2026)')
    ax_eq.axhline(cfg['INITIAL_CAPITAL'], color=MUTED, linewidth=1, linestyle='--', alpha=0.5)
    ax_eq.axvline(pd.Timestamp(SPLIT_DATE), color=GOLD, linewidth=1.5, linestyle=':', alpha=0.8)
    ax_eq.text(pd.Timestamp(SPLIT_DATE), ax_eq.get_ylim()[0] if ax_eq.get_ylim()[0] > 0 else cfg['INITIAL_CAPITAL'],
               f' Split: {SPLIT_DATE}', color=GOLD, fontsize=8, va='bottom')
    ax_eq.legend(fontsize=8, facecolor=PANEL, labelcolor=TEXT, loc='upper left')
    ax_eq.set_title(f"Walk-Forward Equity — {cfg['name']} (capital resets each period)",
                    color=TEXT, fontsize=12, pad=10)
    ax_eq.set_ylabel('Capital ($)', color=MUTED, fontsize=9)
    ax_eq.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'${x:,.0f}'))

    # ── Drawdown comparison ───────────────────────────────────
    for eq, col, lbl in [(eq_is, BLUE, 'IS'), (eq_oos, ORANGE, 'OOS')]:
        rm = eq.cummax()
        dd = (eq - rm) / rm * 100
        ax_dd.fill_between(dd.index, dd.values, 0, color=col, alpha=0.25)
        ax_dd.plot(dd.index, dd.values, color=col, linewidth=1, label=lbl)
    ax_dd.axhline(-cfg['FTMO_MAX_TOTAL_LOSS'], color=RED, linewidth=1.5, linestyle='--',
                  label=f"FTMO limit (-{cfg['FTMO_MAX_TOTAL_LOSS']}%)", alpha=0.7)
    ax_dd.set_title('Drawdown Comparison (%)', color=TEXT, fontsize=10, pad=8)
    ax_dd.legend(fontsize=7, facecolor=PANEL, labelcolor=TEXT)

    # ── Trade P&L scatter ─────────────────────────────────────
    if not tdf_is.empty:
        ax_pnl.scatter(range(len(tdf_is)),
                       tdf_is['pnl_dollars'],
                       c=[GREEN if p > 0 else RED for p in tdf_is['pnl_dollars']],
                       alpha=0.5, s=18, label='IS trades')
    if not tdf_oos.empty:
        offset = len(tdf_is)
        ax_pnl.scatter(range(offset, offset + len(tdf_oos)),
                       tdf_oos['pnl_dollars'],
                       c=[GREEN if p > 0 else '#ff8800' for p in tdf_oos['pnl_dollars']],
                       alpha=0.5, s=18, marker='D', label='OOS trades')
    ax_pnl.axhline(0, color=MUTED, linewidth=0.8)
    ax_pnl.axvline(len(tdf_is), color=GOLD, linewidth=1.5, linestyle=':', alpha=0.8)
    ax_pnl.set_title('Trade P&L (IS then OOS)', color=TEXT, fontsize=10, pad=8)
    ax_pnl.set_xlabel('Trade #', color=MUTED, fontsize=8)
    ax_pnl.set_ylabel('P&L ($)', color=MUTED, fontsize=8)
    ax_pnl.legend(fontsize=7, facecolor=PANEL, labelcolor=TEXT)

    # ── Stats table ───────────────────────────────────────────
    ax_tbl.axis('off')

    def pct_delta(iv, ov, higher=True):
        if iv == 0:
            return ''
        d = (ov - iv) / abs(iv) * 100
        col = GREEN if (d >= 0) == higher else (GOLD if abs(d) < 20 else RED)
        arr = '▲' if d >= 0 else '▼'
        return f"{col}{arr}{abs(d):.0f}%\033[0m"

    rows = [
        ('── IN-SAMPLE ──', '', '', BLUE),
        ('Period', '2022 – 2023', '', TEXT),
        ('Trades',       str(m_is.get('total_trades', 0)), '', TEXT),
        ('Win Rate',     f"{m_is.get('win_rate',0):.1f}%", '', TEXT),
        ('Profit Factor',f"{m_is.get('profit_factor',0):.3f}", '', TEXT),
        ('Max DD',       f"{m_is.get('max_dd_pct',0):.2f}%", '', TEXT),
        ('Sharpe',       f"{m_is.get('sharpe',0):.2f}", '', TEXT),
        ('FTMO Pass',    f"{ftmo_is.get('pass_rate',0):.1f}%", '', TEXT),
        ('── OUT-OF-SAMPLE ──', '', '', ORANGE),
        ('Period', '2024 – 2026', '', TEXT),
        ('Trades',       str(m_oos.get('total_trades', 0)), '', TEXT),
        ('Win Rate',     f"{m_oos.get('win_rate',0):.1f}%", '', TEXT),
        ('Profit Factor',f"{m_oos.get('profit_factor',0):.3f}", '', TEXT),
        ('Max DD',       f"{m_oos.get('max_dd_pct',0):.2f}%", '', TEXT),
        ('Sharpe',       f"{m_oos.get('sharpe',0):.2f}", '', TEXT),
        ('FTMO Pass',    f"{ftmo_oos.get('pass_rate',0):.1f}%", '', TEXT),
    ]

    y = 0.99
    for item in rows:
        label, val, _, col = item
        if val == '':
            ax_tbl.text(0.02, y, label, transform=ax_tbl.transAxes,
                        color=col, fontsize=8, fontweight='bold')
        else:
            ax_tbl.text(0.02, y, label, transform=ax_tbl.transAxes, color=MUTED, fontsize=8)
            ax_tbl.text(0.98, y, val,   transform=ax_tbl.transAxes, color=col,   fontsize=8,
                        fontweight='bold', ha='right')
        y -= 0.058

    fig.suptitle(f"{cfg['name']} — Walk-Forward Validation | Split: {SPLIT_DATE}",
                 color=GOLD, fontsize=14, fontweight='bold', y=0.99)

    out = f"../results/reports/{cfg['slug']}_walkforward_report.png"
    plt.savefig(out, dpi=150, bbox_inches='tight', facecolor=BG)
    print(f"  Chart saved → {out}")
    plt.close()


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    print(f"\n╔══════════════════════════════════════════════════════╗")
    print(f"║   Walk-Forward Validation — {ACTIVE_INSTRUMENT:<24}║")
    print(f"║   Split date: {SPLIT_DATE:<39}║")
    print(f"╚══════════════════════════════════════════════════════╝\n")

    print("► Step 1: Loading data...")
    df_full = load_data(CONFIG['DATA_FILE'])

    print("\n► Step 2: Splitting data...")
    df_is, df_oos = split_data(df_full, SPLIT_DATE)
    print(f"  In-Sample:      {len(df_is):,} bars | {df_is.index[0].date()} → {df_is.index[-1].date()}")
    print(f"  Out-of-Sample:  {len(df_oos):,} bars | {df_oos.index[0].date()} → {df_oos.index[-1].date()}")

    if len(df_is) < 500 or len(df_oos) < 500:
        print("\n  ERROR: One period too short. Adjust SPLIT_DATE.")
        sys.exit(1)

    print("\n► Step 3: Adding indicators...")
    df_is  = add_indicators(df_is.copy(),  CONFIG)
    df_oos = add_indicators(df_oos.copy(), CONFIG)

    print("\n► Step 4: Running IN-SAMPLE backtest...")
    tdf_is, eq_is = run_backtest(df_is, CONFIG)
    print(f"  {len(tdf_is)} trades")

    print("\n► Step 5: Running OUT-OF-SAMPLE backtest...")
    tdf_oos, eq_oos = run_backtest(df_oos, CONFIG)
    print(f"  {len(tdf_oos)} trades")

    if tdf_is.empty or tdf_oos.empty:
        print("\n  ERROR: No trades in one period. Check config.")
        sys.exit(1)

    print("\n► Step 6: Analysing performance...")
    m_is  = analyze_performance(tdf_is,  eq_is,  CONFIG)
    m_oos = analyze_performance(tdf_oos, eq_oos, CONFIG)

    print("\n► Step 7: Running FTMO Monte Carlo (both periods)...")
    ftmo_is  = simulate_ftmo_2026(tdf_is,  CONFIG)
    ftmo_oos = simulate_ftmo_2026(tdf_oos, CONFIG)

    print("\n► Step 8: Generating chart...")
    plot_walkforward(eq_is, eq_oos, tdf_is, tdf_oos, m_is, m_oos, ftmo_is, ftmo_oos, CONFIG)

    is_range  = f"{df_is.index[0].date()} → {df_is.index[-1].date()}"
    oos_range = f"{df_oos.index[0].date()} → {df_oos.index[-1].date()}"
    print_comparison(m_is, m_oos, ftmo_is, ftmo_oos, is_range, oos_range)

    tdf_is.to_csv(f"../results/trades/{CONFIG['slug']}_is_trades.csv",  index=False)
    tdf_oos.to_csv(f"../results/trades/{CONFIG['slug']}_oos_trades.csv", index=False)
    print(f"  IS  trades → ../results/trades/{CONFIG['slug']}_is_trades.csv")
    print(f"  OOS trades → ../results/trades/{CONFIG['slug']}_oos_trades.csv\n")


if __name__ == '__main__':
    main()
