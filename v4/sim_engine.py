"""
V4 独立研究模拟交易引擎。

数据传输:
  - 买入: BuyDecision.select() → 从候选中选择并执行开仓
  - 卖出: 由外部提供 sell_price (通常为次日开盘价), 调用 close_position()
  - 每日结算: daily_settle() 记录当日总权益和收益率

数据持久化: v4/data/paper_account.json
"""

import json
import os
import copy
import logging
from datetime import datetime, date
from typing import Optional

from strategy_spec import DEFAULT_SPEC, TradeCostModel

logger = logging.getLogger(__name__)

# ── 路径 ──────────────────────────────────────────────────
from v4.config import DATA_DIR

DEFAULT_ACCOUNT_PATH = os.path.join(DATA_DIR, 'paper_account.json')

# ── 默认账户模板 ──────────────────────────────────────────
_DEFAULT_DATA = {
    'capital': 100000.0,
    'initial_capital': 100000.0,
    'positions': [],
    'history': [],
    'daily_pnl': [],
    'last_updated': '',
    'fee_model_version': 'a_share_v1',
}


# ============================================================
#  SimAccount  模拟账户
# ============================================================

class SimAccount:
    """模拟账户 — 追踪本金、持仓、交易历史

    Parameters
    ----------
    data_path : str, optional
        账户数据 JSON 文件路径。默认 DATA_DIR/sim_account.json。

    Examples
    --------
    >>> acct = SimAccount()
    >>> acct.open_position('600000', '浦发银行', 8.50, 1100,
    ...                    strategy='v4_paper_observation', target_sell=8.67, stop_loss=8.25)
    >>> acct.close_position('600000', 8.67)
    >>> acct.daily_settle('2026-06-22')
    """

    def __init__(self, data_path: Optional[str] = None,
                 cost_model: Optional[TradeCostModel] = None):
        self.path = data_path or DEFAULT_ACCOUNT_PATH
        self.cost_model = cost_model or TradeCostModel(DEFAULT_SPEC)
        self.data = self._load()
        self._migrate_open_positions_to_fee_model()

    def _migrate_open_positions_to_fee_model(self) -> None:
        """Apply buy fees once to positions created by the legacy simulator."""

        migrated = 0
        total_fee = 0.0
        for position in self.data.get('positions', []):
            if 'cash_out' in position:
                continue
            price = float(position.get('buy_price', 0) or 0)
            shares = int(position.get('shares', 0) or 0)
            if price <= 0 or shares <= 0:
                continue
            buy = self.cost_model.buy_cash_required(price, shares)
            position['cost'] = round(buy['notional'], 2)
            position['cash_out'] = round(buy['cash_out'], 2)
            position['buy_commission'] = round(buy['commission'], 4)
            position['buy_transfer_fee'] = round(buy['transfer_fee'], 4)
            position['buy_fees'] = round(buy['total'], 4)
            total_fee += buy['total']
            migrated += 1
        if migrated:
            self.data['capital'] = round(
                max(0.0, float(self.data.get('capital', 0.0)) - total_fee), 2
            )
            self.data['fee_model_version'] = 'a_share_v1'
            logger.info('迁移旧持仓费用模型: %d只, 补计买入费%.2f元', migrated, total_fee)

    # ── 属性 ──────────────────────────────────────────────

    @property
    def position_count(self) -> int:
        """当前持仓数"""
        return len(self.data.get('positions', []))

    @property
    def available_capital(self) -> float:
        """可用资金"""
        return float(self.data.get('capital', 0.0))

    @property
    def total_equity(self) -> float:
        """总权益 = 现金 + 持仓市值估算

        持仓市值 = 买入价 * 股数 (未卖出前按成本价保守估算)
        """
        capital = self.available_capital
        positions_value = 0.0
        for pos in self.data.get('positions', []):
            positions_value += float(pos.get('buy_price', 0)) * int(pos.get('shares', 0))
        return round(capital + positions_value, 2)

    @property
    def cumulative_return(self) -> float:
        """累计收益率 = (总权益 - 初始本金) / 初始本金 * 100"""
        ic = float(self.data.get('initial_capital', 1.0))
        if ic <= 0:
            return 0.0
        return round((self.total_equity - ic) / ic * 100, 2)

    # ── 加载 / 保存 ──────────────────────────────────────

    def _load(self) -> dict:
        """从 JSON 文件加载账户数据，不存在时返回默认模板"""
        if os.path.exists(self.path):
            try:
                with open(self.path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # 确保必要字段存在
                for k, v in _DEFAULT_DATA.items():
                    data.setdefault(k, v)
                return data
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f'读取账户文件失败 [{self.path}]: {e}, 使用默认数据')
        return copy.deepcopy(_DEFAULT_DATA)

    def _save(self):
        """保存账户数据到 JSON 文件"""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.data['last_updated'] = str(date.today())
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    # ── 开仓 ──────────────────────────────────────────────

    def open_position(self, code: str, name: str, buy_price: float, shares: int,
                      strategy: str = 'v4_paper_observation',
                      target_sell: Optional[float] = None,
                      stop_loss: Optional[float] = None):
        """开仓: 扣除资金, 增加持仓

        Parameters
        ----------
        code : str
            股票代码。
        name : str
            股票名称。
        buy_price : float
            买入价格。
        shares : int
            买入股数。
        strategy : str
            策略标识，默认 'v4_paper_observation'。
        target_sell : float, optional
            目标卖出参考价。默认按扣除成本后净收益 +1% 计算。
        stop_loss : float, optional
            止损价。默认 buy_price * 0.97 (-3%)。
        """
        buy = self.cost_model.buy_cash_required(buy_price, shares)
        cost = buy['notional']
        cash_out = buy['cash_out']
        capital = self.data['capital']
        if cash_out > capital:
            raise ValueError(
                f'资金不足: 需要 {cash_out:.2f}(含费用), 可用 {capital:.2f}'
            )

        if target_sell is None:
            target_sell = round(
                self.cost_model.required_sell_reference(
                    buy_price / (1 + DEFAULT_SPEC.buy_slippage_rate),
                    shares,
                    DEFAULT_SPEC.target_net_return,
                ),
                2,
            )
        if stop_loss is None:
            stop_loss = round(buy_price * 0.97, 2)     # -3% 默认止损

        self.data['capital'] = round(capital - cash_out, 2)
        today = str(date.today())
        self.data['positions'].append({
            'code': code,
            'name': name,
            'buy_date': today,
            'buy_price': round(buy_price, 2),
            'shares': shares,
            'cost': round(cost, 2),
            'cash_out': round(cash_out, 2),
            'buy_commission': round(buy['commission'], 4),
            'buy_transfer_fee': round(buy['transfer_fee'], 4),
            'buy_fees': round(buy['total'], 4),
            'target_sell': round(target_sell, 2),
            'stop_loss': round(stop_loss, 2),
            'strategy': strategy,
        })
        self._save()
        logger.info(
            f'开仓 {code} {name}: '
            f'价格={buy_price:.2f}, 股数={shares}, 含费成本={cash_out:.2f}, '
            f'目标={target_sell:.2f}, 止损={stop_loss:.2f}'
        )

    # ── 平仓 ──────────────────────────────────────────────

    def close_position(self, code: str, sell_price: float,
                       sell_date: Optional[str] = None,
                       sell_reason: str = ''):
        """平仓: 卖出持仓, 计算盈亏, 增加资金, 移入历史

        Parameters
        ----------
        code : str
            股票代码（从持仓中查找）。
        sell_price : float
            卖出价格。
        sell_date : str, optional
            卖出日期，默认今天。
        sell_reason : str
            卖出原因描述。
        """
        positions = self.data.get('positions', [])
        idx = None
        for i, pos in enumerate(positions):
            if pos['code'] == code:
                idx = i
                break

        if idx is None:
            logger.warning(f'未找到持仓: {code}')
            return

        pos = positions.pop(idx)
        buy_price = float(pos['buy_price'])
        shares = int(pos['shares'])
        sell = self.cost_model.sell_cash_received(sell_price, shares)
        buy_cash_out = float(pos.get('cash_out', buy_price * shares))
        pnl_amount = round(sell['cash_in'] - buy_cash_out, 2)
        pnl_pct = round(pnl_amount / buy_cash_out * 100, 2) if buy_cash_out else 0.0
        gross_pnl_pct = round((sell_price - buy_price) / buy_price * 100, 2)

        # 资金回笼
        proceeds = round(sell['cash_in'], 2)
        self.data['capital'] = round(self.data['capital'] + proceeds, 2)

        if sell_date is None:
            sell_date = str(date.today())

        # 移入历史
        history = self.data.setdefault('history', [])
        history.append({
            'code': code,
            'name': pos.get('name', ''),
            'buy_date': pos.get('buy_date', ''),
            'sell_date': sell_date,
            'buy_price': buy_price,
            'sell_price': round(sell_price, 2),
            'shares': shares,
            'pnl_pct': pnl_pct,
            'pnl_amount': pnl_amount,
            'gross_pnl_pct': gross_pnl_pct,
            'buy_fees': round(float(pos.get('buy_fees', 0.0)), 4),
            'sell_commission': round(sell['commission'], 4),
            'sell_transfer_fee': round(sell['transfer_fee'], 4),
            'stamp_duty': round(sell['stamp_duty'], 4),
            'sell_fees': round(sell['total'], 4),
            'total_fees': round(float(pos.get('buy_fees', 0.0)) + sell['total'], 4),
            'cash_out': round(buy_cash_out, 2),
            'cash_in': round(sell['cash_in'], 2),
            'target_1pct': pnl_pct >= DEFAULT_SPEC.target_net_return * 100,
            'fee_model_version': 'a_share_v1',
            'strategy': pos.get('strategy', 'v4_paper_observation'),
            'sell_reason': sell_reason,
        })

        self._save()
        logger.info(
            f'平仓 {code} {pos.get("name","")}: '
            f'买入={buy_price:.2f}, 卖出={sell_price:.2f}, '
            f'盈亏={pnl_pct:+.2f}% ({pnl_amount:+.2f})'
        )
        return history[-1]

    # ── 每日结算 ──────────────────────────────────────────

    def daily_settle(self, date_str: Optional[str] = None):
        """每日结算: 记录当日总权益和收益率

        Parameters
        ----------
        date_str : str, optional
            结算日期，格式 'YYYY-MM-DD'，默认今天。
        """
        if date_str is None:
            date_str = str(date.today())

        daily_pnl = self.data.setdefault('daily_pnl', [])

        equity = self.total_equity
        ic = float(self.data.get('initial_capital', 1.0))

        # 计算当日收益率（相对于前一日）
        prev_equity = None
        if daily_pnl:
            prev_equity = daily_pnl[-1].get('end_capital', ic)
        else:
            prev_equity = ic

        daily_return = round((equity - prev_equity) / prev_equity * 100, 2) if prev_equity else 0.0
        cumulative_return = round((equity - ic) / ic * 100, 2) if ic > 0 else 0.0

        daily_pnl.append({
            'date': date_str,
            'end_capital': round(equity, 2),
            'daily_return': daily_return,
            'cumulative_return': cumulative_return,
        })

        self._save()
        logger.info(
            f'每日结算 [{date_str}]: '
            f'权益={equity:.2f}, 日收益={daily_return:+.2f}%, '
            f'累计={cumulative_return:+.2f}%'
        )

    # ── 查询摘要 ──────────────────────────────────────────

    def get_positions_summary(self) -> list:
        """返回持仓摘要（看板用）

        Returns
        -------
        list[dict]
            每笔持仓: {code, name, buy_date, buy_price, shares, cost,
                       target_sell, stop_loss, strategy}
        """
        return list(self.data.get('positions', []))

    def get_history_summary(self, n: int = 20) -> list:
        """返回最近 n 笔已平仓交易（看板用）

        Parameters
        ----------
        n : int
            返回笔数，默认 20。

        Returns
        -------
        list[dict]
            按交易时间倒序排列（最近交易在先）。
        """
        history = list(self.data.get('history', []))
        # 反转: 最后添加的交易（最近发生的）排在最前
        history.reverse()
        return history[:n]

    def get_pnl_chart_data(self) -> dict:
        """返回盈亏曲线数据（看板用）

        Returns
        -------
        dict
            dates: list[str] — 日期
            equities: list[float] — 每日总权益
            daily_returns: list[float] — 每日收益率(%)
            cumulative_returns: list[float] — 累计收益率(%)
        """
        daily_pnl = self.data.get('daily_pnl', [])
        return {
            'dates': [d.get('date', '') for d in daily_pnl],
            'equities': [d.get('end_capital', 0) for d in daily_pnl],
            'daily_returns': [d.get('daily_return', 0) for d in daily_pnl],
            'cumulative_returns': [d.get('cumulative_return', 0) for d in daily_pnl],
        }

    # ── 重置 ──────────────────────────────────────────────

    def reset(self, initial_capital: float = 100000.0):
        """重置账户到初始状态（清空所有持仓和交易记录）"""
        self.data = {
            'capital': initial_capital,
            'initial_capital': initial_capital,
            'positions': [],
            'history': [],
            'daily_pnl': [],
            'last_updated': str(date.today()),
            'fee_model_version': 'a_share_v1',
        }
        self._save()
        logger.info(f'账户已重置，初始本金: {initial_capital:.2f}')


# ── 关键词 → 行业映射 (用于盘后行情无行业数据时的分散) ──

SECTOR_KEYWORDS = [
    ('银行', ['银行', '工商', '建设', '农业', '中行', '招行', '兴业', '浦发',
              '民生', '中信银行', '光大', '平安银行', '华夏', '北京银行']),
    ('证券', ['证券', '券商', '中信建投', '华泰', '海通', '国泰', '招商证券',
              '广发', '东方证券', '申万', '银河', '光大证券']),
    ('保险', ['保险', '人寿', '人保', '太保', '新华']),
    ('白酒', ['茅台', '五粮液', '泸州', '汾酒', '洋河', '古井', '酒鬼',
              '舍得', '水井坊', '老白干', '今世缘', '口子窖']),
    ('医药', ['医药', '药业', '医疗', '生物', '药明', '恒瑞', '复星',
              '华润双鹤', '白云山', '云南白药', '片仔癀', '同仁堂']),
    ('房地产', ['地产', '万科', '保利', '华侨城', '金地', '招商蛇口',
                '绿地', '华夏幸福', '新城']),
    ('汽车', ['汽车', '比亚迪', '长城', '长安', '上汽', '广汽', '福田',
              '江淮', '江铃', '宇通', '中通']),
    ('食品饮料', ['伊利', '蒙牛', '双汇', '海天', '中炬', '安井',
                   '绝味', '桃李', '涪陵']),
    ('电子', ['电子', '海康', '大华', '京东方', 'TCL', '立讯', '歌尔',
              '蓝思', '鹏鼎']),
    ('半导体', ['半导体', '芯片', '中芯', '华虹', '兆易', '韦尔', '北方华创',
                '长电', '通富']),
    ('新能源', ['宁德', '隆基', '通威', '阳光', '天合', '晶澳', '晶科',
                '亿纬', '恩捷', '先导']),
    ('军工', ['军工', '航天', '航空', '中航', '中国船舶', '中国重工',
              '沈飞', '西飞', '洪都']),
    ('钢铁', ['钢铁', '宝钢', '鞍钢', '首钢', '河钢', '太钢', '马钢',
              '沙钢', '华菱']),
    ('煤炭', ['煤炭', '神华', '陕煤', '兖矿', '中煤', '潞安', '山西焦煤']),
    ('电力', ['电力', '华能', '国电', '大唐', '华电', '长江电力',
              '三峡', '国投电力']),
    ('通信', ['移动', '联通', '电信', '中兴', '烽火', '光迅']),
    ('计算机', ['软件', '计算机', '用友', '金山', '科大讯飞', '恒生',
                '广联达', '中科曙光']),
    ('家电', ['美的', '格力', '海尔', '海信', 'TCL', '苏泊尔', '九阳']),
    ('建筑', ['建筑', '基建', '建设', '中铁', '铁建', '交建', '中建', '电建', '能建',
              '中冶']),
    ('农业', ['牧原', '温氏', '新希望', '大北农', '隆平', '登海', '北大荒']),
    ('化工', ['化工', '化学', '华鲁', '万华', '浙江龙盛', '中化']),
    ('有色', ['有色', '黄金', '铜', '铝业', '稀土', '锂业', '华友', '寒锐',
              '洛阳钼业', '江西铜业']),
    ('机械', ['机械', '装备', '三一', '中联', '徐工', '潍柴', '恒立']),
    ('环保', ['环保', '环境', '碧水源', '启迪', '伟明']),
    ('传媒', ['传媒', '文化', '光线', '华谊', '万达电影', '分众', '蓝色光标']),
    ('物流', ['物流', '顺丰', '圆通', '韵达', '申通', '中通快递']),
    ('交通运输', ['高速', '公路', '机场', '港口', '航运', '海运', '中远',
                  '上港', '宁波港', '南方航空', '中国国航']),
    ('纺织服装', ['纺织', '服装', '服饰', '海澜', '森马', '雅戈尔', '报喜']),
    ('商贸', ['商业', '商贸', '永辉', '王府井', '中国中免', '苏宁']),
    ('建材', ['建材', '水泥', '海螺', '华新', '东方雨虹', '北新建材', '南玻']),
    ('电气设备', ['电气', '正泰', '国电南瑞', '特变电工', '许继', '思源']),
]


def classify_sector(name: str) -> str:
    """根据股票名称关键词判断所属行业"""
    if not name:
        return '未知'
    for sector, keywords in SECTOR_KEYWORDS:
        for kw in keywords:
            if kw in name:
                return sector
    return '其他'


# ============================================================
#  BuyDecision  买入决策
# ============================================================

class BuyDecision:
    """买入决策 — 精度优先，每次最多新增 1 只, 确定买入价和仓位

    规则:
      - 最多同时持有 3 只，但单次信号默认只新增 Top1
      - 每只最多占总权益 1/3（费用包含在上限内）
      - 买入股数按100股整手并计入佣金、过户费
      - 买入价格 = 参考价 + 0.05%基准滑点
      - 目标卖出 = 扣除全部成本后净收益 +1%
      - 止损 = 买入价 -3%
    """

    @staticmethod
    def select(candidates: list, account: SimAccount,
               market_state: Optional[dict] = None) -> list:
        """从早盘候选(已排序)中选择置信度最高的一只买入

        Parameters
        ----------
        candidates : list[dict]
            候选股列表，已按评分排序。每项至少包含:
            code, name, price (或 buy_price), final_score (可选)。
        account : SimAccount
            模拟账户实例。
        market_state : dict, optional
            市场状态字典，含 mode_label。risk_off 时跳过买入。

        Returns
        -------
        list[dict]
            [{code, name, buy_price, shares, position_pct, reason}, ...]
        """
        if not candidates:
            return []

        # 1. 计算可用仓位
        max_positions = DEFAULT_SPEC.max_positions
        existing = account.position_count
        slots = min(1, max_positions - existing)
        if slots <= 0:
            logger.info(f'持仓已满 ({existing}/{max_positions})，跳过买入')
            return []

        # 2. 市场风控: 明确 risk_off 时空仓
        mode = 'neutral'
        if market_state and isinstance(market_state, dict):
            mode = market_state.get('mode_label', 'neutral')
        if mode == 'risk_off':
            logger.warning('市场为 risk_off 模式，按策略空仓')
            return []

        # 3. 评分门槛 + 行业分散；不足80分时保持空仓。
        candidates = [
            cand for cand in candidates
            if (
                bool(cand.get('v4_model_ranked'))
                or float(cand.get('final_score', cand.get('score', 0)) or 0) >= 80.0
            )
            and cand.get('v4_tradable', True) is not False
            and (
                cand.get('predicted_positive_probability') is None
                or float(cand['predicted_positive_probability']) >= 0.55
            )
            and (
                cand.get('predicted_large_loss_probability') is None
                or float(cand['predicted_large_loss_probability']) <= 0.15
            )
        ]
        if not candidates:
            logger.info('无评分达到80分的候选，按策略空仓')
            return []

        # 从候选列表中按评分排序, 但同行业最多1只
        selected = []
        used_sectors = set()
        for cand in candidates:
            if len(selected) >= slots:
                break
            name = cand.get('name', '')
            sector = classify_sector(name)
            if sector in used_sectors and sector != '其他' and sector != '未知':
                logger.info(f'  跳过 {cand.get("code","")} {name} (行业={sector}, 已有同行业)')
                continue
            selected.append(cand)
            if sector != '其他' and sector != '未知':
                used_sectors.add(sector)

        # 如果行业分散后不足 slots, 从剩余的补 (允许同行业)
        if len(selected) < slots:
            for cand in candidates:
                if len(selected) >= slots:
                    break
                if cand not in selected:
                    selected.append(cand)

        logger.info(f'行业分散后选择: {len(selected)} 只 (从 {len(candidates)} 候选)')

        # 4. 计算每只仓位和股数
        decisions = []
        per_position_pct = DEFAULT_SPEC.max_position_fraction
        position_budget = DEFAULT_SPEC.position_budget(account.total_equity)
        remaining_cash = account.available_capital
        costs = account.cost_model

        for cand in selected:
            code = cand.get('code', '')
            name = cand.get('name', '')
            price = float(cand.get('price', cand.get('buy_price', 0)))
            if price <= 0:
                logger.warning(f'无效价格: {code} price={price}')
                continue

            budget = min(position_budget, remaining_cash)
            shares = costs.max_affordable_shares(
                price, budget, apply_buy_slippage=True
            )

            if shares <= 0:
                logger.info(f'{code} {name}: 资金不足以买入1手 (需 {price*100:.2f})')
                continue

            buy_price = round(costs.buy_fill_price(price), 2)
            target_sell = round(
                costs.required_sell_reference(
                    price, shares, DEFAULT_SPEC.target_net_return
                ),
                2,
            )
            stop_loss = round(buy_price * 0.97, 2)       # -3%

            buy_cash = costs.buy_cash_required(buy_price, shares)
            if buy_cash['cash_out'] > budget + 1e-8:
                logger.info(f'{code} {name}: 含费用后超过单票上限')
                continue
            remaining_cash -= buy_cash['cash_out']

            decisions.append({
                'code': code,
                'name': name,
                'buy_price': buy_price,
                'reference_price': price,
                'shares': shares,
                'estimated_cash_out': round(buy_cash['cash_out'], 2),
                'target_sell': target_sell,
                'stop_loss': stop_loss,
                'position_pct': round(per_position_pct * 100, 1),
                'reason': f'评分={cand.get("final_score", "?")}, '
                          f'价格={price:.2f}, 仓位={per_position_pct*100:.0f}%',
                'strategy': cand.get('strategy', 'v4_production'),
            })

        return decisions

    @staticmethod
    def execute(decisions: list, account: SimAccount) -> int:
        """执行买入决策列表 — 对每个决策调用 account.open_position()

        Parameters
        ----------
        decisions : list[dict]
            BuyDecision.select() 返回的决策列表。
        account : SimAccount
            模拟账户实例。

        Returns
        -------
        int
            成功开仓笔数。
        """
        count = 0
        for d in decisions:
            try:
                account.open_position(
                    code=d['code'],
                    name=d['name'],
                    buy_price=d['buy_price'],
                    shares=d['shares'],
                    strategy=d.get('strategy', 'v4_production'),
                    target_sell=d.get('target_sell'),
                    stop_loss=d.get('stop_loss'),
                )
                count += 1
            except ValueError as e:
                logger.warning(f'开仓失败 {d["code"]}: {e}')
        return count
