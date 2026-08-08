"""
V2 数据获取模块 — DataFetcher

API 来源:
  - 新浪实时行情: hq.sinajs.cn
  - 新浪 K 线: money.finance.sina.com.cn
  - 东方财富: push2.eastmoney.com (市值、行业、PE/PB)
"""

import numpy as np
import pandas as pd
import urllib.request
import urllib.parse
import json
import re
import time
import logging
from datetime import datetime, date, timedelta
from typing import Optional

from .execution import CHINA_TZ

logger = logging.getLogger(__name__)

# ── HTTP 头 ──────────────────────────────────────────────
SINA_HEADERS = {
    'Referer': 'https://finance.sina.com.cn',
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
}
EM_HEADERS = {
    'Referer': 'https://quote.eastmoney.com/',
    'User-Agent': SINA_HEADERS['User-Agent'],
}


# ============================================================
#  HTTP 请求工具
# ============================================================

def _fetch_url(url: str, headers: dict = None, timeout: int = 15,
               encoding: str = 'utf-8') -> Optional[str]:
    """通用 HTTP GET 请求。"""
    try:
        req = urllib.request.Request(url, headers=headers or SINA_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            # 自动检测编码
            content_type = resp.headers.get('Content-Type', '')
            if 'gbk' in content_type or 'gb2312' in content_type:
                text = raw.decode('gbk', errors='replace')
            else:
                try:
                    text = raw.decode(encoding)
                except UnicodeDecodeError:
                    text = raw.decode('gbk', errors='replace')
            return text
    except Exception as e:
        logger.warning(f'请求失败 [{url[:60]}...]: {e}')
        return None


def _fetch_json(url: str, headers: dict = None, timeout: int = 15) -> Optional[dict]:
    """请求并解析 JSON。"""
    text = _fetch_url(url, headers=headers, timeout=timeout)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f'JSON 解析失败: {e}')
        return None


# ============================================================
#  DataFetcher 类
# ============================================================

class DataFetcher:
    """
    统一数据获取器。

    负责:
      - 实时行情 (Sina)
      - 历史 K 线 (Sina)
      - 市值/行业/PE/PB (EastMoney)
      - 大盘指数
      - 涨停板
      - 行业成分股
    """

    # ── 代码前缀映射 ─────────────────────────────────────
    SINA_PREFIX = {
        '6': 'sh',
        '9': 'sh',
        '0': 'sz',
        '2': 'sz',
        '3': 'sz',
    }
    EM_PREFIX = {
        '6': '1.',
        '9': '1.',
        '0': '0.',
        '2': '0.',
        '3': '0.',
    }

    def __init__(self, max_retries: int = 3, retry_delay: float = 0.5,
                 batch_size: int = 800):
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.batch_size = batch_size
        self._sector_cache: Optional[dict] = None  # 行业数据缓存

    # ── 实时行情 ──────────────────────────────────────────
    def batch_fetch_quotes(self, codes: list) -> Optional[pd.DataFrame]:
        """
        批量获取实时行情。

        Parameters
        ----------
        codes : list[str]
            股票代码列表(如 ['600000', '000001'])。

        Returns
        -------
        pd.DataFrame | None
            列: code, name, open, high, low, price, prev_close,
                volume, amount, change_pct, close_position, candle_body_pct
        """
        if not codes:
            return None

        batch_started_at = datetime.now(CHINA_TZ)
        all_dfs = []
        for i in range(0, len(codes), self.batch_size):
            batch = codes[i:i + self.batch_size]
            sina_codes = []
            for code in batch:
                code = str(code).strip().zfill(6)
                prefix = self.SINA_PREFIX.get(code[0], 'sh')
                sina_codes.append(f'{prefix}{code}')

            url = 'https://hq.sinajs.cn/list=' + ','.join(sina_codes)
            text = _fetch_url(url)
            if text:
                df = self._parse_sina_quotes(
                    text, received_at=datetime.now(CHINA_TZ)
                )
                if df is not None and not df.empty:
                    all_dfs.append(df)

            if i + self.batch_size < len(codes):
                time.sleep(0.3)

        if all_dfs:
            result = pd.concat(all_dfs, ignore_index=True)
            result.attrs["provider"] = "sina"
            result.attrs["batch_started_at"] = batch_started_at.isoformat()
            result.attrs["batch_completed_at"] = datetime.now(CHINA_TZ).isoformat()
            return result
        return None

    def _parse_sina_quotes(
        self, text: str, *, received_at: Optional[datetime] = None
    ) -> Optional[pd.DataFrame]:
        """解析新浪实时行情响应。"""
        received = received_at or datetime.now(CHINA_TZ)
        if received.tzinfo is None:
            raise ValueError("received_at must be timezone-aware")
        received = received.astimezone(CHINA_TZ)
        rows = []
        for line in text.strip().split('\n'):
            line = line.strip()
            if not line or not line.startswith('var hq_str_'):
                continue
            match = re.search(r'"(.+)"', line)
            if not match:
                continue
            fields = match.group(1).split(',')
            if len(fields) < 10:
                continue
            try:
                name = fields[0].strip()
                if not name or name == '0':
                    continue
                if name.startswith('ST') or '退' in name:
                    continue

                prev_close = float(fields[2]) if fields[2] else 0.0
                price = float(fields[3]) if fields[3] else 0.0
                open_price = float(fields[1]) if fields[1] else 0.0
                high = float(fields[4]) if fields[4] else 0.0
                low = float(fields[5]) if fields[5] else 0.0
                market_volume = float(fields[8]) if fields[8] else 0.0
                amount = float(fields[9]) if fields[9] else 0.0
                bid1_volume = float(fields[10]) if len(fields) > 11 and fields[10] else 0.0
                bid1 = float(fields[11]) if len(fields) > 11 and fields[11] else 0.0
                ask1_volume = float(fields[20]) if len(fields) > 21 and fields[20] else 0.0
                ask1 = float(fields[21]) if len(fields) > 21 and fields[21] else 0.0
                quote_time = None
                if len(fields) > 31 and fields[30] and fields[31]:
                    quote_time = f"{fields[30]}T{fields[31]}+08:00"

                if price <= 0 or prev_close <= 0:
                    continue

                code_match = re.search(r'var hq_str_(sh|sz)(\d+)="', line)
                code = code_match.group(2) if code_match else '000000'

                change_pct = round((price - prev_close) / prev_close * 100, 2)
                limit_ratio = 0.20 if code.startswith(("300", "688")) else 0.10
                limit_up_price = round(prev_close * (1 + limit_ratio) + 1e-8, 2)
                limit_down_price = round(prev_close * (1 - limit_ratio) + 1e-8, 2)

                rows.append({
                    'code': code,
                    'name': name,
                    'price': round(price, 2),
                    'change_pct': change_pct,
                    'change_amount': round(price - prev_close, 2),
                    'high': round(high, 2),
                    'low': round(low, 2),
                    'open': round(open_price, 2),
                    'prev_close': round(prev_close, 2),
                    # Sina already returns shares, not board lots.
                    'volume': int(market_volume),
                    'amount': round(amount, 2),       # 元
                    'bid1': round(bid1, 3),
                    'ask1': round(ask1, 3),
                    'bid1_volume': int(bid1_volume),
                    'ask1_volume': int(ask1_volume),
                    # Compatibility aliases used by the existing watchlist.
                    'bid1_vol': int(bid1_volume),
                    'ask1_vol': int(ask1_volume),
                    'quote_time': quote_time,
                    # Sina exposes one exchange quote timestamp, not a separate
                    # provider-generation timestamp. Preserve that fact rather
                    # than fabricating a second clock reading.
                    'exchange_time': quote_time,
                    'provider_time': quote_time,
                    'provider_time_source': 'same_as_exchange_time',
                    'received_at': received.isoformat(timespec='microseconds'),
                    'provider': 'sina',
                    'trade_date': fields[30] if len(fields) > 30 else '',
                    'halted': False,
                    'limit_up': bool(price >= limit_up_price and ask1 <= 0),
                    'limit_down': bool(price <= limit_down_price and bid1 <= 0),
                })
            except (ValueError, IndexError, TypeError):
                continue

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df['close_position'] = np.where(
            (df['high'] - df['low']) > 0,
            ((df['price'] - df['low']) / (df['high'] - df['low'])).round(2),
            0.5,
        )
        df['candle_body_pct'] = (
            (df['price'] - df['open']) / df['open'] * 100
        ).round(2)
        return df

    # ── 历史 K 线 ─────────────────────────────────────────
    def fetch_kline(self, code: str, days: int = 30,
                    scale: int = 60) -> Optional[pd.DataFrame]:
        """
        获取历史K线数据。默认 scale=60 表示60分钟线，不是日线。

        Parameters
        ----------
        code : str
            股票代码 (如 '600000')。
        days : int
            获取天数。
        scale : int
            周期分钟数，默认60分钟。

        Returns
        -------
        pd.DataFrame | None
            列: date, open, high, low, close, volume, amount, pct_chg
        """
        code = str(code).strip().zfill(6)

        # 新浪 K-line API
        prefix = 'sz' if code[0] in ('0', '2', '3') else 'sh'
        url = (
            f'https://money.finance.sina.com.cn/quotes_service/api/'
            f'json_v2.php/CN_MarketData.getKLineData?symbol={prefix}{code}'
            f'&scale={scale}&ma=no&datalen={days}'
        )

        text = _fetch_url(url)
        if not text:
            logger.warning(f'获取 K 线失败: {code}')
            return None

        try:
            records = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f'K 线 JSON 解析失败: {code}')
            return None

        if not records:
            return None

        rows = []
        for r in records:
            try:
                dt_str = r.get('day', '')
                open_ = float(r.get('open', 0))
                high = float(r.get('high', 0))
                low = float(r.get('low', 0))
                close = float(r.get('close', 0))
                volume = float(r.get('volume', 0))  # 新浪字段本身已是股
                amount = float(r.get('mone', 0))     # 金额(元)

                pct_chg = 0.0
                if len(rows) > 0:
                    prev_close = rows[-1]['close']
                    if prev_close > 0:
                        pct_chg = round((close - prev_close) / prev_close * 100, 2)

                rows.append({
                    'date': dt_str,
                    'open': round(open_, 2),
                    'high': round(high, 2),
                    'low': round(low, 2),
                    'close': round(close, 2),
                    'volume': int(volume),
                    'amount': round(amount, 2),
                    'pct_chg': pct_chg,
                })
            except (ValueError, KeyError, TypeError):
                continue

        if not rows:
            return None

        df = pd.DataFrame(rows)
        # 重算 pct_chg（以实际 close 为准）
        df['pct_chg'] = df['close'].pct_change() * 100
        df['pct_chg'] = df['pct_chg'].round(2).fillna(0.0)
        return df

    # ── 大盘指数 ─────────────────────────────────────────
    def get_market_summary(self) -> dict:
        """
        获取大盘指数涨跌幅。

        Returns
        -------
        dict
            {'sz_index': pct, 'cy_index': pct, 'market_mood': str}
        """
        url = 'https://hq.sinajs.cn/list=sh000001,sz399001,sz399006'
        text = _fetch_url(url)
        if not text:
            return {'status': 'unknown', 'detail': '无法获取指数数据'}

        summary = {}
        for line in text.strip().split('\n'):
            match = re.search(r'"(.+)"', line)
            if not match:
                continue
            fields = match.group(1).split(',')
            if len(fields) < 4:
                continue
            try:
                name = fields[0]
                prev_close = float(fields[2])
                price = float(fields[3])
                pct = round((price - prev_close) / prev_close * 100, 2)
                if '上证' in name:
                    summary['sh_index'] = pct
                elif '深证' in name:
                    summary['sz_index'] = pct
                elif '创业板' in name:
                    summary['cy_index'] = pct
            except (ValueError, IndexError):
                continue

        sh = summary.get('sh_index', 0) or 0
        if sh > 0.5:
            summary['market_mood'] = '强势'
        elif sh > -0.5:
            summary['market_mood'] = '震荡'
        elif sh > -1.5:
            summary['market_mood'] = '弱势'
        else:
            summary['market_mood'] = '危险'

        return summary

    @staticmethod
    def fetch_limit_up_stocks(self, limit: int = 50,
                              threshold: float = 9.5) -> list:
        """
        获取今日涨停股票列表。

        Parameters
        ----------
        limit : int
            扫描范围（涨幅排名前 N 只）。
        threshold : float
            涨停阈值 (%)。

        Returns
        -------
        list[dict]
            [{'code': ..., 'name': ..., 'change_pct': ...}, ...]
        """
        df = self._fetch_top_stocks(limit=limit)
        if df is None or df.empty:
            return []

        limit_ups = df[df['change_pct'] >= threshold]
        result = []
        for _, row in limit_ups.iterrows():
            result.append({
                'code': str(row['code']),
                'name': str(row['name']),
                'change_pct': float(row['change_pct']),
            })
        return result

    def _fetch_top_stocks(self, limit: int = 100) -> Optional[pd.DataFrame]:
        """快速获取涨幅靠前股票（覆盖上海+深圳主要代码区间）。"""
        query_ranges = [
            [f'sh{i:06d}' for i in range(600000, 605000)],
            [f'sh{i:06d}' for i in range(605000, 606000)],
            [f'sz{i:06d}' for i in range(1, 1000)],
            [f'sz{i:06d}' for i in range(2001, 3000)],
            [f'sz{i:06d}' for i in range(300001, 301000)],
        ]

        all_dfs = []
        for codes in query_ranges:
            url = 'https://hq.sinajs.cn/list=' + ','.join(codes)
            text = _fetch_url(url)
            if text:
                df = self._parse_sina_quotes(text)
                if df is not None and not df.empty:
                    all_dfs.append(df)
                time.sleep(0.2)

        if all_dfs:
            result = pd.concat(all_dfs, ignore_index=True)
            result = result.sort_values('change_pct', ascending=False)
            return result.head(limit)
        return None

    # ── 行业/市值/PE/PB (EastMoney) ──────────────────────
    def fetch_sector_data(self) -> dict:
        """
        获取行业成分股映射 (东方财富行业分类)。

        Returns
        -------
        dict
            {行业名: [code1, code2, ...]}
        """
        if self._sector_cache is not None:
            return self._sector_cache

        sector_map = {}
        # 东方财富行业板块列表
        url = (
            'https://push2.eastmoney.com/api/qt/clist/get'
            '?pn=1&pz=500&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:2'
            '&fields=f12,f14'
        )
        data = _fetch_json(url, headers=EM_HEADERS)
        if data and data.get('data') and data['data'].get('diff'):
            for item in data['data']['diff']:
                sector_code = item.get('f12', '')
                sector_name = item.get('f14', '')
                if sector_code and sector_name:
                    stocks = self._fetch_sector_stocks(sector_code)
                    if stocks:
                        sector_map[sector_name] = stocks

        self._sector_cache = sector_map if sector_map else {}
        return self._sector_cache

    def _fetch_sector_stocks(self, sector_code: str) -> list:
        """获取某个行业板块的所有成分股代码。"""
        url = (
            f'https://push2.eastmoney.com/api/qt/clist/get'
            f'?pn=1&pz=500&po=1&np=1&fltt=2&invt=2&fid=f3'
            f'&fs=m:90+t:2+f:!50+f:{sector_code}'
            f'&fields=f12,f14'
        )
        data = _fetch_json(url, headers=EM_HEADERS)
        if data and data.get('data') and data['data'].get('diff'):
            return [str(item['f12']) for item in data['data']['diff']
                    if item.get('f12')]
        return []

    def batch_fetch_fundamentals(self, codes: list) -> Optional[pd.DataFrame]:
        """
        批量获取市值、PE、PB、行业等基本面数据 (EastMoney)。

        Parameters
        ----------
        codes : list[str]
            股票代码列表。

        Returns
        -------
        pd.DataFrame | None
            列: code, name, sector, market_cap, pe_ttm, pb_mrq, log_market_cap
        """
        if not codes:
            return None

        rows = []
        # 分批请求(每批最多 500)
        batch_size = 500
        for i in range(0, len(codes), batch_size):
            batch = codes[i:i + batch_size]
            # 东方财富需要 1. / 0. 前缀
            em_codes = []
            for code in batch:
                code = str(code).strip().zfill(6)
                prefix = self.EM_PREFIX.get(code[0], '1.')
                em_codes.append(prefix + code)

            # 请求字段: f12=代码, f14=名称, f20=流通市值, f9=PE, f23=PB, f13=行业代码? 改用 f41/f43
            url = (
                'https://push2.eastmoney.com/api/qt/clist/get'
                '?pn=1&pz=500&po=1&np=1&fltt=2&invt=2&fid=f3'
                f'&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048'
                f'&fields=f12,f14,f20,f9,f23,f37'
            )
            # 实际上上面的 URL 用了 fs 过滤所有 A 股, 这里通过额外添加 codes 过滤
            # 改用自定义查询: 使用东方财富的 secids 参数
            secids = ','.join(em_codes)
            url2 = (
                'https://push2.eastmoney.com/api/qt/clist/get'
                '?pn=1&pz=500&po=1&np=1&fltt=2&invt=2&fid=f3'
                f'&fs=m:0+t:6&fields=f12,f14,f20,f9,f23,f37'
                f'&secids={secids}'
            )

            data = _fetch_json(url2, headers=EM_HEADERS)
            if data and data.get('data') and data['data'].get('diff'):
                for item in data['data']['diff']:
                    try:
                        raw_code = str(item.get('f12', ''))
                        # 去掉前缀
                        if '.' in raw_code:
                            raw_code = raw_code.split('.')[1]
                        name = item.get('f14', '') or ''
                        market_cap = float(item.get('f20', 0) or 0)  # 流通市值(元)
                        pe_ttm = float(item.get('f9', 0) or 0)
                        pb_mrq = float(item.get('f23', 0) or 0)
                        sector = str(item.get('f37', '') or '')

                        log_mc = np.nan
                        if market_cap > 0:
                            log_mc = np.log10(market_cap)

                        pe_log = np.nan
                        if pe_ttm > 0:
                            pe_log = -np.log10(pe_ttm)

                        pb_log = np.nan
                        if pb_mrq > 0:
                            pb_log = -np.log10(pb_mrq)

                        rows.append({
                            'code': raw_code,
                            'name': name,
                            'sector': sector,
                            'market_cap': market_cap,
                            'pe_ttm': pe_ttm,
                            'pb_mrq': pb_mrq,
                            'log_market_cap': round(log_mc, 4) if not np.isnan(log_mc) else np.nan,
                            'pe_ttm_log': round(pe_log, 4) if not np.isnan(pe_log) else np.nan,
                            'pb_mrq_log': round(pb_log, 4) if not np.isnan(pb_log) else np.nan,
                        })
                    except (ValueError, TypeError):
                        continue

            time.sleep(0.3)

        if rows:
            return pd.DataFrame(rows)
        return None

    # ── 行业强度 ─────────────────────────────────────────
    def compute_sector_strength(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算行业强度因子 (因子20):
          sector_strength = 个股涨跌 - 同行业均值

        Parameters
        ----------
        df : pd.DataFrame
            须含 sector, pct_chg 列。

        Returns
        -------
        pd.DataFrame
            追加 sector_strength 列。
        """
        result = df.copy()
        if 'sector' not in result.columns or 'pct_chg' not in result.columns:
            logger.warning('缺少 sector 或 pct_chg 列，跳过行业强度计算')
            result['sector_strength'] = np.nan
            return result

        sector_mean = result.groupby('sector')['pct_chg'].transform('mean')
        result['sector_strength'] = result['pct_chg'] - sector_mean
        return result

    # ── 清除缓存 ─────────────────────────────────────────
    def clear_cache(self):
        """清除行业数据缓存。"""
        self._sector_cache = None
        logger.info('行业缓存已清除')
