"""
Mock broker for local Mac development and testing.
Identical interface to broker_mt5.py — swap by changing the import in bot.py.
Reads bars from CSV; simulates in-memory order/position state.
"""

import logging
import pandas as pd

log = logging.getLogger(__name__)

_orders      = {}   # ticket -> order dict
_position    = None
_next_ticket = 1000
_data_file   = None
_balance     = 10_000.0


# ── Config ────────────────────────────────────────────────────────────────────

def set_data_file(path):
    global _data_file
    _data_file = path

def set_balance(amount):
    global _balance
    _balance = amount


# ── Connection ────────────────────────────────────────────────────────────────

def connect(login, password, server):
    log.info(f"[MOCK] Connected: login={login} server={server}")
    return True

def disconnect():
    log.info("[MOCK] Disconnected")


# ── Market data ───────────────────────────────────────────────────────────────

def get_bars(symbol, timeframe, count):
    if _data_file is None:
        raise RuntimeError("Mock: call broker_mock.set_data_file(path) before get_bars()")
    df = pd.read_csv(_data_file)
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
    needed = [c for c in ['open', 'high', 'low', 'close'] if c in df.columns]
    df = df[needed].apply(pd.to_numeric, errors='coerce').dropna()
    if 'volume' not in df.columns:
        df['volume'] = 1000
    return df.tail(count)


def get_current_price(symbol):
    if _data_file is None:
        return {'bid': 2000.0, 'ask': 2000.4, 'mid': 2000.2}
    df = get_bars(symbol, 'H1', 2)
    mid = float(df['close'].iloc[-1])
    return {'bid': mid - 0.2, 'ask': mid + 0.2, 'mid': mid}


# ── Account ───────────────────────────────────────────────────────────────────

def get_account_info():
    profit = _position['profit'] if _position else 0.0
    return {
        'balance'    : _balance,
        'equity'     : _balance + profit,
        'margin_free': _balance * 0.9,
        'profit'     : profit,
    }


# ── Orders & positions ────────────────────────────────────────────────────────

def get_pending_orders(symbol):
    return list(_orders.values())


def get_open_position(symbol):
    return _position


def get_today_trade_count(symbol):
    return 0


# ── Order operations ──────────────────────────────────────────────────────────

def place_limit_order(symbol, direction, price, sl, tp, lots, comment=''):
    global _next_ticket
    ticket = _next_ticket
    _next_ticket += 1
    _orders[ticket] = {
        'ticket' : ticket,
        'type'   : 'buy_limit' if direction == 'long' else 'sell_limit',
        'price'  : price,
        'sl'     : sl,
        'tp'     : tp,
        'volume' : lots,
        'comment': comment,
    }
    log.info(f"[MOCK] Limit order: ticket={ticket} {direction} {symbol} "
             f"@ {price:.2f} SL={sl:.2f} TP={tp:.2f} lots={lots} comment={comment}")
    return ticket


def modify_sl(ticket, new_sl, symbol):
    if ticket in _orders:
        _orders[ticket]['sl'] = new_sl
    elif _position and _position['ticket'] == ticket:
        _position['sl'] = new_sl
    else:
        log.warning(f"[MOCK] modify_sl: ticket {ticket} not found")
        return False
    log.info(f"[MOCK] SL modified: ticket={ticket} → {new_sl:.2f}")
    return True


def cancel_order(ticket):
    if ticket in _orders:
        del _orders[ticket]
        log.info(f"[MOCK] Order cancelled: ticket={ticket}")
        return True
    log.warning(f"[MOCK] cancel_order: ticket {ticket} not found")
    return False


def close_position(ticket, symbol, volume):
    global _position
    if _position and _position['ticket'] == ticket:
        _position = None
        log.info(f"[MOCK] Position closed: ticket={ticket}")
        return True
    log.warning(f"[MOCK] close_position: ticket {ticket} not found")
    return False
