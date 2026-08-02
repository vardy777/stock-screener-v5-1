"""
V3 统一市场模块 — 合并 MarketState + SentimentEngine + SectorRanker
"""
import json, os, logging
from datetime import datetime
from typing import Optional
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# ── 行业关键词 ──
SECTOR_KEYWORDS = [
    ('银行', ['银行', '工商', '建设', '农业', '中行', '招行', '兴业', '浦发', '民生', '中信银行']),
    ('证券', ['证券', '券商', '中信建投', '华泰', '海通', '国泰', '广发']),
    ('保险', ['保险', '人寿', '人保', '太保', '新华']),
    ('白酒', ['茅台', '五粮液', '泸州', '汾酒', '洋河', '古井', '酒鬼']),
    ('医药', ['医药', '药业', '医疗', '生物', '药明', '恒瑞', '片仔癀']),
    ('房地产', ['地产', '万科', '保利', '华侨城', '金地']),
    ('汽车', ['汽车', '比亚迪', '长城', '长安', '上汽']),
    ('食品饮料', ['伊利', '双汇', '海天', '中炬']),
    ('电子', ['电子', '海康', '大华', '京东方', '立讯']),
    ('半导体', ['半导体', '芯片', '中芯', '华虹', '兆易']),
    ('新能源', ['宁德', '隆基', '通威', '阳光', '天合']),
    ('军工', ['军工', '航天', '航空', '中航', '中国船舶']),
    ('钢铁', ['钢铁', '宝钢', '鞍钢', '首钢']),
    ('煤炭', ['煤炭', '神华', '陕煤', '兖矿']),
    ('电力', ['电力', '华能', '国电', '大唐', '长江电力']),
    ('通信', ['移动', '联通', '电信', '中兴']),
    ('计算机', ['软件', '计算机', '用友', '金山', '科大讯飞']),
    ('家电', ['美的', '格力', '海尔', '海信']),
    ('建筑', ['建筑', '基建', '中铁', '铁建', '交建', '中建']),
    ('农业', ['牧原', '温氏', '新希望']),
    ('化工', ['化工', '化学', '万华']),
    ('有色', ['有色', '黄金', '铜', '铝业', '稀土']),
    ('机械', ['机械', '装备', '三一', '中联']),
    ('环保', ['环保', '环境', '碧水源']),
    ('传媒', ['传媒', '文化', '光线', '分众']),
]

def classify_sector(name: str) -> str:
    for sector, keywords in SECTOR_KEYWORDS:
        for kw in keywords:
            if kw in str(name):
                return sector
    return '其他'


class MarketContext:
    """统一市场上下文: 多周期评估 + 情绪 + 板块排名"""

    def __init__(self, cache_dir: str = None):
        from v3.config import DATA_DIR
        self.cache_dir = cache_dir or DATA_DIR
        self._rankings = {}
        self._top_sectors = []
        self._last_time = ''
        # 情绪
        self.limit_up = 0
        self.limit_down = 0
        self.up_ratio = 0.5
        self.avg_change = 0.0
        self.sentiment_score = 5
        self.sentiment_label = '中性'

    # ═══ 市场状态 ═══
    def assess(self, quotes_df: pd.DataFrame) -> dict:
        from v3.data import DataFetcher
        df = DataFetcher()
        result = {'sh_1d_pct': 0, 'sh_5d_pct': 0, 'sh_20d_pct': 0,
                  'advance_ratio': 0.5, 'composite': 0, 'mode_label': 'neutral'}

        summary = df.get_market_summary()
        sh_1d = summary.get('sh_index', 0) or 0
        result['sh_1d_pct'] = sh_1d

        # 5日: 用5只大盘股均值
        try:
            sample = [f'6{i:05d}' for i in range(0, 50)]
            closes_all = []
            for code in sample[:5]:
                kl = df.fetch_kline(code, days=25)
                if kl is not None and len(kl) >= 5:
                    closes_all.append(kl['close'].values[-1] / kl['close'].values[-5] - 1)
            if closes_all:
                result['sh_5d_pct'] = round(sum(closes_all) / len(closes_all) * 100, 2)
        except: pass

        # 宽度
        q = quotes_df[quotes_df['price'] > 0] if quotes_df is not None else pd.DataFrame()
        if not q.empty:
            pct_col = 'change_pct' if 'change_pct' in q.columns else 'pct_chg'
            up = int((q[pct_col] > 0).sum()) if pct_col in q.columns else 0
            result['advance_ratio'] = round(up / len(q), 3) if len(q) > 0 else 0.5

        # 综合评分
        score = 0
        score += 1 if sh_1d > 0.5 else (-1 if sh_1d < -0.5 else 0)
        s5 = result['sh_5d_pct']
        score += 1 if s5 > 2 else (-1 if s5 < -2 else 0)
        ar = result['advance_ratio']
        score += 1 if ar > 0.6 else (-1 if ar < 0.4 else 0)
        result['composite'] = score
        result['mode_label'] = 'risk_on' if score >= 1.5 else ('risk_off' if score <= -1.5 else 'neutral')
        return result

    # ═══ 情绪指标 ═══
    def analyze_sentiment(self, quotes_df: pd.DataFrame) -> dict:
        q = quotes_df[quotes_df['price'] > 0].copy()
        if len(q) < 100: return self._load_sentiment_cache()
        pct_col = 'change_pct' if 'change_pct' in q.columns else 'pct_chg'
        self.limit_up = int((q[pct_col] >= 9.5).sum())
        self.limit_down = int((q[pct_col] <= -9.5).sum())
        up = int((q[pct_col] > 0).sum())
        self.up_ratio = round(up / len(q), 3)
        self.avg_change = round(float(q[pct_col].mean()), 2)
        score = 5
        if self.limit_up > 80: score += 2
        elif self.limit_up > 50: score += 1
        elif self.limit_up < 10: score -= 2
        elif self.limit_up < 20: score -= 1
        if self.limit_down > 30: score -= 2
        elif self.limit_down > 15: score -= 1
        if self.up_ratio > 0.7: score += 1
        elif self.up_ratio < 0.3: score -= 1
        if self.avg_change > 1.0: score += 1
        elif self.avg_change < -1.0: score -= 1
        self.sentiment_score = max(0, min(10, score))
        labels = {0: '恐慌', 2: '偏弱', 4: '中性', 6: '偏强', 8: '亢奋'}
        self.sentiment_label = labels.get(self.sentiment_score - self.sentiment_score % 2, '中性')
        self._save_cache()
        return self.get_sentiment()

    def get_sentiment(self) -> dict:
        return {'limit_up': self.limit_up, 'limit_down': self.limit_down,
                'up_ratio': self.up_ratio, 'avg_change': self.avg_change,
                'score': self.sentiment_score, 'label': self.sentiment_label}

    # ═══ 板块排名 ═══
    def rank_sectors(self, quotes_df: pd.DataFrame) -> dict:
        q = quotes_df[quotes_df['price'] > 0].copy()
        pct_col = 'change_pct' if 'change_pct' in q.columns else 'pct_chg'
        amt_col = 'amount' if 'amount' in q.columns else None
        q['_sector'] = q['name'].apply(classify_sector)
        rankings = {}
        for sector, group in q.groupby('_sector'):
            n = len(group)
            if n < 3: continue
            avg = round(float(group[pct_col].mean()), 2)
            ur = round(float((group[pct_col] > 0).sum()) / n, 3)
            rankings[sector] = {'name': sector, 'count': n, 'avg_pct': avg, 'up_ratio': ur,
                                'total_amount': round(float(group[amt_col].sum()) / 1e8, 1) if amt_col else 0}
        sorted_sec = sorted(rankings.items(), key=lambda x: x[1]['avg_pct'], reverse=True)
        for i, (sec, info) in enumerate(sorted_sec):
            info['rank'] = i + 1
            info['score'] = round(min(info['avg_pct'] * 5, 50) + info['up_ratio'] * 30, 1)
        self._rankings = dict(sorted_sec)
        self._top_sectors = [s for s, _ in sorted_sec[:8]]
        self._last_time = datetime.now().strftime('%H:%M:%S')
        self._save_rank_cache()
        return self._rankings

    def get_sector_bonus(self, stock_name: str) -> float:
        sec = classify_sector(str(stock_name))
        if sec not in self._rankings: return 0
        rank = self._rankings[sec].get('rank', 99)
        total = len(self._rankings)
        if total == 0: return 0
        if rank <= 3: return 10
        elif rank <= 5: return 5
        elif rank <= 8: return 2
        elif rank >= total - 2: return -10
        elif rank >= total - 5: return -5
        return 0

    def get_sector_summary(self) -> dict:
        top = [{'sector': s, 'avg_pct': self._rankings[s].get('avg_pct', 0),
                'up_ratio': self._rankings[s].get('up_ratio', 0.5),
                'rank': self._rankings[s].get('rank', 99)}
               for s in self._top_sectors[:5]]
        return {'top': top, 'time': self._last_time, 'total_sectors': len(self._rankings)}

    # ═══ 缓存 ═══
    def _save_cache(self):
        try:
            p = os.path.join(self.cache_dir, 'market_context.json')
            with open(p, 'w', encoding='utf-8') as f:
                json.dump({'sentiment': self.get_sentiment(),
                           'rankings': self._rankings,
                           'top_sectors': self._top_sectors,
                           'time': self._last_time}, f, ensure_ascii=False, indent=2)
        except: pass

    def load_cache(self) -> dict:
        try:
            p = os.path.join(self.cache_dir, 'market_context.json')
            if os.path.exists(p):
                with open(p, 'r', encoding='utf-8') as f:
                    d = json.load(f)
                self._rankings = d.get('rankings', {})
                self._top_sectors = d.get('top_sectors', [])
                self._last_time = d.get('time', '')
                s = d.get('sentiment', {})
                self.limit_up = s.get('limit_up', 0)
                self.limit_down = s.get('limit_down', 0)
                self.up_ratio = s.get('up_ratio', 0.5)
                self.avg_change = s.get('avg_change', 0)
                self.sentiment_score = s.get('score', 5)
                self.sentiment_label = s.get('label', '中性')
                return d
        except: pass
        return {}

    def _save_rank_cache(self):
        try:
            p = os.path.join(self.cache_dir, 'sector_rankings.json')
            with open(p, 'w', encoding='utf-8') as f:
                json.dump({'rankings': self._rankings, 'top': self._top_sectors,
                           'time': self._last_time}, f, ensure_ascii=False, indent=2)
        except: pass

    def _load_sentiment_cache(self) -> dict:
        try:
            p = os.path.join(self.cache_dir, 'market_context.json')
            if os.path.exists(p):
                with open(p, 'r') as f:
                    s = json.load(f).get('sentiment', {})
                self.limit_up = s.get('limit_up', 0)
                self.sentiment_score = s.get('score', 5)
                self.sentiment_label = s.get('label', '中性')
                return s
        except: pass
        return {'score': 5, 'label': '中性', 'limit_up': 0, 'limit_down': 0,
                'up_ratio': 0.5, 'avg_change': 0}
