"""
MT5 broker wrapper — Windows VPS only (MetaTrader5 lib requires Windows).
All functions return None/False on failure instead of raising,
so the bot stays alive through transient errors.
"""

import logging
import pandas as pd
from datetime import datetime, date

import MetaTrader5 as mt5

log = logging.getLogger(__name__)

_TIMEFRAME = {
    'M1' : mt5.TIMEFRAME_M1,
    'M5' : mt5.TIMEFRAME_M5,
    'M15': mt5.TIMEFRAME_M15,
    'H1' : mt5.TIMEFRAME_H1,
    'H4' : mt5.TIMEFRAME_H4,
    'D1' : mt5.TIMEFRAME_D1,
}


# ── Connection ────────────────────────────────────────────────────────────────

def connect(login, password, server):
    if not mt5.initialize():
        log.error(f"MT5 initialize failed: {mt5.last_error()}")
        return False
    if not mt5.login(login, password=password, server=server):
        log.error(f"MT5 login failed: {mt5.last_error()}")
        mt5.shutdown()
        return False
    info = mt5.account_info()
    log.info(f"MT5 connected: {server} | login={login} | balance=${info.balance:,.2f}")
    return True


def disconnect():
    mt5.shutdown()


# ── Market data ───────────────────────────────────────────────────────────────

def get_bars(symbol, timeframe, count):
    """
    Returns last `count` CLOSED H1 bars as a DataFrame.
    Drops the currently-forming bar (index 0 in MT5 = newest/current).
    """
    tf    = _TIMEFRAME.get(timeframe, mt5.TIMEFRAME_H1)
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count + 1)
    if rates is None or len(rates) == 0:
        log.error(f"get_bars failed {symbol}: {mt5.last_error()}")
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True).dt.tz_localize(None)
    df.set_index('time', inplace=True)
    df.rename(columns={'tick_volume': 'volume'}, inplace=True)
    df = df[['open', 'high', 'low', 'close', 'volume']]
    df = df.iloc[:-1]   # drop forming bar
    return df.tail(count)


def get_current_price(symbol):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        log.error(f"get_current_price failed {symbol}: {mt5.last_error()}")
        return None
    return {'bid': tick.bid, 'ask': tick.ask, 'mid': (tick.bid + tick.ask) / 2}


# ── Account ───────────────────────────────────────────────────────────────────

def get_account_info():
    info = mt5.account_info()
    if info is None:
        log.error(f"get_account_info failed: {mt5.last_error()}")
        return None
    return {
        'balance'    : info.balance,
        'equity'     : info.equity,
        'margin_free': info.margin_free,
        'profit'     : info.profit,
    }


# ── Orders & positions ────────────────────────────────────────────────────────

def get_pending_orders(symbol):
    orders = mt5.orders_get(symbol=symbol)
    if orders is None:
        return []
    return [
        {
            'ticket' : o.ticket,
            'type'   : 'buy_limit'  if o.type == mt5.ORDER_TYPE_BUY_LIMIT  else 'sell_limit',
            'price'  : o.price_open,
            'sl'     : o.sl,
            'tp'     : o.tp,
            'volume' : o.volume_current,
            'comment': o.comment,
        }
        for o in orders
    ]


def get_open_position(symbol):
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        return None
    p = positions[0]
    return {
        'ticket': p.ticket,
        'dir'   : 'long' if p.type == mt5.POSITION_TYPE_BUY else 'short',
        'entry' : p.price_open,
        'sl'    : p.sl,
        'tp'    : p.tp,
        'volume': p.volume,
        'profit': p.profit,
    }


def get_today_trade_count(symbol):
    """Count inbound fills (entries) for today."""
    today_start = datetime.combine(date.today(), datetime.min.time())
    deals = mt5.history_deals_get(today_start, datetime.now())
    if deals is None:
        return 0
    return sum(1 for d in deals
               if d.symbol == symbol and d.entry == mt5.DEAL_ENTRY_IN)


# ── Order operations ──────────────────────────────────────────────────────────

def place_limit_order(symbol, direction, price, sl, tp, lots, comment=''):
    order_type = (mt5.ORDER_TYPE_BUY_LIMIT if direction == 'long'
                  else mt5.ORDER_TYPE_SELL_LIMIT)
    request = {
        'action'      : mt5.TRADE_ACTION_PENDING,
        'symbol'      : symbol,
        'volume'      : lots,
        'type'        : order_type,
        'price'       : round(price, 2),
        'sl'          : round(sl,    2),
        'tp'          : round(tp,    2),
        'comment'     : comment[:31],       # MT5 comment max 31 chars
        'type_time'   : mt5.ORDER_TIME_GTC,
        'type_filling': mt5.ORDER_FILLING_RETURN,
    }
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log.error(f"place_limit_order failed: retcode={result.retcode} msg={result.comment}")
        return None
    log.info(f"Limit order: ticket={result.order} {direction} {symbol} "
             f"@ {price:.2f} SL={sl:.2f} TP={tp:.2f} lots={lots}")
    return result.order


def _clamp_sl_to_min_dist(symbol, new_sl, position_type):
    """Adjust new_sl to respect broker minimum stop distance from current price."""
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        return new_sl
    min_dist = info.trade_stops_level * info.point
    if min_dist == 0:
        min_dist = (tick.ask - tick.bid) * 2  # fallback: 2x spread
    min_dist += info.point  # one extra tick safety margin
    if position_type == mt5.POSITION_TYPE_BUY:
        return min(new_sl, tick.bid - min_dist)
    else:
        return max(new_sl, tick.ask + min_dist)


def modify_sl(ticket, new_sl, symbol):
    """Modify SL on either a pending order or an open position."""
    positions = mt5.positions_get(ticket=ticket)
    if positions:
        p = positions[0]
        new_sl = _clamp_sl_to_min_dist(symbol, new_sl, p.type)
        request = {
            'action'  : mt5.TRADE_ACTION_SLTP,
            'position': ticket,
            'symbol'  : symbol,
            'sl'      : round(new_sl, 2),
            'tp'      : p.tp,
        }
    else:
        orders = mt5.orders_get(ticket=ticket)
        if not orders:
            log.error(f"modify_sl: ticket {ticket} not found")
            return False
        o = orders[0]
        request = {
            'action': mt5.TRADE_ACTION_MODIFY,
            'order' : ticket,
            'price' : o.price_open,
            'sl'    : round(new_sl, 2),
            'tp'    : o.tp,
        }
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log.error(f"modify_sl failed: ticket={ticket} retcode={result.retcode}")
        return False
    log.info(f"SL modified: ticket={ticket} -> {new_sl:.2f}")
    return True


def cancel_order(ticket):
    result = mt5.order_send({'action': mt5.TRADE_ACTION_REMOVE, 'order': ticket})
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log.error(f"cancel_order failed: ticket={ticket} retcode={result.retcode}")
        return False
    log.info(f"Order cancelled: ticket={ticket}")
    return True


def close_position(ticket, symbol, volume):
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        log.error(f"close_position: ticket {ticket} not found")
        return False
    p    = positions[0]
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        log.error(f"close_position: no tick for {symbol}")
        return False

    close_type  = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    close_price = tick.bid             if p.type == mt5.POSITION_TYPE_BUY else tick.ask

    request = {
        'action'      : mt5.TRADE_ACTION_DEAL,
        'symbol'      : symbol,
        'volume'      : volume,
        'type'        : close_type,
        'position'    : ticket,
        'price'       : close_price,
        'comment'     : 'SessionEnd',
        'type_filling': mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log.error(f"close_position failed: ticket={ticket} retcode={result.retcode}")
        return False
    log.info(f"Position closed: ticket={ticket}")
    return True
