#!/usr/bin/env python
"""
V3 模拟推送 — 基于上周五(2026-06-19)真实行情数据
"""
import sys, os, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
os.chdir(os.path.join(os.path.dirname(__file__), '..', '..'))

import pandas as pd
import numpy as np
from datetime import datetime
from v3.data import DataFetcher
from v3.factors import UltraShortFactorComputer
from v3.scorer import UltraShortScorer
from v3.strategy import UltraShortStrategy
from v3.market_state import MarketState
from v3.push import send_wechat, build_morning_card

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s %(message)s')
logger = logging.getLogger('v3_sim_push')

# 1. 市场状态
market = MarketState.assess()
logger.info(f"市场状态: {market['mode_label']} (评分={market['composite']})")

# 2. 获取行情 — 覆盖涨幅榜前200只
df = DataFetcher()
codes = (
    [f'{i:06d}' for i in range(1, 300)]     # sz 000001-000299
    + [f'6{i:05d}' for i in range(0, 200)]  # sh 600000-600199
    + [f'3{i:05d}' for i in range(0, 100)]  # sz 300001-300099 (创业板)
)
quotes = df.batch_fetch_quotes(codes)

if quotes is None or quotes.empty:
    logger.error("无法获取行情数据")
    sys.exit(1)

q = quotes[quotes['price'] > 0].copy()
logger.info(f"获取行情: {len(q)} 只")

# 3. 基础筛选 (V3标准: 涨幅2-7%, 价格>=5)
q = q[q['change_pct'].between(2.0, 7.0)].copy()
q = q[q['price'] >= 5].copy()
q = q[q['amount'] >= 5e7].copy()  # 5000万成交额
logger.info(f"基础筛选后: {len(q)} 只")

# 4. 重命名列以适配因子计算器
q.rename(columns={
    'change_pct': 'pct_chg',
    'close_position': 'close_position',
}, inplace=True)

# 添加因子计算所需的额外列
q['market_cap'] = 0  # 占位
q['sector'] = '未知'
# 计算量比 (当日volume / 5日均量 - 用全市场均值1.2模拟)
q['volume_ratio'] = 1.0 + (q['pct_chg'] - q['pct_chg'].mean()) / 50

# 5. 因子计算
fc = UltraShortFactorComputer()
q = fc.compute(q)

# 6. 打分
scorer = UltraShortScorer()
q = scorer.score(q)

# 7. 早盘筛选
strategy = UltraShortStrategy()
screened = strategy.screen_morning(q)
top5 = screened.head(5).to_dict('records')

logger.info(f"Top 5 候选:")
for i, s in enumerate(top5):
    logger.info(f"  {i+1}. {s['code']} {s.get('name','?')}  "
                f"评分={s.get('final_score',0):.1f}  "
                f"涨幅={s.get('pct_chg',0):+.2f}%  "
                f"价格={s.get('price',0):.2f}")

# 8. 推送
html = build_morning_card(top5, market)
result = send_wechat(
    "📈 V3 模拟推送 (基于上周五数据)",
    html,
    template='html',
)

if result:
    print("✅ 推送成功！检查微信")
else:
    print("❌ 推送失败")
