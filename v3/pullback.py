"""
V3 回调选股引擎 — PullbackEngine

完整K线分析 + 多维评分的回调选股策略。
用于识别强势股短暂回调后的买入机会。

流程:
  1. 初筛: 今日跌幅2-5%, price>5, amount>30M
  2. K线分析: 近20日K线，计算MA5/MA10/MA20/量比/多周期涨幅
  3. 趋势判断: 近5日涨幅8-25% (强势股)
  4. 缩量确认: 今日量比 < 0.8
  5. 支撑检测: close > MA10
  6. 板块确认: 所属板块在Top10热门行业
  7. 全天走势: 非单边下跌
  8. 五维评分排序

使用方式:
  engine = PullbackEngine()
  candidates = engine.screen(quotes_df)
"""

import logging
import time
import numpy as np
import pandas as pd
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# 尝试导入 DataFetcher
try:
    from v3.data import DataFetcher
except ImportError:
    DataFetcher = None

# 尝试导入板块分类
try:
    from v3.sector_rank import classify as _classify_sector
except ImportError:
    _classify_sector = None

# ── 板块关键词映射 (降级方案) ──
_SECTOR_KEYWORDS = [
    ('银行', ['银行']), ('证券', ['证券', '券商']), ('保险', ['保险', '人寿', '人保']),
    ('白酒', ['茅台', '五粮液', '泸州', '汾酒', '洋河', '古井', '酒鬼']),
    ('医药', ['医药', '药业', '医疗', '生物', '药明', '恒瑞', '复星']),
    ('房地产', ['地产', '万科', '保利', '华侨城', '金地']),
    ('汽车', ['汽车', '比亚迪', '长城', '长安', '上汽', '广汽']),
    ('食品饮料', ['伊利', '蒙牛', '双汇', '海天']),
    ('电子', ['电子', '海康', '大华', '京东方', '立讯']),
    ('半导体', ['半导体', '芯片', '中芯', '华虹', '兆易']),
    ('新能源', ['宁德', '隆基', '通威', '阳光', '天合', '亿纬']),
    ('军工', ['军工', '航天', '航空', '中航']),
    ('钢铁', ['钢铁', '宝钢', '鞍钢', '首钢']),
    ('煤炭', ['煤炭', '神华', '陕煤', '兖矿']),
    ('电力', ['电力', '华能', '国电', '长江电力']),
    ('通信', ['移动', '联通', '电信', '中兴']),
    ('计算机', ['软件', '计算机', '用友', '金山']),
    ('家电', ['美的', '格力', '海尔']),
    ('建筑', ['建筑', '基建', '中铁', '铁建']),
    ('农业', ['牧原', '温氏', '新希望']),
    ('化工', ['化工', '化学', '万华']),
    ('有色', ['有色', '黄金', '稀土', '锂业']),
    ('机械', ['机械', '装备', '三一', '中联']),
    ('环保', ['环保', '环境', '碧水源']),
    ('传媒', ['传媒', '文化', '光线', '分众']),
]


def _classify_name(name: str) -> str:
    """根据股票名称关键词判断所属行业"""
    if not name:
        return '其他'
    if _classify_sector is not None:
        return _classify_sector(name)
    for sector, keywords in _SECTOR_KEYWORDS:
        for kw in keywords:
            if kw in str(name):
                return sector
    return '其他'


class PullbackEngine:
    """回调选股引擎 — 完整K线分析+多维评分

    用于识别强势股短暂回调后的买入机会。

    Examples
    --------
    >>> engine = PullbackEngine()
    >>> candidates = engine.screen(quotes_df)
    >>> for c in candidates:
    ...     print(f"{c['name']}: score={c['score']}, change={c['change_pct']}%")
    """

    # ── 初筛参数 ──────────────────────────────────────────
    MIN_PRICE = 5.0             # 最低股价
    MIN_AMOUNT = 3e7            # 最低成交额 (3000万)
    PULLBACK_MIN = 2.0          # 最小回调幅度 (%)
    PULLBACK_MAX = 5.0          # 最大回调幅度 (%)

    # ── K线筛选参数 ───────────────────────────────────────
    MIN_5D_RETURN = 3.0         # 5日最低涨幅 3% (原8%太严)
    MAX_5D_RETURN = 30.0        # 5日最高涨幅 30%
    MAX_10D_RETURN = 40.0       # 10日最高涨幅 40%
    MAX_VOLUME_RATIO = 1.0      # 量比上限 1.0 (原0.8太严)
    MAX_DIST_TO_MA10 = -5.0     # 允许跌破MA10 -5% (原-3%太严)
    KLINE_DAYS = 20             # 获取K线天数

    # ── 输出 ──────────────────────────────────────────────
    MAX_CANDIDATES = 10

    def __init__(self):
        self.candidates: List[Dict[str, Any]] = []
        self._sector_rankings: Dict[str, Any] = {}
        self._top_sectors: List[str] = []
        self._sector_order: List[str] = []   # 排名顺序

    # ══════════════════════════════════════════════════════════
    # 外部上下文注入
    # ══════════════════════════════════════════════════════════

    def set_sector_context(self, rankings: Dict[str, Any]) -> None:
        """注入板块排名数据，用于评分中的板块热度维度

        Parameters
        ----------
        rankings : dict
            SectorRanker.rankings 输出: {sector: {rank, score, avg_pct, ...}}
        """
        self._sector_rankings = rankings
        # 按排名排序
        sorted_sec = sorted(rankings.items(), key=lambda x: x[1].get('rank', 99))
        self._sector_order = [s for s, _ in sorted_sec]
        self._top_sectors = self._sector_order[:10]

    # ══════════════════════════════════════════════════════════
    # 主入口: screen
    # ══════════════════════════════════════════════════════════

    def screen(self, quotes_df: pd.DataFrame,
               kline_cache: Optional[Dict[str, pd.DataFrame]] = None) -> List[Dict[str, Any]]:
        """回调选股主流程

        Parameters
        ----------
        quotes_df : pd.DataFrame
            今日实时行情。必须包含: code, name, price, open, high, low, volume, amount,
            change_pct (或 pct_chg)。
        kline_cache : dict, optional
            预取的K线缓存 {code: pd.DataFrame}。未提供时自动获取。

        Returns
        -------
        list[dict]
            候选股列表，按评分降序:
            [{code, name, score, price, change_pct, buy_price, strategy:'回调', rank}, ...]
        """
        self.candidates = []

        if quotes_df is None or quotes_df.empty:
            logger.warning("行情数据为空, 无法选股")
            return []

        # ── Step 1: 初筛 ──────────────────────────────────
        df = quotes_df[quotes_df['price'] > 0].copy()

        # 排除科创板、北交所、ST
        df = df[~df['code'].str.startswith('688')].copy()
        df = df[~df['code'].str.startswith('8')].copy()
        if 'name' in df.columns:
            df = df[~df['name'].str.contains('ST|\\*ST|退', na=False)].copy()

        # 涨幅列标准化
        pct_col = 'change_pct' if 'change_pct' in df.columns else 'pct_chg'
        if pct_col not in df.columns:
            logger.warning("缺少涨跌幅列")
            return []

        # 回调幅度筛选 2%~5%
        df = df[df[pct_col].between(-self.PULLBACK_MAX, -self.PULLBACK_MIN)].copy()
        logger.info(f"回调初步筛选 (跌幅{self.PULLBACK_MIN}%~{self.PULLBACK_MAX}%): {len(df)} 只")

        if df.empty:
            return []

        # 价格和成交额过滤
        df = df[df['price'] >= self.MIN_PRICE].copy()
        if 'amount' in df.columns:
            df = df[df['amount'] >= self.MIN_AMOUNT].copy()
        logger.info(f"初筛后 (price>={self.MIN_PRICE}, amount>={self.MIN_AMOUNT/1e6:.0f}M): {len(df)} 只")

        if df.empty:
            return []

        # ── Step 2: 按回调质量预排序, 取最优20只做K线分析 ──
        # 预测评分: 回调幅度离3%越近越好, 成交额越大越好, 量比越低越好
        pct_val = df[pct_col].abs() if pct_col in df.columns else 4
        df['_pre_rank'] = (
            (5 - pct_val) * 3               # 回调越浅(接近-2%)越好
            + (df['amount'].fillna(0) / 5e7) # 成交额越大越好
        )
        if 'volume_ratio' in df.columns:
            df['_pre_rank'] += (1 - df['volume_ratio'].fillna(1)) * 2  # 缩量越多越好
        df = df.sort_values('_pre_rank', ascending=False).head(20)
        pmin = df[pct_col].min() if pct_col in df.columns else 0
        pmax = df[pct_col].max() if pct_col in df.columns else 0
        logger.info("回调预排序后取top 20: 跌幅范围 %.1f%%~%.1f%%" % (pmin, pmax))

        # ── Step 3: K线深度分析 ──
        analyzed_rows = []
        for _, row in df.iterrows():
            code = str(row.get('code', ''))

            # 获取K线
            kline = None
            if kline_cache and code in kline_cache:
                kline = kline_cache[code]
            else:
                kline = self._fetch_kline(code)

            if kline is None or len(kline) < 10:
                continue  # K线不足, 跳过

            # ── 计算各项指标 ──
            row_dict = row.to_dict()

            # K线指标
            indicators = self._calc_indicators(kline)
            row_dict.update(indicators)

            # ── Step 3: 趋势判断 ──
            near_5d = indicators.get('near_5d_return', 0)
            if near_5d < self.MIN_5D_RETURN or near_5d > self.MAX_5D_RETURN:
                continue

            # 近10日不能暴涨太多
            near_10d = indicators.get('near_10d_return', 0)
            if near_10d > self.MAX_10D_RETURN:
                continue

            # ── Step 4: 缩量确认 ──
            vol_ratio = indicators.get('volume_ratio', 1.0)
            if vol_ratio > self.MAX_VOLUME_RATIO:
                continue

            # ── Step 5: 支撑检测 (close > MA10) ──
            dist_ma10 = indicators.get('dist_to_ma10', 0)
            if dist_ma10 < self.MAX_DIST_TO_MA10:
                continue

            # ── Step 6: 板块确认 ──
            name = str(row_dict.get('name', ''))
            sector = _classify_name(name)
            row_dict['_sector'] = sector

            # 计算板块排名和加成
            sector_rank = self._get_sector_rank(sector)
            sector_bonus = self._get_sector_bonus(sector)
            row_dict['sector_rank'] = sector_rank
            row_dict['sector_bonus'] = sector_bonus

            # 只保留Top10热门行业
            if self._top_sectors and sector not in self._top_sectors:
                # 没有板块数据或不在Top10, 仍纳入但降分处理
                row_dict['sector_penalty'] = -5.0
            else:
                row_dict['sector_penalty'] = 0.0

            # ── Step 7: 全天走势 ──
            open_p = float(row_dict.get('open', 0))
            high_p = float(row_dict.get('high', 0))
            close_p = float(row_dict.get('price', 0))
            low_p = float(row_dict.get('low', 0))

            if open_p > 0 and high_p > 0 and close_p > 0:
                # 全天走势: (close-open)/open vs (high-close)/high
                body = (close_p - open_p) / open_p          # 实体涨跌
                upper_shadow = (high_p - max(open_p, close_p)) / high_p  # 上影线比例
                lower_shadow = (min(open_p, close_p) - low_p) / low_p if low_p > 0 else 0

                # 单边下跌检测: 实体下跌 + 上影线短 + 下影线短
                is_one_sided = (body < -0.01 and upper_shadow < 0.005 and lower_shadow < 0.01)
                if is_one_sided:
                    row_dict['intraday_penalty'] = -8.0
                else:
                    row_dict['intraday_penalty'] = 0.0

                # 下影线加分: 盘中下跌后拉起, 说明有支撑
                if lower_shadow > 0.01:
                    row_dict['lower_shadow_bonus'] = min(3.0, lower_shadow * 100)
                else:
                    row_dict['lower_shadow_bonus'] = 0.0
            else:
                row_dict['intraday_penalty'] = 0.0
                row_dict['lower_shadow_bonus'] = 0.0

            # ── Step 8: 评分 ──
            row_dict['pullback_score'] = self.score(row_dict, kline)

            analyzed_rows.append(row_dict)

        if not analyzed_rows:
            logger.info("K线深度筛选后无候选")
            return []

        # ── 排序输出 ──
        result_df = pd.DataFrame(analyzed_rows)
        result_df = result_df.sort_values('pullback_score', ascending=False)
        top = result_df.head(self.MAX_CANDIDATES)

        # 构建输出格式（与追高一致）
        output = []
        for rank, (_, row) in enumerate(top.iterrows(), 1):
            price_val = float(row.get('price', 0))
            change_val = float(row.get(pct_col, row.get('change_pct', 0)))
            output.append({
                'code': str(row.get('code', '')),
                'name': str(row.get('name', '')),
                'score': round(float(row.get('pullback_score', 0)), 1),
                'price': round(price_val, 2),
                'change_pct': round(change_val, 2),
                'buy_price': round(price_val * 1.002, 2),
                'strategy': '回调',
                'rank': rank,
                # 额外诊断信息
                '_near_5d': round(float(row.get('near_5d_return', 0)), 2),
                '_vol_ratio': round(float(row.get('volume_ratio', 1)), 3),
                '_dist_ma10': round(float(row.get('dist_to_ma10', 0)), 2),
                '_sector': row.get('_sector', '未知'),
            })

        self.candidates = output
        logger.info(f"回调策略最终候选: {len(output)} 只")
        return output

    # ══════════════════════════════════════════════════════════
    # K线指标计算
    # ══════════════════════════════════════════════════════════

    def _calc_indicators(self, kline: pd.DataFrame) -> Dict[str, float]:
        """基于K线计算全部技术指标

        Returns
        -------
        dict
            near_3d_return, near_5d_return, near_10d_return,
            ma5, ma10, ma20, dist_to_ma5, dist_to_ma10, dist_to_ma20,
            volume_ratio, consecutive_shrink,
            atr_5, atr_14, kline_volatility
        """
        indicators = {}

        closes = kline['close'].values
        today = closes[-1]

        # ── 多周期涨幅 ──
        indicators['near_3d_return'] = self._n_day_return(closes, 3)
        indicators['near_5d_return'] = self._n_day_return(closes, 5)
        indicators['near_10d_return'] = self._n_day_return(closes, 10)

        # ── 均线 ──
        ma5 = np.mean(closes[-5:]) if len(closes) >= 5 else today
        ma10 = np.mean(closes[-10:]) if len(closes) >= 10 else today
        ma20 = np.mean(closes[-20:]) if len(closes) >= 20 else today

        indicators['ma5'] = round(float(ma5), 2)
        indicators['ma10'] = round(float(ma10), 2)
        indicators['ma20'] = round(float(ma20), 2)

        # ── 距均线距离 (%) ──
        indicators['dist_to_ma5'] = round(float((today - ma5) / ma5 * 100), 2) if ma5 > 0 else 0
        indicators['dist_to_ma10'] = round(float((today - ma10) / ma10 * 100), 2) if ma10 > 0 else 0
        indicators['dist_to_ma20'] = round(float((today - ma20) / ma20 * 100), 2) if ma20 > 0 else 0

        # ── 量比 ──
        indicators['volume_ratio'] = self._calc_volume_ratio(kline)

        # ── 连续缩量天数 ──
        indicators['consecutive_shrink'] = self._count_consecutive_shrink(kline)

        # ── ATR (波动率) ──
        indicators['atr_5'] = self._calc_atr(kline, 5)
        indicators['atr_14'] = self._calc_atr(kline, 14)

        # ── K线整体波动 ──
        if len(closes) >= 10:
            returns = np.diff(closes[-10:]) / closes[-10:-1] * 100
            indicators['kline_volatility'] = round(float(np.std(returns)), 2)
        else:
            indicators['kline_volatility'] = 0.0

        return indicators

    @staticmethod
    def _n_day_return(closes: np.ndarray, n: int) -> float:
        """计算近N日累计涨幅 (%)"""
        if len(closes) < n + 1:
            return 0.0
        base = closes[-(n + 1)]
        if base <= 0:
            return 0.0
        return round(float((closes[-1] - base) / base * 100), 2)

    @staticmethod
    def _calc_volume_ratio(kline: pd.DataFrame) -> float:
        """计算量比: 今日量 / 5日均量"""
        if 'volume' not in kline.columns or len(kline) < 6:
            return 1.0
        vols = kline['volume'].values
        today_vol = vols[-1]
        # 排除今日，取前5日均量
        avg_5d = np.mean(vols[-6:-1])
        if avg_5d <= 0:
            return 1.0
        return round(float(today_vol / avg_5d), 3)

    @staticmethod
    def _count_consecutive_shrink(kline: pd.DataFrame) -> int:
        """统计连续缩量天数 (逐日量递减)"""
        if 'volume' not in kline.columns or len(kline) < 3:
            return 0
        vols = kline['volume'].values
        count = 0
        for i in range(len(vols) - 1, 0, -1):
            if vols[i] < vols[i - 1]:
                count += 1
            else:
                break
        return count

    @staticmethod
    def _calc_atr(kline: pd.DataFrame, n: int) -> float:
        """计算ATR (Average True Range)"""
        if len(kline) < n + 1:
            return 0.0
        highs = kline['high'].values
        lows = kline['low'].values
        closes = kline['close'].values

        tr_list = []
        for i in range(1, len(kline)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            tr_list.append(tr)

        if len(tr_list) >= n:
            return round(float(np.mean(tr_list[-n:])), 2)
        return round(float(np.mean(tr_list)), 2) if tr_list else 0.0

    # ══════════════════════════════════════════════════════════
    # 五维评分系统 (≥100行)
    # ══════════════════════════════════════════════════════════

    def score(self, row: Dict[str, Any], kline: pd.DataFrame) -> float:
        """五维评分 (0-100)

        维度与权重:
        1. 回调深度评分  30% — 温和回调(2-3%)最佳
        2. 缩量程度评分  25% — 量比越低越好，确认洗盘
        3. 距MA10评分    20% — 精准回调到支撑位
        4. 板块热度评分  15% — 所属行业热度
        5. 五日趋势评分  10% — 非暴涨暴跌，趋势稳健

        外加惩罚/奖励项

        Parameters
        ----------
        row : dict
            股票数据行（含所有指标）
        kline : pd.DataFrame
            K线DataFrame

        Returns
        -------
        float
            0-100 综合评分
        """
        score = 0.0

        # ──────────────────────────────────────────────────
        # 维度1: 回调深度评分 (30分)
        #   1a: 回调幅度合理性 (18分)
        #   1b: 回调位置/收盘位置 (12分)
        # ──────────────────────────────────────────────────

        change_pct = abs(float(row.get('change_pct', row.get('pct_chg', 0))))

        # 1a: 回调幅度评分 (18分)
        # 理想回调 2.0%-3.5%，太深 (>4.5%) 可能趋势已坏
        if change_pct <= 2.2:
            depth_score_a = 18.0              # 极浅回调，可能只是横盘
        elif change_pct <= 2.5:
            depth_score_a = 17.5              # 很浅回调
        elif change_pct <= 2.8:
            depth_score_a = 17.0
        elif change_pct <= 3.0:
            depth_score_a = 16.0              # 温和回调，最佳区间
        elif change_pct <= 3.2:
            depth_score_a = 15.0
        elif change_pct <= 3.5:
            depth_score_a = 13.5
        elif change_pct <= 3.8:
            depth_score_a = 11.0              # 偏深回调
        elif change_pct <= 4.0:
            depth_score_a = 9.0
        elif change_pct <= 4.3:
            depth_score_a = 7.0
        elif change_pct <= 4.5:
            depth_score_a = 5.0               # 深度回调
        elif change_pct <= 4.8:
            depth_score_a = 3.0
        elif change_pct <= 5.0:
            depth_score_a = 1.5               # 极深回调
        else:
            depth_score_a = 0.5               # 不应到这里 (已过滤)
        score += max(0, depth_score_a)

        # 1b: 收盘位置评分 (12分)
        # 收盘在低位 = 充分回调未反弹，高位 = 已反弹
        close_pos = float(row.get('close_position', 0.3))
        candle_body = float(row.get('candle_body_pct', -2.0))

        if close_pos <= 0.10:
            depth_score_b = 12.0              # 极度低位收盘，充分释放
        elif close_pos <= 0.15:
            depth_score_b = 11.0
        elif close_pos <= 0.20:
            depth_score_b = 10.0
        elif close_pos <= 0.25:
            depth_score_b = 9.0
        elif close_pos <= 0.30:
            depth_score_b = 8.0               # 低位收盘，理想
        elif close_pos <= 0.35:
            depth_score_b = 7.0
        elif close_pos <= 0.40:
            depth_score_b = 6.0
        elif close_pos <= 0.50:
            depth_score_b = 5.0               # 居中
        elif close_pos <= 0.60:
            depth_score_b = 3.5               # 偏高位
        elif close_pos <= 0.75:
            depth_score_b = 2.0               # 高位，已反弹较多
        else:
            depth_score_b = 1.0               # 极高（有上影线反弹）
        score += depth_score_b

        # ──────────────────────────────────────────────────
        # 维度2: 缩量程度评分 (25分)
        #   2a: 量比绝对值 (17分)
        #   2b: 连续缩量天数 (8分)
        # ──────────────────────────────────────────────────

        vol_ratio = float(row.get('volume_ratio', 1.0))

        # 2a: 量比评分 (17分)
        if vol_ratio <= 0.25:
            vol_score_a = 17.0                # 极度缩量
        elif vol_ratio <= 0.30:
            vol_score_a = 16.5
        elif vol_ratio <= 0.35:
            vol_score_a = 16.0
        elif vol_ratio <= 0.40:
            vol_score_a = 15.0                # 大幅缩量
        elif vol_ratio <= 0.45:
            vol_score_a = 14.0
        elif vol_ratio <= 0.50:
            vol_score_a = 13.0                # 半量，理想缩量
        elif vol_ratio <= 0.55:
            vol_score_a = 11.5
        elif vol_ratio <= 0.60:
            vol_score_a = 10.0                # 明显缩量
        elif vol_ratio <= 0.65:
            vol_score_a = 8.5
        elif vol_ratio <= 0.70:
            vol_score_a = 7.0                 # 适度缩量
        elif vol_ratio <= 0.75:
            vol_score_a = 5.0
        elif vol_ratio <= 0.80:
            vol_score_a = 3.0                 # 边缘缩量
        else:
            vol_score_a = 1.0                 # 接近正常量
        score += vol_score_a

        # 2b: 连续缩量天数 (8分)
        consecutive = int(row.get('consecutive_shrink', 0))
        if consecutive >= 5:
            vol_score_b = 8.0                 # 连续5天缩量
        elif consecutive >= 4:
            vol_score_b = 7.0
        elif consecutive >= 3:
            vol_score_b = 5.5                 # 连续3天缩量
        elif consecutive >= 2:
            vol_score_b = 3.5
        elif consecutive >= 1:
            vol_score_b = 1.5                 # 仅今日缩量
        else:
            vol_score_b = 0.0                 # 未缩量
        score += vol_score_b

        # ──────────────────────────────────────────────────
        # 维度3: 距MA10支撑评分 (20分)
        #   3a: 距MA10距离 (12分)
        #   3b: MA多头排列 (8分)
        # ──────────────────────────────────────────────────

        dist_ma10 = float(row.get('dist_to_ma10', 0))

        # 3a: 距MA10距离 (12分)
        # 理想: 紧密贴合MA10 (+0.2% ~ +1.5%)
        if 0.0 <= dist_ma10 <= 0.3:
            ma10_score_a = 12.0               # 精准回踩MA10
        elif 0.3 < dist_ma10 <= 0.6:
            ma10_score_a = 11.5
        elif 0.6 < dist_ma10 <= 1.0:
            ma10_score_a = 11.0               # 紧贴支撑
        elif 1.0 < dist_ma10 <= 1.5:
            ma10_score_a = 10.0
        elif 1.5 < dist_ma10 <= 2.0:
            ma10_score_a = 8.5
        elif 2.0 < dist_ma10 <= 2.5:
            ma10_score_a = 7.0                # 略高于支撑
        elif 2.5 < dist_ma10 <= 3.0:
            ma10_score_a = 5.5
        elif 3.0 < dist_ma10 <= 4.0:
            ma10_score_a = 3.5                # 远离支撑
        elif 4.0 < dist_ma10 <= 5.0:
            ma10_score_a = 2.0
        elif dist_ma10 > 5.0:
            ma10_score_a = 1.0                # 太远
        elif -0.3 <= dist_ma10 < 0:
            ma10_score_a = 10.0               # 轻微跌破（可接受）
        elif -0.8 <= dist_ma10 < -0.3:
            ma10_score_a = 8.0
        elif -1.5 <= dist_ma10 < -0.8:
            ma10_score_a = 5.0                # 跌破支撑
        elif -2.5 <= dist_ma10 < -1.5:
            ma10_score_a = 2.5                # 深度跌破
        else:
            ma10_score_a = 1.0
        score += ma10_score_a

        # 3b: MA多头排列 (8分)
        dist_ma5 = float(row.get('dist_to_ma5', 0))
        dist_ma20 = float(row.get('dist_to_ma20', 0))

        # MA5 > MA10 > MA20 表示完整的上升趋势
        if dist_ma5 > dist_ma10 > dist_ma20:
            ma10_score_b = 8.0                # 完美多头排列
        elif dist_ma5 > dist_ma10:
            ma10_score_b = 5.5                # 短期多头（MA5 > MA10）
        elif dist_ma10 > dist_ma20:
            ma10_score_b = 3.5                # 中期多头（MA10 > MA20）
        elif dist_ma5 > dist_ma20:
            ma10_score_b = 2.0                # 长期仍在上方
        else:
            # MA5 < MA20，短期均线跌破长期，趋势可能转弱
            ma10_score_b = 0.0
        score += ma10_score_b

        # ──────────────────────────────────────────────────
        # 维度4: 板块热度评分 (15分)
        #   4a: 板块绝对排名 (9分)
        #   4b: 板块涨跌加成 (6分)
        # ──────────────────────────────────────────────────

        sec_rank = int(row.get('sector_rank', 99))
        sec_bonus = float(row.get('sector_bonus', 0))
        total_sec = max(len(self._sector_order), 1)

        # 4a: 板块排名 (9分)
        if sec_rank <= 1:
            sector_score_a = 9.0               # 排名第1
        elif sec_rank <= 2:
            sector_score_a = 8.0
        elif sec_rank <= 3:
            sector_score_a = 7.0
        elif sec_rank <= 4:
            sector_score_a = 6.0
        elif sec_rank <= 5:
            sector_score_a = 5.0               # Top5
        elif sec_rank <= 6:
            sector_score_a = 4.0
        elif sec_rank <= 7:
            sector_score_a = 3.0
        elif sec_rank <= 8:
            sector_score_a = 2.5               # Top8
        elif sec_rank <= 9:
            sector_score_a = 2.0
        elif sec_rank <= 10:
            sector_score_a = 1.5               # Top10
        elif sec_rank <= 12:
            sector_score_a = 1.0
        elif sec_rank <= 15:
            sector_score_a = 0.5               # 中等
        else:
            sector_score_a = 0.0               # 冷门
        score += sector_score_a

        # 4b: 绝对加成 (6分)
        if sec_bonus >= 10:
            sector_score_b = 6.0
        elif sec_bonus >= 8:
            sector_score_b = 5.0
        elif sec_bonus >= 5:
            sector_score_b = 4.0
        elif sec_bonus >= 3:
            sector_score_b = 2.5
        elif sec_bonus >= 2:
            sector_score_b = 1.5
        elif sec_bonus > 0:
            sector_score_b = 0.8
        else:
            sector_score_b = 0.0
        score += sector_score_b

        # ──────────────────────────────────────────────────
        # 维度5: 五日趋势评分 (10分)
        #   5a: 5日涨幅合理性 (6分)
        #   5b: 趋势稳定性 (4分)
        # ──────────────────────────────────────────────────

        near_5d = float(row.get('near_5d_return', 0))
        near_3d = float(row.get('near_3d_return', 0))
        near_10d = float(row.get('near_10d_return', 0))

        # 5a: 5日涨幅评分 (6分)
        # 8-15% 是最理想的强势区间：有足够趋势但未过热
        if 10 <= near_5d <= 13:
            trend_score_a = 6.0                # 理想强势
        elif 13 < near_5d <= 15:
            trend_score_a = 5.5
        elif 8 <= near_5d < 10:
            trend_score_a = 5.0                # 足够强势
        elif 15 < near_5d <= 18:
            trend_score_a = 4.5
        elif 18 < near_5d <= 20:
            trend_score_a = 3.5                # 偏强
        elif 20 < near_5d <= 22:
            trend_score_a = 2.5
        elif 22 < near_5d <= 24:
            trend_score_a = 1.5                # 过热
        elif 24 < near_5d <= 25:
            trend_score_a = 0.8                # 极端过热
        else:
            trend_score_a = 3.0                # 偏弱但仍在范围
        score += trend_score_a

        # 5b: 趋势稳定性评分 (4分)
        # 计算各周期涨幅的标准差，越小越稳定
        returns = [abs(near_3d), abs(near_5d), abs(near_10d)]
        returns_std = float(np.std(returns))

        if returns_std < 1.5:
            trend_score_b = 4.0                # 极度稳定
        elif returns_std < 2.5:
            trend_score_b = 3.5
        elif returns_std < 4.0:
            trend_score_b = 3.0
        elif returns_std < 6.0:
            trend_score_b = 2.0                # 较稳定
        elif returns_std < 8.0:
            trend_score_b = 1.0
        elif returns_std < 10.0:
            trend_score_b = 0.5                # 波动大
        else:
            trend_score_b = 0.0                # 极度不稳定
        score += trend_score_b

        # ──────────────────────────────────────────────────
        # 惩罚与奖励项
        # ──────────────────────────────────────────────────

        # P1: 板块不在Top10的惩罚
        sector_penalty = float(row.get('sector_penalty', 0))
        score += sector_penalty

        # P2: 单边下跌惩罚 (全天无抵抗下跌)
        intraday_penalty = float(row.get('intraday_penalty', 0))
        score += intraday_penalty

        # P3: 下影线奖励 (盘中下跌后反弹，显示支撑)
        lower_shadow_bonus = float(row.get('lower_shadow_bonus', 0))
        score += lower_shadow_bonus

        # P4: 光脚阴线额外惩罚 (无下影线=无支撑)
        if close_pos <= 0.03 and candle_body < -2.0:
            score -= 4.0
        elif close_pos <= 0.05 and candle_body < -1.5:
            score -= 2.0

        # P5: 上影线过长惩罚 (盘中反弹失败)
        open_p = float(row.get('open', 0))
        high_p = float(row.get('high', 0))
        price_p = float(row.get('price', 0))
        if open_p > 0 and high_p > 0 and price_p > 0:
            upper_shadow_pct = (high_p - max(open_p, price_p)) / open_p * 100
            if upper_shadow_pct > 2.5:
                score -= 3.0                   # 长上影线
            elif upper_shadow_pct > 1.5:
                score -= 1.5

        # P6: ATR惩罚 — ATR过大说明波动剧烈，回调风险高
        atr_14 = float(row.get('atr_14', 0))
        if atr_14 > 0 and price_p > 0:
            atr_pct = atr_14 / price_p * 100
            if atr_pct > 5.0:
                score -= 3.0                   # 日均波幅 >5%
            elif atr_pct > 3.5:
                score -= 1.5

        # ── 确保范围 ──
        return round(max(0.0, min(100.0, score)), 1)

    # ══════════════════════════════════════════════════════════
    # 板块辅助
    # ══════════════════════════════════════════════════════════

    def _get_sector_rank(self, sector: str) -> int:
        """获取板块排名 (1-based, 99=未知)"""
        if not self._sector_rankings or sector not in self._sector_rankings:
            return 99
        return self._sector_rankings[sector].get('rank', 99)

    def _get_sector_bonus(self, sector: str) -> float:
        """获取板块热度加成 (-10 ~ +10)"""
        if not self._sector_rankings or sector not in self._sector_rankings:
            return 0.0

        rank = self._sector_rankings[sector].get('rank', 99)
        total = len(self._sector_rankings)

        if total == 0:
            return 0.0

        if rank <= 1:
            return 10.0
        elif rank <= 2:
            return 8.0
        elif rank <= 3:
            return 6.0
        elif rank <= 5:
            return 4.0
        elif rank <= 8:
            return 2.0
        elif rank >= total - 1:
            return -10.0
        elif rank >= total - 3:
            return -5.0
        elif rank >= total - 5:
            return -2.0
        else:
            return 0.0

    # ══════════════════════════════════════════════════════════
    # 数据获取
    # ══════════════════════════════════════════════════════════

    def _fetch_kline(self, code: str) -> Optional[pd.DataFrame]:
        """获取单只股票的K线数据"""
        if DataFetcher is None:
            logger.warning(f"DataFetcher 不可用, 无法获取 {code} K线")
            return None

        try:
            fetcher = DataFetcher()
            kline = fetcher.fetch_kline(code, days=self.KLINE_DAYS)
            if kline is not None and len(kline) >= 10:
                return kline
        except Exception as e:
            logger.warning(f"获取 {code} K线失败: {e}")

        return None

    def fetch_klines_batch(self, codes: List[str]) -> Dict[str, pd.DataFrame]:
        """批量获取K线数据

        Parameters
        ----------
        codes : list[str]
            股票代码列表

        Returns
        -------
        dict
            {code: pd.DataFrame}
        """
        cache = {}
        for i, code in enumerate(codes):
            kline = self._fetch_kline(str(code))
            if kline is not None:
                cache[str(code)] = kline
            # 控制请求频率
            if i > 0 and i % 10 == 0:
                time.sleep(0.2)
        return cache
