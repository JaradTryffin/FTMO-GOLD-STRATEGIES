"""
╔══════════════════════════════════════════════════════════════╗
║   OB STRATEGY — LIVE TRADING BOT                            ║
║                                                              ║
║   HOW TO RUN:                                               ║
║   Windows VPS (real MT5):                                   ║
║     cd scripts && python bot.py                             ║
║                                                              ║
║   Mac (mock/test mode):                                     ║
║     cd scripts && python bot.py --mock                      ║
╚══════════════════════════════════════════════════════════════╝

Runs every hour at :02 past the hour.
Each run:
  1. Fetch last 200 closed H1 bars from MT5
  2. Recompute indicators + OB state
  3. Manage open position (breakeven / trailing / session close)
  4. Sync pending limit orders against active OBs
"""

import sys
import os
import logging
import schedule
import time
import argparse
from datetime import datetime

# ── logging setup (before any other imports) ─────────────────────────────────
os.makedirs('../logs', exist_ok=True)
logging.basicConfig(
    level    = logging.INFO,
    format   = '%(asctime)s %(levelname)-8s %(message)s',
    datefmt  = '%Y-%m-%d %H:%M:%S',
    handlers = [
        logging.FileHandler('../logs/bot.log'),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── broker import (real MT5 or mock) ─────────────────────────────────────────
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--mock', action='store_true')
args, _ = parser.parse_known_args()

if args.mock:
    import broker_mock as broker
    log.info("Running in MOCK mode (no real MT5 connection)")
else:
    try:
        import broker_mt5 as broker
        log.info("Running in LIVE MT5 mode")
    except ImportError:
        log.warning("MetaTrader5 not installed — falling back to mock mode")
        import broker_mock as broker

# ── strategy imports ──────────────────────────────────────────────────────────
from config   import INSTRUMENTS, ACTIVE_INSTRUMENT
from backtest import add_indicators
from strategy import compute_live_state, ob_id

try:
    from bot_credentials import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER
except ImportError:
    log.error("bot_credentials.py not found. "
              "Copy bot_credentials_template.py → bot_credentials.py and fill in details.")
    sys.exit(1)

CONFIG = INSTRUMENTS[ACTIVE_INSTRUMENT]
SYMBOL = CONFIG['MT5_SYMBOL']
TF     = CONFIG['MT5_TIMEFRAME']
N_BARS = CONFIG['BARS_TO_FETCH']


# ── helpers ───────────────────────────────────────────────────────────────────

def calc_lots(balance, sl_dist, cfg):
    risk = balance * (cfg['RISK_PCT'] / 100)
    lots = risk / (sl_dist * (1 / cfg['LOT_SIZE_UNIT']) * cfg['POINT_VALUE'])
    return max(0.01, round(lots, 2))


def _is_at_breakeven(live_pos):
    """True if SL has already been moved to breakeven (within 1 point of entry)."""
    if live_pos['dir'] == 'long':
        return live_pos['sl'] >= live_pos['entry'] - 1.0
    return live_pos['sl'] <= live_pos['entry'] + 1.0


# ── main reconcile ────────────────────────────────────────────────────────────

def reconcile():
    log.info("══ Reconcile run ══════════════════════════════")

    if not broker.connect(MT5_LOGIN, MT5_PASSWORD, MT5_SERVER):
        log.error("Connection failed — skipping this run")
        return

    try:
        # ── 1. Fetch bars ─────────────────────────────────────────────────────
        df = broker.get_bars(SYMBOL, TF, N_BARS + 10)
        if df is None or len(df) < 100:
            log.error("Insufficient bars — skipping")
            return

        df = add_indicators(df, CONFIG)
        log.info(f"Bars: {len(df)} | Last closed bar: {df.index[-1]}")

        # ── 2. Live state ─────────────────────────────────────────────────────
        live_pos     = broker.get_open_position(SYMBOL)
        live_orders  = broker.get_pending_orders(SYMBOL)
        acct         = broker.get_account_info()
        trades_today = broker.get_today_trade_count(SYMBOL)

        if acct is None:
            log.error("Could not get account info — skipping")
            return

        log.info(f"Balance: ${acct['balance']:,.2f} | Equity: ${acct['equity']:,.2f} | "
                 f"Position: {'YES' if live_pos else 'none'} | "
                 f"Pending: {len(live_orders)} | Trades today: {trades_today}")

        # ── 3. FTMO daily loss guard ──────────────────────────────────────────
        # Stop placing new orders if within 20% of hitting the daily loss limit
        daily_loss_limit = acct['balance'] * CONFIG['FTMO_MAX_DAILY_LOSS'] / 100
        daily_drawdown   = acct['balance'] - acct['equity']
        if daily_drawdown >= daily_loss_limit * 0.80:
            log.warning(f"Daily drawdown ${daily_drawdown:,.2f} near limit "
                        f"${daily_loss_limit:,.2f} — no new orders")
            broker.disconnect()
            return

        # ── 4. Compute OB state ───────────────────────────────────────────────
        pos_for_state = None
        if live_pos:
            pos_for_state = {
                'dir'    : live_pos['dir'],
                'entry'  : live_pos['entry'],
                'sl'     : live_pos['sl'],
                'tp'     : live_pos['tp'],
                'sl_dist': abs(live_pos['entry'] - live_pos['sl']),
                'be'     : _is_at_breakeven(live_pos),
            }

        state = compute_live_state(df, CONFIG, live_position=pos_for_state)
        log.info(f"Active OBs: {len(state['active_obs'])} | "
                 f"SessionClose: {state['should_close_session']} | "
                 f"BE trigger: {state['be_triggered']} | "
                 f"Trailing SL: {state['new_trailing_sl']}")

        # ── 5. Manage open position ───────────────────────────────────────────
        if live_pos:
            if state['should_close_session']:
                log.info("Past session end — closing position at market")
                broker.close_position(live_pos['ticket'], SYMBOL, live_pos['volume'])

            elif state['be_triggered'] and pos_for_state and not pos_for_state['be']:
                new_sl = (live_pos['entry'] + 0.5 if live_pos['dir'] == 'long'
                          else live_pos['entry'] - 0.5)
                log.info(f"Breakeven triggered → SL {live_pos['sl']:.2f} → {new_sl:.2f}")
                broker.modify_sl(live_pos['ticket'], new_sl, SYMBOL)

            elif state['new_trailing_sl'] is not None:
                log.info(f"Trailing stop → SL {live_pos['sl']:.2f} "
                         f"→ {state['new_trailing_sl']:.2f}")
                broker.modify_sl(live_pos['ticket'], state['new_trailing_sl'], SYMBOL)

        # ── 6. Sync pending orders ────────────────────────────────────────────
        expected_ids = {ob_id(ob): ob for ob in state['active_obs']}
        live_ids     = {o['comment']: o
                        for o in live_orders if o['comment'].startswith('OB_')}

        # Cancel orders whose OB is no longer valid
        for comment, order in live_ids.items():
            if comment not in expected_ids:
                log.info(f"Cancelling stale order: {comment} (ticket={order['ticket']})")
                broker.cancel_order(order['ticket'])

        # Place limit orders for new OBs (when no position + under daily cap + in session)
        if live_pos is None and trades_today < CONFIG['MAX_TRADES_DAY']:
            last_bar = df.iloc[-1]

            if not state['should_close_session']:
                tick = broker.get_current_price(SYMBOL)
                if tick is None:
                    log.warning("Could not get current price — skipping order placement")
                    broker.disconnect()
                    return

                for ob in state['active_obs']:
                    oid = ob_id(ob)
                    if oid in live_ids:
                        continue  # order already placed

                    # Validate bias and that price hasn't already passed through OB
                    if ob['dir'] == 'bull' and last_bar['bull_bias']:
                        if tick['ask'] <= ob['ob_high']:
                            log.debug(f"Bull OB {oid}: price already at/below OB — skipping")
                            continue
                        sl      = ob['wick_low'] - last_bar['atr'] * CONFIG['SL_BUFFER_MULT']
                        sl_dist = abs(ob['ob_high'] - sl)
                        if sl_dist < 0.5:
                            continue
                        tp      = ob['ob_high'] + sl_dist * CONFIG['RR_RATIO']
                        lots    = calc_lots(acct['balance'], sl_dist, CONFIG)
                        broker.place_limit_order(
                            symbol    = SYMBOL,
                            direction = 'long',
                            price     = ob['ob_high'],
                            sl        = sl,
                            tp        = tp,
                            lots      = lots,
                            comment   = oid,
                        )

                    elif ob['dir'] == 'bear' and last_bar['bear_bias']:
                        if tick['bid'] >= ob['ob_low']:
                            log.debug(f"Bear OB {oid}: price already at/above OB — skipping")
                            continue
                        sl      = ob['wick_high'] + last_bar['atr'] * CONFIG['SL_BUFFER_MULT']
                        sl_dist = abs(ob['ob_low'] - sl)
                        if sl_dist < 0.5:
                            continue
                        tp      = ob['ob_low'] - sl_dist * CONFIG['RR_RATIO']
                        lots    = calc_lots(acct['balance'], sl_dist, CONFIG)
                        broker.place_limit_order(
                            symbol    = SYMBOL,
                            direction = 'short',
                            price     = ob['ob_low'],
                            sl        = sl,
                            tp        = tp,
                            lots      = lots,
                            comment   = oid,
                        )
            else:
                log.info("Outside session — no new limit orders placed")
        elif live_pos:
            log.info("Position open — no new orders")
        else:
            log.info(f"Daily trade cap reached ({trades_today}/{CONFIG['MAX_TRADES_DAY']}) — no new orders")

    except Exception:
        log.exception("Unhandled error in reconcile()")
    finally:
        broker.disconnect()

    log.info("══ Reconcile complete ════════════════════════")


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    log.info("╔══════════════════════════════════════════════╗")
    log.info(f"║  OB Bot starting — {ACTIVE_INSTRUMENT:<26}║")
    log.info(f"║  Symbol: {SYMBOL:<37}║")
    log.info(f"║  Mode:   {'MOCK' if isinstance(broker.__name__ if hasattr(broker,'__name__') else '', str) and 'mock' in str(broker) else 'LIVE MT5':<37}║")
    log.info("╚══════════════════════════════════════════════╝")

    reconcile()  # run immediately on start

    schedule.every().hour.at(":02").do(reconcile)
    log.info("Scheduler active — runs every hour at :02")

    while True:
        schedule.run_pending()
        time.sleep(15)


if __name__ == '__main__':
    main()
