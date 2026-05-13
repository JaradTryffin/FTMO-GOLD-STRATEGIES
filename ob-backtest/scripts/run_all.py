"""
╔══════════════════════════════════════════════════════════════╗
║   MULTI-INSTRUMENT VALIDATION RUNNER                        ║
║   Runs full backtest + walk-forward on all instruments      ║
║                                                              ║
║   HOW TO RUN:                                               ║
║   cd scripts && python3 run_all.py                          ║
╚══════════════════════════════════════════════════════════════╝
"""

import sys
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

from config import INSTRUMENTS
from backtest import load_data, add_indicators, run_backtest, analyze_performance, simulate_ftmo_2026

# Walk-forward split dates per instrument (need enough data on each side)
WF_SPLITS = {
    "XAUUSD_2022" : "2024-01-01",   # 2yr IS / 2yr OOS
    "USTEC"       : "2025-07-01",   # ~18mo IS / ~9mo OOS
    "BTCUSD"      : None,           # only 15 months — skip walk-forward
    "XAUUSD"      : "2025-07-01",
}

# Instruments to run (order matters for display)
RUN_ORDER = ["XAUUSD_2022", "USTEC", "BTCUSD"]


def run_instrument(name, cfg):
    G = '\033[92m'; R = '\033[91m'; Y = '\033[93m'; B = '\033[94m'
    W = '\033[0m';  BOLD = '\033[1m'

    print(f"\n{'═'*60}")
    print(f"{BOLD}{Y}  {cfg['name'].upper()}{W}")
    print(f"{'═'*60}")

    df = load_data(cfg['DATA_FILE'])
    if df is None or len(df) < 500:
        print(f"  {R}Insufficient data. Skipping.{W}")
        return None

    df  = add_indicators(df, cfg)
    tdf, eq = run_backtest(df, cfg)

    if tdf.empty:
        print(f"  {R}No trades generated. Skipping.{W}")
        return None

    m    = analyze_performance(tdf, eq, cfg)
    ftmo = simulate_ftmo_2026(tdf, cfg)

    wr   = m.get('win_rate', 0)
    pf   = m.get('profit_factor', 0)
    rr   = m.get('actual_rr', 0)
    dd   = abs(m.get('max_dd_pct', 0))
    np_  = m.get('net_profit', 0)
    sh   = m.get('sharpe', 0)
    pr   = ftmo.get('pass_rate', 0)

    def c(v, g, b, hi=True):
        return G if (v >= g if hi else v <= g) else (Y if (v >= b if hi else v <= b) else R)

    mode = f"FIXED {cfg.get('FIXED_LOT')} lots" if cfg.get('FIXED_LOT') else "Dynamic"
    print(f"  Bars: {len(df):,} | Trades: {len(tdf)} | Lot mode: {mode}")
    print(f"  Period: {df.index[0].date()} → {df.index[-1].date()}")
    print(f"\n  {B}FULL PERIOD{W}")
    print(f"  Win Rate:       {c(wr,50,40)}{wr:.1f}%{W}   Profit Factor: {c(pf,1.5,1.2)}{pf:.3f}{W}")
    print(f"  Actual RR:      {c(rr,2.0,1.5)}{rr:.2f}:1{W}  Max DD:        {c(dd,5,8,False)}{dd:.2f}%{W}")
    print(f"  Net Profit:     {G if np_>0 else R}${np_:,.2f}{W}  Sharpe:        {c(sh,1.5,0.8)}{sh:.2f}{W}")
    print(f"  FTMO Pass Rate: {G if pr>=65 else Y}{pr:.1f}%{W}  Consec Losses: {m.get('max_consec_loss',0)}")

    # Walk-forward
    split = WF_SPLITS.get(name)
    if split:
        cutoff  = pd.Timestamp(split)
        df_is   = df[df.index < cutoff].copy()
        df_oos  = df[df.index >= cutoff].copy()

        if len(df_is) < 300 or len(df_oos) < 300:
            print(f"\n  {Y}Walk-forward skipped — insufficient bars in one period.{W}")
        else:
            tdf_is,  eq_is  = run_backtest(df_is,  cfg)
            tdf_oos, eq_oos = run_backtest(df_oos, cfg)

            if not tdf_is.empty and not tdf_oos.empty:
                m_is  = analyze_performance(tdf_is,  eq_is,  cfg)
                m_oos = analyze_performance(tdf_oos, eq_oos, cfg)

                wr_is  = m_is.get('win_rate', 0);  wr_oos  = m_oos.get('win_rate', 0)
                pf_is  = m_is.get('profit_factor', 0); pf_oos = m_oos.get('profit_factor', 0)
                dd_is  = abs(m_is.get('max_dd_pct', 0)); dd_oos = abs(m_oos.get('max_dd_pct', 0))
                sh_is  = m_is.get('sharpe', 0); sh_oos = m_oos.get('sharpe', 0)

                print(f"\n  {B}WALK-FORWARD (split: {split}){W}")
                print(f"  {'Metric':<18}{'In-Sample':>12}{'Out-of-Sample':>15}{'Held Up?':>10}")
                print(f"  {'─'*55}")

                def wf_row(label, iv, ov, higher=True, fmt='.1f', suffix=''):
                    delta = ov - iv
                    pct   = (delta / abs(iv) * 100) if iv != 0 else 0
                    ok    = (delta >= 0) if higher else (delta <= 0)
                    marginal = abs(pct) < 25
                    col   = G if ok else (Y if marginal else R)
                    tick  = f"{col}{'✓' if ok else ('~' if marginal else '✗')}{W}"
                    print(f"  {label:<18}{iv:>{12}{fmt}}{suffix}{ov:>{15}{fmt}}{suffix}{tick:>14}")

                wf_row("Win Rate",      wr_is,  wr_oos,  True,  '.1f', '%')
                wf_row("Profit Factor", pf_is,  pf_oos,  True,  '.3f')
                wf_row("Max Drawdown",  dd_is,  dd_oos,  False, '.2f', '%')
                wf_row("Sharpe",        sh_is,  sh_oos,  True,  '.2f')
                print(f"  Trades IS/OOS:  {len(tdf_is)} / {len(tdf_oos)}")

                oos_ok = pf_oos >= 1.3 and wr_oos >= 40
                verdict_col = G if oos_ok else R
                verdict_txt = "OOS HOLDS UP" if oos_ok else "OOS DEGRADED"
                print(f"\n  Walk-Forward Verdict: {verdict_col}{BOLD}{verdict_txt}{W}")
    else:
        print(f"\n  {Y}Walk-forward: skipped (insufficient data length){W}")

    return m


def print_summary(results):
    G = '\033[92m'; R = '\033[91m'; Y = '\033[93m'; B = '\033[94m'
    W = '\033[0m';  BOLD = '\033[1m'

    print(f"\n\n{'═'*60}")
    print(f"{BOLD}{Y}  CROSS-INSTRUMENT SUMMARY{W}")
    print(f"{'═'*60}")
    print(f"  {'Instrument':<22}{'WR':>7}{'PF':>8}{'RR':>8}{'DD':>8}{'Sharpe':>8}")
    print(f"  {'─'*55}")

    for name, m in results.items():
        if m is None:
            continue
        cfg = INSTRUMENTS[name]
        wr  = m.get('win_rate', 0)
        pf  = m.get('profit_factor', 0)
        rr  = m.get('actual_rr', 0)
        dd  = abs(m.get('max_dd_pct', 0))
        sh  = m.get('sharpe', 0)
        ok  = pf >= 1.3 and wr >= 40
        col = G if ok else R
        print(f"  {col}{cfg['name']:<22}{wr:>6.1f}%{pf:>8.3f}{rr:>7.2f}x{dd:>7.2f}%{sh:>8.2f}{W}")

    print(f"\n  Lot mode: FIXED (compounding removed) | Costs: spread + slippage + commission")

    valid = sum(1 for m in results.values() if m is not None and m.get('profit_factor', 0) >= 1.3)
    total = sum(1 for m in results.values() if m is not None)
    col   = G if valid == total else (Y if valid > 0 else R)
    print(f"\n  Edge confirmed on {col}{valid}/{total}{W} instruments tested")
    print(f"{'═'*60}\n")


def main():
    print(f"\n╔══════════════════════════════════════════════════════╗")
    print(f"║   MULTI-INSTRUMENT VALIDATION                       ║")
    print(f"║   Fixed lot sizing | Full costs | Walk-forward      ║")
    print(f"╚══════════════════════════════════════════════════════╝")

    results = {}
    for name in RUN_ORDER:
        cfg = INSTRUMENTS[name]
        results[name] = run_instrument(name, cfg)

    print_summary(results)


if __name__ == '__main__':
    main()
