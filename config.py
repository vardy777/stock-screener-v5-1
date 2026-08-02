"""
选股系统 - 核心配置 v2.1 (Phase 2)
"""

TIMES = {
    "market_open": "09:30", "market_close": "15:00",
    "morning_screen": "09:35", "afternoon_confirm": "14:30",
    "buy_window_start": "14:45", "buy_window_end": "14:55",
}

# --- 基础筛选 ---
MORNING_FILTERS = {
    "min_change_pct": 2.0, "max_change_pct": 7.0,
    "min_price": 5.0, "max_price": 100.0,
    "min_amount": 5e7,
}

AFTERNOON_FILTERS = {
    "min_change_pct": 1.0, "max_change_pct": 7.0,
    "min_close_position": 0.6, "min_candle_body": 0.5,
    "max_market_decline": 1.5, "min_amount": 3e7,
}

# --- Phase 1: 技术面因子 ---
TECHNICAL_FILTERS = {
    "require_ma_bullish": False,
    "require_macd_golden": False,
    "tech_min_total_score": 20,
    "require_yesterday_limit_up": False,
    "min_zt_count": 10,
}

# --- Phase 2: 资金流因子 (NEW) ---
CAPITAL_FILTERS = {
    "min_main_net": -1000,          # 主力净流入底线(万元), -1000万以下过滤
    "min_capital_score": 0,         # 资金流最低评分
    "capital_weight": 0.25,         # 资金流在综合评分中的权重
    "require_main_positive": False, # True=强制要求主力净流入
}

# --- 综合打分权重 ---
SCORING_WEIGHTS = {
    "close_position": 0.35,   # 日内位置 35% (因子有效性最高!)
    "change_pct": 0.20,       # 涨幅动量 20%
    "tech_score": 0.20,       # 技术面 20%
    "capital_score": 0.10,    # 资金流 10%
    "ma_bonus": 0.08,         # MA加分 8%
    "macd_bonus": 0.07,       # MACD加分 7%
}

# --- 风控 ---
RISK_CONTROL = {
    "max_positions": 3, "max_single_position_pct": 30,
    "total_position_pct": 80, "stop_loss_pct": -3.0,
    "target_profit_pct": 2.0,
}

# --- 路径 ---
import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
REPORT_DIR = os.path.join(DATA_DIR, "reports")
JOURNAL_PATH = os.path.join(DATA_DIR, "trade_journal.csv")

for d in [DATA_DIR, REPORT_DIR]:
    os.makedirs(d, exist_ok=True)
