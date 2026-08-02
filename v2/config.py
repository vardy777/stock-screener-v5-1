"""
V2 系统核心配置 — Windows 适配 (安全版)

敏感配置从环境变量读取，不在代码中硬编码。
创建 .env 文件或在系统环境变量中设置:

    PUSHPLUS_TOKEN=xxx       # PushPlus 推送Token
    HOLDING_COST=15.348      # 持仓成本价 (可选)
    HOLDING_QTY=21900        # 持仓股数 (可选)
"""

import os

# ── 目录结构 ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # stock-screener/
SCRIPTS_DIR = os.path.join(BASE_DIR, 'v2', 'scripts')
DATA_DIR = os.path.join(BASE_DIR, 'data')

LEGACY_CACHE_DIR = os.path.join(DATA_DIR, 'legacy_cache')

# ── 数据文件 ──────────────────────────────────────────────
IC_FILE = os.path.join(BASE_DIR, 'v2', 'factor_ic.json')
FACTOR_IC_FILE = IC_FILE  # alias for backward compat

PE_PB_CACHE = os.path.join(LEGACY_CACHE_DIR, 'pe_pb_cache.json')
WIN_RATE = os.path.join(LEGACY_CACHE_DIR, 'win_rate_data.json')
WIN_RATE_DATA = WIN_RATE  # alias for backward compat
MARKET_DB = os.path.join(LEGACY_CACHE_DIR, 'market.db')

JOURNAL_PATH = os.path.join(DATA_DIR, 'trade_journal.csv')

# ── 推送服务 (从环境变量读取) ────────────────────────────
DASHBOARD_PORT = 8899
PUSHPLUS_TOKEN = os.getenv("PUSHPLUS_TOKEN", "")
TOKEN = PUSHPLUS_TOKEN  # alias for backward compat

# ── 持仓信息 (从环境变量读取, 可选) ─────────────────────
HOLDING_COST = float(os.getenv("HOLDING_COST", "0"))
HOLDING_QTY = int(os.getenv("HOLDING_QTY", "0"))

# ── 21因子列表 ──────────────────────────────────────────
FACTOR_21 = [
    "momentum_1d", "momentum_5d", "momentum_10d", "momentum_20d",
    "breakthrough_1d", "volume_ratio", "volatility_20d", "turn_rate",
    "rsi_14d", "amount_stability", "up_down_vol_ratio", "vol_price_sync",
    "log_market_cap", "pe_ttm", "pb_mrq", "momentum_accel",
    "overnight_gap", "chan_breakout", "price_vs_poc",
    "sector_strength", "dist_to_20d_high",
]

# ── 策略配置 ────────────────────────────────────────────
STRATEGIES = {
    "breakthrough": {
        "filters": {
            "chan_breakout": 0.5, "volume_ratio": 1.3,
            "dist_to_20d_high": -3.0, "sector_strength": -1.0,
            "amount": 3e8, "price_max": 150,
        },
        "base_weight": 0.40,
    },
    "momentum": {
        "filters": {
            "rsi_14d_min": 45, "rsi_14d_max": 72,
            "amount_stability": 0.4, "overnight_gap": -0.5,
            "amount": 2e8, "price_max": 150,
        },
        "base_weight": 0.10,
    },
    "oversold": {
        "filters": {
            "pct_chg_max": -5.0, "rsi_14d_max": 38,
            "volume_ratio": 0.8, "amount": 1e8, "price_max": 150,
        },
        "base_weight": 0.10,
    },
}

# ── 风控参数 ────────────────────────────────────────────
RISK = {
    "max_positions": 5,
    "max_single_position_pct": 0.50,
    "max_industry_exposure": 0.40,
    "stop_loss_pct": -3.0,
    "target_profit_pct": 2.0,
}

# ── Kelly 仓位配置 ─────────────────────────────────────
KELLY = {
    "kelly_cap": 0.50,
    "kelly_floor": 0.0,
    "weight_cap": 0.50,
    "weight_floor": 0.10,
    "base_weight": {"breakthrough": 0.40, "momentum": 0.10, "oversold": 0.10},
}

# ── 市场自适应配额 ─────────────────────────────────────
QUOTAS = {
    "risk_on": {"breakthrough": 4, "momentum": 1, "oversold": 0},
    "risk_off": {"breakthrough": 0, "momentum": 1, "oversold": 4},
    "neutral": {"breakthrough": 2, "momentum": 2, "oversold": 1},
}

# ── 确保目录存在 ─────────────────────────────────────────
for d in [DATA_DIR, LEGACY_CACHE_DIR, SCRIPTS_DIR]:
    os.makedirs(d, exist_ok=True)
