"""
V3 超短系统核心配置 — 尾盘买入/次日竞价卖出

敏感配置从环境变量读取，不在代码中硬编码。
创建 .env 文件或在系统环境变量中设置:

    PUSHPLUS_TOKEN=***       # PushPlus 推送Token
    HOLDING_COST=15.348      # 持仓成本价 (可选)
    HOLDING_QTY=21900        # 持仓股数 (可选)
"""

import os

from strategy_spec import DEFAULT_SPEC

# ── 从 .env 文件加载（cron 环境无桌面 env vars）─
_ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(_ENV_FILE):
    with open(_ENV_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                key, val = key.strip(), val.strip()
                if key not in os.environ:  # 不覆盖已有环境变量
                    os.environ[key] = val

# ── 目录结构 ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # stock-screener/
SCRIPTS_DIR = os.path.join(BASE_DIR, 'v3', 'scripts')
DATA_DIR = os.path.join(BASE_DIR, 'v3', 'data')

LEGACY_CACHE_DIR = os.path.join(DATA_DIR, 'legacy_cache')

# ── 数据文件 ──────────────────────────────────────────────
# V3不再使用IC，用因子权重文件替代
FACTOR_WEIGHTS_FILE = os.path.join(BASE_DIR, 'v3', 'factor_weights.json')

PE_PB_CACHE = os.path.join(LEGACY_CACHE_DIR, 'pe_pb_cache.json')
WIN_RATE = os.path.join(LEGACY_CACHE_DIR, 'win_rate_data.json')
WIN_RATE_DATA = WIN_RATE  # alias for backward compat
MARKET_DB = os.path.join(LEGACY_CACHE_DIR, 'market.db')

# V3 buy/sell commands delegate to the root trade_journal module, so settlement
# must read the same file rather than a second, silently empty V3 journal.
JOURNAL_PATH = os.path.join(BASE_DIR, 'data', 'trade_journal.csv')

# ── 推送服务 (从环境变量读取) ────────────────────────────
DASHBOARD_PORT = 8899
PUSHPLUS_TOKEN = os.getenv("PUSHPLUS_TOKEN", "")
TOKEN = PUSHPLUS_TOKEN  # alias for backward compat

# ── 持仓信息 (从环境变量读取, 可选) ─────────────────────
HOLDING_COST = float(os.getenv("HOLDING_COST", "0"))
HOLDING_QTY = int(os.getenv("HOLDING_QTY", "0"))

# ── 尾盘买入窗口 ────────────────────────────────────────
BUY_WINDOW = {
    'start': '14:50',
    'end': '14:51',
    'prefer': '14:50',
}

# ── 仓位管理 ─────────────────────────────────────────────
POSITION_SIZE = DEFAULT_SPEC.max_position_fraction  # 单票最多总权益的1/3
POSITION = {
    'max_positions': DEFAULT_SPEC.max_positions,
    'per_position_pct': DEFAULT_SPEC.max_position_fraction,
    'stop_loss_pct': -3.0,
    'target_profit_pct': DEFAULT_SPEC.target_net_return * 100,
}

# ── 成交与费用 (研究、回测、模拟盘共用) ───────────────────
EXECUTION = {
    'signal_cutoff': DEFAULT_SPEC.signal_cutoff,
    'buy_start': DEFAULT_SPEC.buy_start,
    'buy_end': DEFAULT_SPEC.buy_end,
    'sell_start': DEFAULT_SPEC.sell_start,
    'buy_slippage_rate': DEFAULT_SPEC.buy_slippage_rate,
    'sell_slippage_rate': DEFAULT_SPEC.sell_slippage_rate,
    'commission_rate': DEFAULT_SPEC.fees.commission_rate,
    'minimum_commission': DEFAULT_SPEC.fees.minimum_commission,
    'stamp_duty_rate': DEFAULT_SPEC.fees.stamp_duty_rate,
    'transfer_fee_rate': DEFAULT_SPEC.fees.transfer_fee_rate,
}

# ── 因子评分权重 (V3 factors.py 将使用) ─────────────────
SCORING_WEIGHTS = {
    'momentum': 0.25,
    'volume': 0.20,
    'breakthrough': 0.20,
    'fundamental': 0.15,
    'market_state': 0.10,
    'risk': 0.10,
}

# ── 风控参数 ────────────────────────────────────────────
RISK = {
    'max_positions': DEFAULT_SPEC.max_positions,
    'max_single_position_pct': DEFAULT_SPEC.max_position_fraction,
    'max_industry_exposure': 0.40,
    'stop_loss_pct': -3.0,
    'target_profit_pct': DEFAULT_SPEC.target_net_return * 100,
}

# ── 确保目录存在 ─────────────────────────────────────────
for d in [DATA_DIR, LEGACY_CACHE_DIR, SCRIPTS_DIR]:
    os.makedirs(d, exist_ok=True)
