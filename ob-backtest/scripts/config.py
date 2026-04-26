# ══════════════════════════════════════════════════════════════════════════════
#  BACKTEST CONFIG
#
#  ← Change ACTIVE_INSTRUMENT to switch between instruments
#
#  Available: "XAUUSD"  |  "XAUUSD_2022"  |  "BTCUSD"  |  "USTEC"
# ══════════════════════════════════════════════════════════════════════════════

ACTIVE_INSTRUMENT = "XAUUSD_2022"   # ← change this, then run backtest.py

# ──────────────────────────────────────────────────────────────────────────────
#  Per-instrument settings
#  name          — display name used in chart titles and terminal output
#  slug          — short ID used in output file names  (e.g. xauusd_2022_ob_report.png)
#  DATA_FILE     — path to your CSV  (None = use synthetic data)
#  LOT_SIZE_UNIT — minimum lot size for position sizing
#  SESSION_START/END — trading session in UTC hours (start inclusive, end exclusive)
# ──────────────────────────────────────────────────────────────────────────────

INSTRUMENTS = {

    # ── Gold — shorter history (TradingView default export) ───────────────────
    "XAUUSD": {
        "name"              : "Gold (XAU/USD)",
        "slug"              : "xauusd",
        "DATA_FILE"         : "../data/xauusd_1h.csv",

        # Account
        "INITIAL_CAPITAL"   : 10_000,
        "RISK_PCT"          : 0.75,        # % of account risked per trade
        "LOT_SIZE_UNIT"     : 0.01,        # 0.01 lots = $1/point on Gold
        "POINT_VALUE"       : 1.0,

        # Structure detection
        "SWING_LOOKBACK"    : 5,
        "OB_MAX_AGE"        : 80,
        "OB_LOOKBACK"       : 25,
        "MIN_OB_BODY_MULT"  : 0.2,

        # Entry
        "RR_RATIO"          : 3.0,
        "ATR_LEN"           : 14,
        "SL_BUFFER_MULT"    : 0.15,
        "HTF_EMA"           : 50,

        # Session (UTC) — London + NY combined
        "SESSION_START"     : 7,
        "SESSION_END"       : 18,

        # Risk management
        "MAX_TRADES_DAY"    : 2,
        "BREAKEVEN_AT_1R"   : True,
        "TRAILING_AFTER_BE" : True,
        "TRAILING_ATR_MULT" : 1.5,

        # FTMO 2026 rules
        "FTMO_PROFIT_TARGET": 10.0,
        "FTMO_MAX_DAILY_LOSS": 5.0,
        "FTMO_MAX_TOTAL_LOSS": 10.0,
        "FTMO_MIN_DAYS"     : 2,
        "FTMO_TIME_LIMIT"   : None,
        "FTMO_BEST_DAY_RULE": 50.0,
        "FTMO_PHASE"        : "1-Step",

        # Monte Carlo
        "MC_SIMULATIONS"    : 1000,
        "MC_MAX_TRADES"     : 300,
    },

    # ── Gold — 4-year dataset including 2022 bear market ──────────────────────
    "XAUUSD_2022": {
        "name"              : "Gold 2022–2026 (XAU/USD)",
        "slug"              : "xauusd_2022",
        "DATA_FILE"         : "../data/XAUUSD_H1_2022_2026.csv",

        "INITIAL_CAPITAL"   : 10_000,
        "RISK_PCT"          : 0.75,
        "LOT_SIZE_UNIT"     : 0.01,
        "POINT_VALUE"       : 1.0,

        "SWING_LOOKBACK"    : 5,
        "OB_MAX_AGE"        : 80,
        "OB_LOOKBACK"       : 25,
        "MIN_OB_BODY_MULT"  : 0.2,

        "RR_RATIO"          : 3.0,
        "ATR_LEN"           : 14,
        "SL_BUFFER_MULT"    : 0.15,
        "HTF_EMA"           : 50,

        "SESSION_START"     : 7,
        "SESSION_END"       : 18,

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

        "INITIAL_CAPITAL"   : 10_000,
        "RISK_PCT"          : 0.75,
        "LOT_SIZE_UNIT"     : 1.0,         # 1 lot BTC = $1/point
        "POINT_VALUE"       : 1.0,

        "SWING_LOOKBACK"    : 5,
        "OB_MAX_AGE"        : 80,
        "OB_LOOKBACK"       : 25,
        "MIN_OB_BODY_MULT"  : 0.2,

        "RR_RATIO"          : 3.0,
        "ATR_LEN"           : 14,
        "SL_BUFFER_MULT"    : 0.15,
        "HTF_EMA"           : 50,

        # NYSE session hours (data timestamps are EST)
        "SESSION_START"     : 9,
        "SESSION_END"       : 16,

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

        "INITIAL_CAPITAL"   : 10_000,
        "RISK_PCT"          : 0.75,
        "LOT_SIZE_UNIT"     : 1.0,
        "POINT_VALUE"       : 1.0,

        "SWING_LOOKBACK"    : 5,
        "OB_MAX_AGE"        : 80,
        "OB_LOOKBACK"       : 25,
        "MIN_OB_BODY_MULT"  : 0.2,

        "RR_RATIO"          : 3.0,
        "ATR_LEN"           : 14,
        "SL_BUFFER_MULT"    : 0.15,
        "HTF_EMA"           : 50,

        "SESSION_START"     : 9,
        "SESSION_END"       : 16,

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
