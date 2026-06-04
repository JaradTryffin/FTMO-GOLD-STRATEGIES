"""
OB STRATEGY -- LIVE TRADING BOT

HOW TO RUN:
  Windows VPS (real MT5):
    cd scripts && python bot.py

  Mac (mock/test mode):
    cd scripts && python bot.py --mock

Runs every hour at :02 past the hour.
Each run loops over all ACTIVE_INSTRUMENTS:
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

MOCK_MODE = args.mock

if MOCK_MODE:
    import broker_mock as broker
    log.info("Running in MOCK mode")
else:
    try:
        import broker_mt5 as broker
        log.info("Running in LIVE MT5 mode")
    except ImportError:
        log.warning("MetaTrader5 not installed — falling back to mock mode")
        import broker_mock as broker
        MOCK_MODE = True

# ── strategy imports ──────────────────────────────────────────────────────────
from config   import INSTRUMENTS, ACTIVE_INSTRUMENTS
from backtest import add_indicators
from strategy import compute_live_state, ob_id

try:
    from bot_credentials import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER
except ImportError:
    log.error("bot_credentials.py not found. "
              "Copy bot_credentials_template.py -> bot_credentials.py and fill in details.")
    sys.exit(1)


# ── helpers ───────────────────────────────────────────────────────────────────

def calc_lots(balance, sl_dist, cfg):
    risk = balance * (cfg['RISK_PCT'] / 100)
    lots = risk / (sl_dist * (1 / cfg['LOT_SIZE_UNIT']) * cfg['POINT_VALUE'])
    return max(cfg['LOT_SIZE_UNIT'], round(lots, 2))


def _is_at_breakeven(live_pos):
    if live_pos['dir'] == 'long':
        return live_pos['sl'] >= live_pos['entry'] - 1.0
    return live_pos['sl'] <= live_pos['entry'] + 1.0


# ── per-instrument reconcile ──────────────────────────────────────────────────

def _reconcile_instrument(cfg, acct):
    symbol = cfg['MT5_SYMBOL']
    tf     = cfg['MT5_TIMEFRAME']
    n_bars = cfg['BARS_TO_FETCH']

    log.info(f"  [{symbol}] " + "-" * (44 - len(symbol)))

    # In mock mode set data file per instrument
    if MOCK_MODE:
        data_abs = os.path.abspath(os.path.join(os.path.dirname(__file__), cfg['DATA_FILE']))
        if not os.path.exists(data_abs):
            log.warning(f"  [{symbol}] Mock data not found: {data_abs} — skipping")
            return
        broker.set_data_file(data_abs)

    # ── 1. Fetch bars ─────────────────────────────────────────────────────────
    df = broker.get_bars(symbol, tf, n_bars + 10)
    if df is None or len(df) < 100:
        log.error(f"  [{symbol}] Insufficient bars — skipping")
        return

    df = add_indicators(df, cfg)
    log.info(f"  [{symbol}] Bars: {len(df)} | Last bar: {df.index[-1]}")

    # ── 2. Live state ─────────────────────────────────────────────────────────
    live_pos     = broker.get_open_position(symbol)
    live_orders  = broker.get_pending_orders(symbol)
    trades_today = broker.get_today_trade_count(symbol)

    log.info(f"  [{symbol}] Position: {'YES' if live_pos else 'none'} | "
             f"Pending: {len(live_orders)} | Trades today: {trades_today}")

    # ── 3. FTMO daily loss guard ──────────────────────────────────────────────
    daily_loss_limit = acct['balance'] * cfg['FTMO_MAX_DAILY_LOSS'] / 100
    daily_drawdown   = acct['balance'] - acct['equity']
    if daily_drawdown >= daily_loss_limit * 0.80:
        log.warning(f"  [{symbol}] Daily drawdown near limit — no new orders")
        return

    # ── 4. Compute OB state ───────────────────────────────────────────────────
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

    state = compute_live_state(df, cfg, live_position=pos_for_state)
    log.info(f"  [{symbol}] Active OBs: {len(state['active_obs'])} | "
             f"SessionClose: {state['should_close_session']} | "
             f"BE trigger: {state['be_triggered']} | "
             f"Trailing SL: {state['new_trailing_sl']}")

    # ── 5. Manage open position ───────────────────────────────────────────────
    if live_pos:
        if state['should_close_session']:
            log.info(f"  [{symbol}] Past session end — closing position at market")
            broker.close_position(live_pos['ticket'], symbol, live_pos['volume'])

        elif state['be_triggered'] and pos_for_state and not pos_for_state['be']:
            # SL moves to just beyond entry; buffer clears broker min stop distance
            buf    = cfg.get('BE_SL_BUFFER', 5.0)
            new_sl = (live_pos['entry'] - buf if live_pos['dir'] == 'long'
                      else live_pos['entry'] + buf)
            log.info(f"  [{symbol}] Breakeven triggered -> SL {live_pos['sl']:.2f} -> {new_sl:.2f}")
            broker.modify_sl(live_pos['ticket'], new_sl, symbol)

        elif state['new_trailing_sl'] is not None:
            log.info(f"  [{symbol}] Trailing stop -> SL {live_pos['sl']:.2f} "
                     f"-> {state['new_trailing_sl']:.2f}")
            broker.modify_sl(live_pos['ticket'], state['new_trailing_sl'], symbol)

    # ── 6. Sync pending orders ────────────────────────────────────────────────
    expected_ids = {ob_id(ob): ob for ob in state['active_obs']}
    live_ids     = {o['comment']: o
                    for o in live_orders if o['comment'].startswith('OB_')}

    for comment, order in live_ids.items():
        if comment not in expected_ids:
            log.info(f"  [{symbol}] Cancelling stale order: {comment}")
            broker.cancel_order(order['ticket'])

    if live_pos is None and trades_today < cfg['MAX_TRADES_DAY']:
        last_bar = df.iloc[-1]

        if not state['should_close_session']:
            tick = broker.get_current_price(symbol)
            if tick is None:
                log.warning(f"  [{symbol}] Could not get current price — skipping")
                return

            for ob in state['active_obs']:
                oid = ob_id(ob)
                if oid in live_ids:
                    continue

                if ob['dir'] == 'bull' and last_bar['bull_bias']:
                    if tick['ask'] <= ob['ob_high']:
                        continue
                    sl      = ob['wick_low'] - last_bar['atr'] * cfg['SL_BUFFER_MULT']
                    sl_dist = abs(ob['ob_high'] - sl)
                    if sl_dist < 0.5:
                        continue
                    tp   = ob['ob_high'] + sl_dist * cfg['RR_RATIO']
                    lots = calc_lots(acct['balance'], sl_dist, cfg)
                    broker.place_limit_order(
                        symbol=symbol, direction='long',
                        price=ob['ob_high'], sl=sl, tp=tp, lots=lots, comment=oid,
                    )

                elif ob['dir'] == 'bear' and last_bar['bear_bias']:
                    if tick['bid'] >= ob['ob_low']:
                        continue
                    sl      = ob['wick_high'] + last_bar['atr'] * cfg['SL_BUFFER_MULT']
                    sl_dist = abs(ob['ob_low'] - sl)
                    if sl_dist < 0.5:
                        continue
                    tp   = ob['ob_low'] - sl_dist * cfg['RR_RATIO']
                    lots = calc_lots(acct['balance'], sl_dist, cfg)
                    broker.place_limit_order(
                        symbol=symbol, direction='short',
                        price=ob['ob_low'], sl=sl, tp=tp, lots=lots, comment=oid,
                    )
        else:
            log.info(f"  [{symbol}] Outside session — no new limit orders")
    elif live_pos:
        log.info(f"  [{symbol}] Position open — no new orders")
    else:
        log.info(f"  [{symbol}] Daily trade cap reached ({trades_today}/{cfg['MAX_TRADES_DAY']})")


# ── main reconcile ────────────────────────────────────────────────────────────

def reconcile():
    log.info("-- Reconcile run " + "-" * 33)

    if not broker.connect(MT5_LOGIN, MT5_PASSWORD, MT5_SERVER):
        log.error("Connection failed — skipping this run")
        return

    try:
        acct = broker.get_account_info()
        if acct is None:
            log.error("Could not get account info — skipping")
            return

        log.info(f"Balance: ${acct['balance']:,.2f} | Equity: ${acct['equity']:,.2f}")

        for instrument_key in ACTIVE_INSTRUMENTS:
            try:
                _reconcile_instrument(INSTRUMENTS[instrument_key], acct)
            except Exception:
                log.exception(f"Error reconciling {instrument_key}")

    except Exception:
        log.exception("Unhandled error in reconcile()")
    finally:
        broker.disconnect()

    log.info("-- Reconcile complete " + "-" * 28)


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    log.info("=" * 50)
    log.info(f"  OB Bot starting -- {len(ACTIVE_INSTRUMENTS)} instruments")
    for key in ACTIVE_INSTRUMENTS:
        log.info(f"    {key}: {INSTRUMENTS[key]['MT5_SYMBOL']}")
    log.info(f"  Mode: {'MOCK' if MOCK_MODE else 'LIVE MT5'}")
    log.info("=" * 50)

    reconcile()

    schedule.every().hour.at(":02").do(reconcile)
    log.info("Scheduler active — runs every hour at :02")

    while True:
        schedule.run_pending()
        time.sleep(15)


if __name__ == '__main__':
    main()
