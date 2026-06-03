# ══════════════════════════════════════════════════════════════════════════════
#  BACKTEST CONFIG
#
#  ← Change ACTIVE_INSTRUMENT to switch between instruments
#
#  Available: "XAUUSD"  |  "XAUUSD_2022"  |  "BTCUSD"  |  "USTEC"
# ══════════════════════════════════════════════════════════════════════════════

ACTIVE_INSTRUMENT  = "XAUUSD_2022"   # ← for backtest scripts (single instrument)
ACTIVE_INSTRUMENTS = ["XAUUSD_2022", "USTEC"]  # ← for live bot (multi-instrument)

# ──────────────────────────────────────────────────────────────────────────────
#  Per-instrument settings
#  name               — display name used in chart titles and terminal output
#  slug               — short ID used in output file names
#  DATA_FILE          — path to CSV (None = use synthetic data)
#  MT5_SYMBOL         — exact symbol name in MT5 terminal (may differ by broker)
#  MT5_TIMEFRAME      — timeframe string: 'H1', 'H4', 'D1', etc.
#  BARS_TO_FETCH      — bars to load each run (must cover EMA warmup + OB_MAX_AGE)
#  LOT_SIZE_UNIT      — minimum lot size for position sizing
#  SPREAD_POINTS      — bid-ask spread in price points (deducted per trade)
#  SLIPPAGE_POINTS    — SL execution slippage in price points
#  COMMISSION_PER_LOT — round-trip commission in $ per 1 standard lot
#  FIXED_LOT          — if set, overrides dynamic sizing (removes compounding distortion)
#  SESSION_START/END  — trading session in UTC hours (start inclusive, end exclusive)
# ──────────────────────────────────────────────────────────────────────────────

INSTRUMENTS = {

    # ── Gold — shorter history (TradingView default export) ───────────────────
    "XAUUSD": {
        "name"              : "Gold (XAU/USD)",
        "slug"              : "xauusd",
        "DATA_FILE"         : "../data/xauusd_1h.csv",
        "MT5_SYMBOL"        : "XAUUSDm",   # Exness symbol name
        "MT5_TIMEFRAME"     : "H1",
        "BARS_TO_FETCH"     : 200,

        "INITIAL_CAPITAL"   : 10_000,
        "RISK_PCT"          : 0.75,
        "LOT_SIZE_UNIT"     : 0.01,        # 0.01 lots = $1/point on Gold
        "POINT_VALUE"       : 1.0,
        "SPREAD_POINTS"     : 0.4,         # Gold ECN typical bid-ask
        "SLIPPAGE_POINTS"   : 0.3,         # SL execution slippage
        "COMMISSION_PER_LOT": 7.0,         # $7 round trip per standard lot
        "FIXED_LOT"         : 0.01,        # fixed micro lot for unbiased stats

        "SWING_LOOKBACK"    : 5,
        "OB_MAX_AGE"        : 80,
        "OB_LOOKBACK"       : 25,
        "MIN_OB_BODY_MULT"  : 0.2,

        "RR_RATIO"          : 3.0,
        "ATR_LEN"           : 14,
        "SL_BUFFER_MULT"    : 0.15,
        "HTF_EMA"           : 50,

        "SESSION_START"     : 7,
        "SESSION_END"       : 21,

        "MAX_TRADES_DAY"    : 2,
        "BREAKEVEN_AT_1R"   : True,
        "TRAILING_AFTER_BE" : True,
        "TRAILING_ATR_MULT" : 1.5,

        "FTMO_PROFIT_TARGET": 10.0,
        "FTMO_MAX_DAILY_LOSS": 5.0,
        "FTMO_MAX_TOTAL_LOSS": 10.0,
        "FTMO_MIN_DAYS"     : 2,
        "FTMO_TIME_LIMIT"   : None,
        "FTMO_BEST_DAY_RULE": 50.0,
        "FTMO_PHASE"        : "1-Step",

        "MC_SIMULATIONS"    : 1000,
        "MC_MAX_TRADES"     : 300,
    },

    # ── Gold — 4-year dataset including 2022 bear market ──────────────────────
    "XAUUSD_2022": {
        "name"              : "Gold 2022–2026 (XAU/USD)",
        "slug"              : "xauusd_2022",
        "DATA_FILE"         : "../data/XAUUSD_H1_2022_2026.csv",
        "MT5_SYMBOL"        : "XAUUSDm",   # Exness symbol name
        "MT5_TIMEFRAME"     : "H1",
        "BARS_TO_FETCH"     : 200,

        "INITIAL_CAPITAL"   : 10_000,
        "RISK_PCT"          : 0.75,
        "LOT_SIZE_UNIT"     : 0.01,
        "POINT_VALUE"       : 1.0,
        "SPREAD_POINTS"     : 0.4,
        "SLIPPAGE_POINTS"   : 0.3,
        "COMMISSION_PER_LOT": 7.0,
        "FIXED_LOT"         : 0.01,

        "SWING_LOOKBACK"    : 5,
        "OB_MAX_AGE"        : 80,
        "OB_LOOKBACK"       : 25,
        "MIN_OB_BODY_MULT"  : 0.2,

        "RR_RATIO"          : 3.0,
        "ATR_LEN"           : 14,
        "SL_BUFFER_MULT"    : 0.15,
        "HTF_EMA"           : 50,

        "SESSION_START"     : 7,
        "SESSION_END"       : 21,

        "MAX_TRADES_DAY"    : 2,
        "BREAKEVEN_AT_1R"   : True,
        "TRAILING_AFTER_BE" : True,
        "TRAILING_ATR_MULT" : 1.5,

        "FTMO_PROFIT_TARGET": 10.0,
        "FTMO_MAX_DAILY_LOSS": 5.0,
        "FTMO_MAX_TOTAL_LOSS": 10.0,
        "FTMO_MIN_DAYS"     : 2,
        "FTMO_TIME_LIMIT"   : None,
        "FTMO_BEST_DAY_RULE": 50.0,
        "FTMO_PHASE"        : "1-Step",

        "MC_SIMULATIONS"    : 1000,
        "MC_MAX_TRADES"     : 300,
    },

    # ── Bitcoin (BTC/USDT) ────────────────────────────────────────────────────
    "BTCUSD": {
        "name"              : "Bitcoin (BTC/USDT)",
        "slug"              : "btcusd",
        "DATA_FILE"         : "../data/btcusd_1h.csv",
        "MT5_SYMBOL"        : "BTCUSD",
        "MT5_TIMEFRAME"     : "H1",
        "BARS_TO_FETCH"     : 200,

        "INITIAL_CAPITAL"   : 10_000,
        "RISK_PCT"          : 0.75,
        "LOT_SIZE_UNIT"     : 1.0,         # 1 lot = $1/point
        "POINT_VALUE"       : 1.0,
        "SPREAD_POINTS"     : 5.0,         # BTC spread ~$5
        "SLIPPAGE_POINTS"   : 2.0,
        "COMMISSION_PER_LOT": 10.0,        # $10 round trip per lot
        "FIXED_LOT"         : 1.0,

        "SWING_LOOKBACK"    : 5,
        "OB_MAX_AGE"        : 80,
        "OB_LOOKBACK"       : 25,
        "MIN_OB_BODY_MULT"  : 0.2,

        "RR_RATIO"          : 3.0,
        "ATR_LEN"           : 14,
        "SL_BUFFER_MULT"    : 0.15,
        "HTF_EMA"           : 50,

        "SESSION_START"     : 0,           # BTC trades 24/7
        "SESSION_END"       : 23,

        "MAX_TRADES_DAY"    : 2,
        "BREAKEVEN_AT_1R"   : True,
        "TRAILING_AFTER_BE" : True,
        "TRAILING_ATR_MULT" : 1.5,

        "FTMO_PROFIT_TARGET": 10.0,
        "FTMO_MAX_DAILY_LOSS": 5.0,
        "FTMO_MAX_TOTAL_LOSS": 10.0,
        "FTMO_MIN_DAYS"     : 2,
        "FTMO_TIME_LIMIT"   : None,
        "FTMO_BEST_DAY_RULE": 50.0,
        "FTMO_PHASE"        : "1-Step",

        "MC_SIMULATIONS"    : 1000,
        "MC_MAX_TRADES"     : 300,
    },

    # ── NASDAQ 100 (USTEC) ────────────────────────────────────────────────────
    "USTEC": {
        "name"              : "NASDAQ 100 (USTEC)",
        "slug"              : "ustec",
        "DATA_FILE"         : "../data/ustec_data.csv",
        "MT5_SYMBOL"        : "USTECm",    # Exness symbol name
        "MT5_TIMEFRAME"     : "H1",
        "BARS_TO_FETCH"     : 200,

        "INITIAL_CAPITAL"   : 10_000,
        "RISK_PCT"          : 0.75,
        "LOT_SIZE_UNIT"     : 1.0,
        "POINT_VALUE"       : 1.0,
        "SPREAD_POINTS"     : 1.0,         # NAS100 ~1 point spread
        "SLIPPAGE_POINTS"   : 0.5,
        "COMMISSION_PER_LOT": 0.0,         # Exness indices are spread-based
        "FIXED_LOT"         : 1.0,

        "SWING_LOOKBACK"    : 5,
        "OB_MAX_AGE"        : 80,
        "OB_LOOKBACK"       : 25,
        "MIN_OB_BODY_MULT"  : 0.2,

        "RR_RATIO"          : 3.0,
        "ATR_LEN"           : 14,
        "SL_BUFFER_MULT"    : 0.15,
        "HTF_EMA"           : 50,

        "SESSION_START"     : 7,
        "SESSION_END"       : 21,          # full London + NY session

        "MAX_TRADES_DAY"    : 2,
        "BREAKEVEN_AT_1R"   : True,
        "TRAILING_AFTER_BE" : True,
        "TRAILING_ATR_MULT" : 1.5,

        "FTMO_PROFIT_TARGET": 10.0,
        "FTMO_MAX_DAILY_LOSS": 5.0,
        "FTMO_MAX_TOTAL_LOSS": 10.0,
        "FTMO_MIN_DAYS"     : 2,
        "FTMO_TIME_LIMIT"   : None,
        "FTMO_BEST_DAY_RULE": 50.0,
        "FTMO_PHASE"        : "1-Step",

        "MC_SIMULATIONS"    : 1000,
        "MC_MAX_TRADES"     : 300,
    },
}
