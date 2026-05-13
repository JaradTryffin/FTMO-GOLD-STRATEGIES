"""
Live state engine for the OB bot.
Reuses add_indicators + find_ob_candle from backtest.py.
Does NOT simulate trades — only tracks structural state (swings, OBs).
"""

from backtest import add_indicators, find_ob_candle


def ob_id(ob):
    """Stable string ID for an OB, used as MT5 order comment tag."""
    return f"OB_{ob['formed_time'].strftime('%Y%m%d%H%M')}_{ob['dir']}"


def compute_live_state(df, cfg, live_position=None):
    """
    Replay bars to rebuild current market structure state.

    Parameters
    ----------
    df            : DataFrame with indicators already applied (add_indicators called first)
    cfg           : instrument config dict
    live_position : dict or None
                    {dir, entry, sl, tp, sl_dist, be}
                    Provide to get BE/trailing update recommendations.

    Returns
    -------
    dict with keys:
        active_obs           : list of currently valid OB dicts
        be_triggered         : bool — last bar hit 1R, should move SL to BE
        new_trailing_sl      : float or None — new trailing SL if better than current
        should_close_session : bool — last bar is past SESSION_END
    """
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
        row = df.iloc[i]

        # Confirm swings that are n bars old (no lookahead)
        conf_i = i - n
        if df['is_swing_high'].iloc[conf_i]:
            new_sh = df['high'].iloc[conf_i]
            if last_sh_price is None or new_sh != last_sh_price:
                last_sh_price = new_sh
                last_sh_idx   = conf_i
                last_bull_bos = None
        if df['is_swing_low'].iloc[conf_i]:
            new_sl_val = df['low'].iloc[conf_i]
            if last_sl_price is None or new_sl_val != last_sl_price:
                last_sl_price = new_sl_val
                last_sl_idx   = conf_i
                last_bear_bos = None

        # Detect BOS → create Order Blocks
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

        # Age OBs; remove mitigated or expired
        for ob in active_obs:
            ob['age'] += 1
            if ob['dir'] == 'bull' and row['close'] < ob['ob_low']:
                ob['mitigated'] = True
            elif ob['dir'] == 'bear' and row['close'] > ob['ob_high']:
                ob['mitigated'] = True
        active_obs = [ob for ob in active_obs
                      if not ob['mitigated'] and ob['age'] < cfg['OB_MAX_AGE']]

    # ── Last-bar checks ───────────────────────────────────────────────────────
    last = df.iloc[-1]

    should_close_session = int(last['hour_gmt']) >= cfg['SESSION_END']

    be_triggered    = False
    new_trailing_sl = None

    if live_position is not None:
        pos = live_position
        if pos['dir'] == 'long':
            if cfg['BREAKEVEN_AT_1R'] and not pos['be']:
                if last['high'] >= pos['entry'] + pos['sl_dist']:
                    be_triggered = True
            if cfg['TRAILING_AFTER_BE'] and pos['be']:
                candidate = last['close'] - last['atr'] * cfg['TRAILING_ATR_MULT']
                if candidate > pos['sl']:
                    new_trailing_sl = candidate
        else:
            if cfg['BREAKEVEN_AT_1R'] and not pos['be']:
                if last['low'] <= pos['entry'] - pos['sl_dist']:
                    be_triggered = True
            if cfg['TRAILING_AFTER_BE'] and pos['be']:
                candidate = last['close'] + last['atr'] * cfg['TRAILING_ATR_MULT']
                if candidate < pos['sl']:
                    new_trailing_sl = candidate

    return {
        'active_obs'          : active_obs,
        'be_triggered'        : be_triggered,
        'new_trailing_sl'     : new_trailing_sl,
        'should_close_session': should_close_session,
    }
