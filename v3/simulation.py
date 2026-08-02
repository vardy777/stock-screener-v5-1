"""
V3 SimulationEngine — 模拟交易引擎包装器

将 SimAccount, BuyDecision, DataFetcher, MarketState, Scorer, Strategy
统一为 SimulatinEngine 接口, 供 dashboard.py 使用。
"""
import json
import os
import math
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import pandas as pd

from decision_policy import market_is_risk_off, market_regime_score
from market_universe import is_eligible_a_share, list_universe_codes
from strategy_spec import DEFAULT_SPEC, TradeCostModel

logger = logging.getLogger(__name__)

try:
    from v3.sim_engine import SimAccount, BuyDecision
    from v3.market import MarketContext
    from v3.data import DataFetcher
    from v3.scorer import UltraShortScorer
    from v3.factors import UltraShortFactorComputer
except ImportError:
    SimAccount = None
    BuyDecision = None
    MarketContext = None
    DataFetcher = None
    UltraShortScorer = None
    UltraShortFactorComputer = None
    logger.warning("部分 V3 模块导入失败, SimulationEngine 可能不可用")


class SimulationEngine:
    """V3 核心引擎 — 选股/交易/状态"""

    @staticmethod
    def health_check() -> bool:
        """每日自检: API可达 + 账户可读写"""
        try:
            from v3.data import DataFetcher
            df = DataFetcher()
            q = df.batch_fetch_quotes(['600519'])
            if q is None or q.empty: return False
            e = SimulationEngine(); e.load_state()
            if e._account is None: return False
            return True
        except Exception:
            return False

    def __init__(self):
        self._account: Optional[SimAccount] = None
        self._candidates: list = []
        self._last_screen_time: Optional[str] = None
        self._sector_ranker = None   # P0: 板块排名器
        self._sentiment = None       # P1: 情绪指标
        self._last_market_state = None

    # ── 属性 ──────────────────────────────────────────────

    @property
    def positions(self) -> list:
        """当前持仓列表"""
        if self._account is None:
            return []
        return self._account.get_positions_summary()

    @property
    def daily_records(self) -> list:
        """每日结算记录"""
        if self._account is None:
            return []
        return list(self._account.data.get('daily_pnl', []))

    @property
    def account(self):
        """SimAccount 实例"""
        return self._account

    # ── 加载 / 保存 ──────────────────────────────────────

    def load_state(self):
        """加载持久化的模拟账户状态"""
        if SimAccount is None:
            logger.error("SimAccount 不可用")
            return
        try:
            self._account = SimAccount()
            # 加载候选数据
            self._candidates = self.load_candidates_from_file()
            logger.info(f"模拟账户已加载, 候选{len(self._candidates)}只")
        except Exception as e:
            logger.error(f"加载模拟账户失败: {e}")
            self._account = None

    def get_state(self) -> dict:
        """获取完整的看板状态字典

        Returns
        -------
        dict
            {
                'account': {资金概览},
                'positions': [{持仓明细}],
                'candidates': [{今日候选}],
                'trade_history': [{交易历史}],
                'daily_records': [{每日结算}],
                'market_state': {市场状态},
                'time': '...',
            }
        """
        if self._account is None:
            return self._empty_state()

        acct = self._account
        data = acct.data
        ic = float(data.get('initial_capital', 100000.0))
        eq = acct.total_equity
        cash = acct.available_capital
        cum_ret = acct.cumulative_return

        # 持仓
        positions_raw = acct.get_positions_summary()
        positions = []
        pos_market_value = 0.0
        for p in positions_raw:
            buy_price = float(p.get('buy_price', 0))
            shares = int(p.get('shares', 0))
            cur = buy_price  # 无当前价时按成本价
            pnl_pct = 0.0
            pnl_amount = 0.0
            try:
                cur = float(p.get('current_price', buy_price))
                if buy_price > 0:
                    pnl_pct = round((cur - buy_price) / buy_price * 100, 2)
                    pnl_amount = round((cur - buy_price) * shares, 2)
            except (ValueError, ZeroDivisionError):
                pass

            mv = round(cur * shares, 2)
            pos_market_value += mv
            default_target = acct.cost_model.required_sell_reference(
                buy_price / (1 + DEFAULT_SPEC.buy_slippage_rate),
                shares,
                DEFAULT_SPEC.target_net_return,
            ) if buy_price > 0 and shares > 0 else 0.0

            positions.append({
                'code': p.get('code', ''),
                'name': p.get('name', ''),
                'buy_date': p.get('buy_date', ''),
                'buy_price': buy_price,
                'shares': shares,
                'cost': round(buy_price * shares, 2),
                'current_price': cur,
                'market_value': mv,
                'pnl_pct': pnl_pct,
                'pnl_amount': pnl_amount,
                'target_sell': float(p.get('target_sell', round(default_target, 2))),
                'stop_loss': float(p.get('stop_loss', round(buy_price * 0.97, 2))),
            })

        # 交易历史
        history = acct.get_history_summary(50)
        trade_history = []
        for t in reversed(history):
            trade_history.append({
                'date': t.get('sell_date', '')[:10],
                'code': t.get('code', ''),
                'name': t.get('name', ''),
                'buy_date': t.get('buy_date', '')[:10],
                'buy_price': float(t.get('buy_price', 0)),
                'sell_price': float(t.get('sell_price', 0)),
                'shares': int(t.get('shares', 0)),
                'pnl_pct': float(t.get('pnl_pct', 0)),
                'pnl_amount': float(t.get('pnl_amount', 0)),
                'strategy': t.get('strategy', ''),
                'sell_reason': t.get('sell_reason', ''),
            })

        # 每日结算记录
        daily_records = list(data.get('daily_pnl', []))

        # 胜率统计
        total_trades = len(trade_history)
        wins = sum(1 for t in trade_history if t['pnl_pct'] > 0)
        win_rate = round(wins / total_trades * 100, 1) if total_trades > 0 else 0

        # 今日盈亏 (持仓浮动盈亏)
        today_pnl_pct = 0.0
        today_pnl_amount = 0.0
        if positions:
            pnl_pcts = [p['pnl_pct'] for p in positions if p['pnl_pct'] != 0]
            pnl_amts = [p['pnl_amount'] for p in positions]
            if pnl_pcts:
                today_pnl_pct = round(sum(pnl_pcts) / len(pnl_pcts), 2)
            today_pnl_amount = round(sum(pnl_amts), 2)

        # 最大回撤
        max_dd = 0.0
        max_peak = ic
        for r in daily_records:
            eq_val = float(r.get('end_capital', ic))
            if eq_val > max_peak:
                max_peak = eq_val
            dd = (max_peak - eq_val) / max_peak * 100 if max_peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        # 市场状态
        market_state = self._get_market_state()

        return {
            'account': {
                'initial_capital': ic,
                'current_capital': round(cash, 2),
                'total_equity': round(eq, 2),
                'position_market_value': round(pos_market_value, 2),
                'total_return_pct': round(cum_ret, 2),
                'total_return_amount': round(eq - ic, 2),
                'today_pnl_pct': today_pnl_pct,
                'today_pnl_amount': today_pnl_amount,
                'max_drawdown_pct': round(max_dd, 2),
                'total_trades': total_trades,
                'wins': wins,
                'losses': total_trades - wins,
                'win_rate': win_rate,
                'position_count': len(positions),
            },
            'positions': positions,
            'candidates': self._candidates if self._candidates else self.load_candidates_from_file(),
            'trade_history': trade_history,
            'daily_records': daily_records,
            'market_state': market_state,
            'sector_ranks': self._get_sector_ranks(),
            'sentiment': self._get_sentiment(),
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

    def _get_sentiment(self) -> dict:
        try:
            if self._sentiment:
                return self._sentiment.get_sentiment()
        except: pass
        try:
            # SentimentEngine → MarketContext
            s = MarketContext()
            cached = s.load_cache()
            return cached.get('sentiment', {}) or {'limit_up': 0, 'limit_down': 0, 'up_ratio': 0.5, 'avg_change': 0, 'score': 5, 'label': '中性'}
        except: pass
        return {'limit_up': 0, 'limit_down': 0, 'up_ratio': 0.5, 'avg_change': 0, 'score': 5, 'label': '中性'}

    def _get_sector_ranks(self) -> dict:
        """获取板块排名摘要"""
        try:
            if self._sector_ranker:
                return self._sector_ranker.get_sector_summary()
        except:
            pass
        # 尝试从缓存加载
        try:
            # SectorRanker → MarketContext
            r = MarketContext()
            r.load_cache()
            return r.get_sector_summary()
        except:
            pass
        return {'top': [], 'bottom': [], 'time': '', 'total_sectors': 0}

    def _get_market_state(self, quotes=None, *, expected_codes: int = 0) -> dict:
        """获取与研究口径一致的全市场状态；缺失时明确标记不可用。"""
        if quotes is None and self._last_market_state is not None:
            return dict(self._last_market_state)
        try:
            if quotes is None or quotes.empty:
                return {'sh_1d_pct': 0, 'sh_5d_pct': 0, 'sh_20d_pct': 0,
                        'advance_ratio': 0.5, 'market_mean_signal_return': 0.0,
                        'market_mean_gap': 0.0, 'regime_score': -1.0,
                        'quote_coverage': 0.0, 'data_valid': False,
                        'composite': 0, 'mode_label': 'unavailable'}
            q = quotes.copy()
            q['code'] = q['code'].astype(str).str.zfill(6)
            q = q[q['code'].map(is_eligible_a_share)]
            q = q[pd.to_numeric(q['price'], errors='coerce').gt(0)]
            if 'quote_time' not in q.columns:
                return self._get_market_state(None)
            from v4.execution import TradingClock
            q = q[q['quote_time'].map(TradingClock.quote_is_fresh)]
            q = q.drop_duplicates('code', keep='last')
            if q.empty:
                return self._get_market_state(None)
            pct = pd.to_numeric(
                q.get('change_pct', q.get('pct_chg')), errors='coerce'
            )
            metric_valid = pct.notna()
            q = q.loc[metric_valid].copy()
            pct = pct.loc[metric_valid]
            if q.empty:
                return self._get_market_state(None)
            if not {'prev_close', 'open'}.issubset(q.columns):
                return self._get_market_state(None)
            previous = pd.to_numeric(q.get('prev_close'), errors='coerce')
            opened = pd.to_numeric(q.get('open'), errors='coerce')
            breadth = float((pct > 0).mean())
            market_return = float(pct.mean() / 100.0)
            gap = (opened / previous - 1.0).replace([math.inf, -math.inf], float('nan'))
            market_gap = float(gap.dropna().mean()) if gap.notna().any() else 0.0
            coverage = min(1.0, len(q) / expected_codes) if expected_codes else 0.0
            regime = market_regime_score(breadth, market_return, market_gap)
            state = {
                'sh_1d_pct': market_return * 100.0,
                'sh_5d_pct': 0.0,
                'sh_20d_pct': 0.0,
                'composite': regime * 3.0,
                'advance_ratio': breadth,
                'market_mean_signal_return': market_return,
                'market_mean_gap': market_gap,
                'regime_score': regime,
                'quote_coverage': coverage,
                'data_valid': bool(expected_codes and coverage >= 0.95),
                'mode_label': (
                    'risk_off' if market_is_risk_off(breadth, market_return, market_gap)
                    else ('risk_on' if regime >= 0.35 else 'neutral')
                ),
            }
            self._last_market_state = dict(state)
            return state
        except Exception as exc:
            logger.warning('全市场状态计算失败: %s', exc)
            return {'sh_1d_pct': 0, 'sh_5d_pct': 0, 'sh_20d_pct': 0,
                    'advance_ratio': 0.5, 'market_mean_signal_return': 0.0,
                    'market_mean_gap': 0.0, 'regime_score': -1.0,
                    'quote_coverage': 0.0, 'data_valid': False,
                    'composite': 0, 'mode_label': 'unavailable'}

    def _empty_state(self) -> dict:
        """空状态模板"""
        return {
            'account': {
                'initial_capital': 100000,
                'current_capital': 100000,
                'total_equity': 100000,
                'position_market_value': 0,
                'total_return_pct': 0,
                'total_return_amount': 0,
                'today_pnl_pct': 0,
                'today_pnl_amount': 0,
                'max_drawdown_pct': 0,
                'total_trades': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0,
                'position_count': 0,
            },
            'positions': [],
            'candidates': [],
            'trade_history': [],
            'daily_records': [],
            'market_state': self._get_market_state(),
            'sector_ranks': self._get_sector_ranks(),
            'sentiment': self._get_sentiment(),
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

    # ── 选股 ──────────────────────────────────────────────

    def screen_today(self) -> list:
        """运行今日选股, 返回候选列表 (top 5)

        流程: 获取行情 → 筛选 → 因子计算 → 打分 → 策略过滤 → Top5
        """
        if DataFetcher is None:
            logger.error("DataFetcher 不可用, 按安全规则空仓")
            self._candidates = []
            self._last_screen_time = datetime.now().strftime('%H:%M:%S')
            return self._candidates

        try:
            df = DataFetcher()
            root = Path(__file__).resolve().parent.parent
            codes = list_universe_codes(root / 'phase1' / 'data' / 'daily')
            if not codes:
                logger.error('统一全市场股票池为空, 按安全规则空仓')
                self._candidates = []
                return self._candidates
            quotes = df.batch_fetch_quotes(codes)

            if quotes is None or quotes.empty:
                logger.error("无法获取行情数据, 按安全规则空仓")
                self._candidates = []
                self._last_screen_time = datetime.now().strftime('%H:%M:%S')
                return self._candidates

            try:
                from v4.snapshots import capture_frame
                capture_frame(
                    quotes,
                    'buy',
                    expected_codes=codes,
                    minimum_coverage=0.95,
                    capture_metadata={
                        'source': 'afternoon_confirmation_screen',
                        'requested_codes': len(codes),
                    },
                    require_order_book=True,
                    capture_role='decision_confirmation',
                )
            except Exception as e:
                logger.warning("V4真实14:50快照保存失败: %s", e)

            q = quotes[quotes['price'] > 0].copy()
            q['code'] = q['code'].astype(str).str.zfill(6)
            q = q[q['code'].map(is_eligible_a_share)].copy()
            logger.info(f"获取行情: {len(q)} 只")
            market_state = self._get_market_state(q, expected_codes=len(codes))
            from v4.runtime import V4Runtime
            from v4.execution import TradingClock
            v4_runtime = V4Runtime()
            if (
                v4_runtime.production_enabled
                and TradingClock.action_status('buy').allowed
            ):
                model_candidates = v4_runtime.evaluate_universe(
                    q,
                    fallback_candidates=[],
                    market_state=market_state,
                )
                self._candidates = model_candidates
                self._last_screen_time = datetime.now().strftime('%H:%M:%S')
                self._save_candidates(model_candidates)
                logger.info("V4生产模型完成全市场排序: %d只", len(model_candidates))
                return model_candidates

            # 市场情绪分析 (P1)
            try:
                # SentimentEngine → MarketContext
                se = MarketContext()
                se.analyze_sentiment(q)
                self._sentiment = se
                logger.info(
                    "市场情绪: %s (评分%s/10, 涨停%s, 跌停%s)",
                    se.sentiment_label, se.sentiment_score,
                    se.limit_up, se.limit_down,
                )
            except Exception as e:
                logger.warning(f"情绪分析失败: {e}")

            # 排除科创板 (688xxx), ST股票, 北交所(8xxxxx)
            q = q[~q['code'].str.startswith('688')].copy()
            # ── 混合策略: 追高 + 回调 → 统一排名 ──
            all_candidates = []

            # === 追高池: 涨幅2~7% ===
            chase_q = q.copy()
            chase_q = chase_q[~chase_q['name'].str.contains('ST|\\*ST', na=False)].copy()

            # 追高最低涨幅 4% (复盘发现2%涨幅的票次日溢价不足)
            pct_col = 'change_pct' if 'change_pct' in chase_q.columns else 'pct_chg'
            chase_q = chase_q[chase_q[pct_col].between(4.0, 7.0)].copy()
            chase_q = chase_q[chase_q['price'] >= 5].copy()
            if 'amount' in chase_q.columns:
                chase_q = chase_q[chase_q['amount'] >= 5e7].copy()

            if not chase_q.empty:
                chase_q.rename(columns={'change_pct': 'pct_chg'}, inplace=True)
                if UltraShortFactorComputer is not None:
                    chase_q = UltraShortFactorComputer().compute(chase_q)
                if UltraShortScorer is not None:
                    chase_q = UltraShortScorer().score(chase_q)
                # Apply sector/fund bonuses
                self._apply_bonuses(chase_q, quotes)
                # 板块确认: 只保留Top8热门行业
                if self._sector_ranker and self._sector_ranker._top_sectors:
                    top8 = set(self._sector_ranker._top_sectors[:8])
                    from v3.market import classify_sector
                    chase_q['_sec'] = chase_q['name'].apply(lambda n: classify_sector(str(n)))
                    chase_q = chase_q[chase_q['_sec'].isin(top8)].copy()
                for i, s in enumerate(chase_q.head(5).to_dict('records')):
                    # 尾盘区分: 优先全天稳步涨 (close > open 且 close - open > high - close)
                    close_price = float(s.get('price', 0))
                    open_price = float(s.get('open', 0))
                    high_price = float(s.get('high', 0))
                    # 全天稳步涨加分; 尾盘暴拉(close接近high但开盘弱)降分
                    intraday_bonus = 0
                    if open_price > 0 and high_price > 0:
                        if close_price > open_price and (close_price - open_price) > (high_price - close_price):
                            intraday_bonus = -5  # 尾盘暴拉, 降分
                    score = s.get('final_score', 70) + intraday_bonus
                    all_candidates.append({
                        'code': s.get('code',''), 'name': s.get('name',''),
                        'score': round(score, 1),
                        'price': close_price,
                        'change_pct': round(float(s.get('pct_chg',0)), 2),
                        'buy_price': round(
                            TradeCostModel(DEFAULT_SPEC).buy_fill_price(close_price), 2
                        ),
                        'strategy': '追高',
                        'quote_time': s.get('quote_time'),
                    })

            # === 回调池: PullbackEngine 完整K线分析+多维评分 ===
            pullback_candidates = []
            try:
                from v3.pullback import PullbackEngine
                pb_engine = PullbackEngine()
                # 注入板块排名数据
                if self._sector_ranker:
                    pb_engine.set_sector_context(self._sector_ranker._rankings)
                pullback_candidates = pb_engine.screen(quotes)
                logger.info(f"PullbackEngine 返回 {len(pullback_candidates)} 只候选")
            except Exception as e:
                logger.warning(f"PullbackEngine 执行失败: {e}")
                import traceback
                logger.warning(traceback.format_exc())

            for c in pullback_candidates:
                c.setdefault('rank', 0)
                all_candidates.append(c)

            # === 合并排名: 追高和回调混合 ===
            if not all_candidates:
                logger.warning("追高+回调均无候选；仍交由V4生产模型评估全市场")
                top5 = []
            else:
                # 旧策略仅作为研究锁定期的可视候选；生产模型独立评估全市场。
                all_candidates.sort(key=lambda x: x['score'], reverse=True)
                top5 = all_candidates[:5]
            for i, c in enumerate(top5):
                c['rank'] = i + 1

            try:
                top5 = v4_runtime.evaluate_universe(
                    q,
                    fallback_candidates=top5,
                    market_state=market_state,
                )
            except Exception as e:
                logger.exception("V4候选评估失败，按安全规则全部不可交易: %s", e)
                for candidate in top5:
                    candidate['v4_tradable'] = False
                    candidate['v4_decision'] = '观察/空仓'
                    candidate['v4_block_reasons'] = ['V4评估不可用']

            self._candidates = top5
            self._last_screen_time = datetime.now().strftime('%H:%M:%S')

            chase_count = sum(1 for c in top5 if c.get('strategy') == '追高')
            pullback_count = sum(1 for c in top5 if c.get('strategy') == '回调')
            logger.info(f"今日候选: {len(top5)} 只 (追高{chase_count}/回调{pullback_count})")

            # 保存到缓存文件
            self._save_candidates(top5)
            return top5

        except Exception as e:
            logger.error(f"选股失败: {e}")
            self._candidates = []
            self._last_screen_time = datetime.now().strftime('%H:%M:%S')
            return self._candidates

    def _apply_bonuses(self, df, all_quotes):
        try:
            # SectorRanker → MarketContext
            ranker = MarketContext()
            ranker.rank_sectors(all_quotes[all_quotes['price'] > 0])
            self._sector_ranker = ranker
            if 'final_score' in df.columns:
                bonuses = [ranker.get_sector_bonus(str(r.get('name',''))) for _, r in df.iterrows()]
                df['sector_bonus'] = bonuses
                df['final_score'] = df['final_score'] + df['sector_bonus']
        except Exception as e:
            logger.warning(f"板块加成失败: {e}")

    def _save_candidates(self, candidates: list) -> None:
        """持久化候选列表到 dashboard_data.json (跳过mock数据)"""
        try:
            # 不保存mock数据, 避免自动交易误买
            if any(c.get('is_mock') for c in candidates):
                logger.warning("跳过保存mock候选, 避免自动交易误买")
                return
            from v3.config import DATA_DIR
            path = os.path.join(DATA_DIR, 'dashboard_data.json')
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({
                    'candidates': candidates,
                    'market_state': self._last_market_state or {},
                    'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'date': datetime.now().strftime('%Y-%m-%d'),
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存候选失败: {e}")

    def load_candidates_from_file(self) -> list:
        """从 dashboard_data.json 加载持久化的候选列表"""
        try:
            from v3.config import DATA_DIR
            path = os.path.join(DATA_DIR, 'dashboard_data.json')
            if not os.path.exists(path):
                return []
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('candidates', [])
        except Exception:
            return []

    def load_market_state_from_file(self) -> dict:
        """读取最近一次主动选股留下的市场状态，不触发任何行情请求。"""
        try:
            from v3.config import DATA_DIR
            path = os.path.join(DATA_DIR, 'dashboard_data.json')
            if not os.path.exists(path):
                return {}
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            state = data.get('market_state', {})
            return state if isinstance(state, dict) else {}
        except Exception:
            return {}

    def _mock_candidates(self) -> list:
        """模拟候选数据 — 仅用于看板占位, 自动交易跳过"""
        return [
            {'code': '600184', 'name': '光电股份', 'score': 87.3, 'strategy': '追高',
             'price': 28.22, 'change_pct': 3.45, 'buy_price': 28.28, 'rank': 1, 'is_mock': True},
            {'code': '600133', 'name': '东湖高新', 'score': 82.1, 'strategy': '追高',
             'price': 8.40, 'change_pct': 2.80, 'buy_price': 8.42, 'rank': 2, 'is_mock': True},
            {'code': '000006', 'name': '深振业Ａ', 'score': 78.5, 'strategy': '追高',
             'price': 8.21, 'change_pct': 2.15, 'buy_price': 8.23, 'rank': 3, 'is_mock': True},
            {'code': '300458', 'name': '全志科技', 'score': 74.2, 'strategy': '回调',
             'price': 35.16, 'change_pct': -3.12, 'buy_price': 35.22, 'rank': 4, 'is_mock': True},
            {'code': '002415', 'name': '海康威视', 'score': 71.8, 'strategy': '回调',
             'price': 35.00, 'change_pct': -2.45, 'buy_price': 35.07, 'rank': 5, 'is_mock': True},
        ]

    # ── 买入 ──────────────────────────────────────────────

    def execute_buy(
        self,
        selected_codes: list = None,
        *,
        force: bool = False,
        refresh_candidates: bool = True,
    ) -> dict:
        """执行买入: 从候选列表选 Top N 开仓

        Parameters
        ----------
        selected_codes : list, optional
            指定要买入的股票代码列表。为 None 时自动选 Top N。

        Returns
        -------
        dict
            {'success': bool, 'message': str, 'bought': int, 'detail': [...]}
        """
        if self._account is None:
            self.load_state()

        try:
            from v4.execution import TradingClock
            TradingClock.require('buy', force=force)
        except Exception as e:
            return {'success': False, 'message': f'V4拒绝买入: {e}', 'bought': 0, 'detail': []}

        if self._account is None:
            return {'success': False, 'message': '模拟账户未初始化', 'bought': 0, 'detail': []}

        # 允许窗口内始终重新计算候选，避免使用页面或前一日缓存下单。
        if refresh_candidates or not self._candidates:
            self.screen_today()

        if not self._candidates:
            return {'success': False, 'message': '无候选股票', 'bought': 0, 'detail': []}

        if any(c.get('is_mock') for c in self._candidates):
            logger.error('检测到模拟候选，拒绝执行买入')
            return {
                'success': False,
                'message': '检测到模拟候选，已按安全规则拒绝买入',
                'bought': 0,
                'detail': [],
            }

        if BuyDecision is None:
            return {'success': False, 'message': 'BuyDecision 不可用', 'bought': 0, 'detail': []}

        try:
            market = self._get_market_state()

            # 将候选转为 BuyDecision 格式
            buy_candidates = []
            for c in self._candidates:
                # 如果指定了代码列表, 只保留选中的
                if selected_codes is not None and c['code'] not in selected_codes:
                    continue
                buy_candidates.append({
                    'code': c['code'],
                    'name': c['name'],
                    # 始终传参考现价；BuyDecision统一施加一次买入滑点。
                    'price': c['price'],
                    'final_score': c['score'],
                    'quote_time': c.get('quote_time'),
                    'v4_tradable': c.get('v4_tradable', False),
                    'v4_model_ranked': c.get('v4_model_ranked', False),
                    'v4_decision': c.get('v4_decision', '观察/空仓'),
                    'v4_block_reasons': c.get('v4_block_reasons', []),
                    'predicted_positive_probability': c.get(
                        'predicted_positive_probability'
                    ),
                    'predicted_large_loss_probability': c.get(
                        'predicted_large_loss_probability'
                    ),
                })

            decisions = BuyDecision.select(buy_candidates, self._account, market)

            if not decisions:
                return {'success': True, 'message': '无符合条件的买入 (仓位已满或风险模式)',
                        'bought': 0, 'detail': []}

            # 执行买入
            count = BuyDecision.execute(decisions, self._account)
            self._account._save()

            return {
                'success': True,
                'message': f'成功买入 {count} 只',
                'bought': count,
                'detail': decisions,
            }

        except Exception as e:
            logger.error(f"执行买入失败: {e}")
            return {'success': False, 'message': f'买入失败: {str(e)}', 'bought': 0, 'detail': []}

    # ── 卖出 ──────────────────────────────────────────────

    def execute_sell(self, *, force: bool = False) -> dict:
        """执行卖出: 按当前持仓全部平仓

        09:30进入连续竞价后获取当前可交易价格，并计入卖出滑点与费用。

        Returns
        -------
        dict
            {'success': bool, 'message': str, 'sold': int, 'detail': [...]}
        """
        if self._account is None:
            self.load_state()

        try:
            from v4.execution import TradingClock
            TradingClock.require('sell', force=force)
        except Exception as e:
            return {'success': False, 'message': f'V4拒绝卖出: {e}', 'sold': 0, 'detail': []}

        if self._account is None:
            return {'success': False, 'message': '模拟账户未初始化', 'sold': 0, 'detail': []}

        positions = self._account.get_positions_summary()
        if not positions:
            return {'success': True, 'message': '当前无持仓', 'sold': 0, 'detail': []}

        try:
            df = DataFetcher()
            costs = TradeCostModel(DEFAULT_SPEC)
            detail = []

            for p in positions:
                code = p['code']
                sell_reference = None

                try:
                    quotes = df.batch_fetch_quotes([code])
                    if quotes is not None and not quotes.empty:
                        try:
                            from v4.snapshots import capture_frame
                            capture_frame(quotes, 'sell')
                        except Exception as e:
                            logger.warning("V4真实09:30快照保存失败: %s", e)
                        row = quotes.iloc[0]
                        from v4.execution import TradingClock
                        if not TradingClock.quote_is_fresh(row.get('quote_time')):
                            raise ValueError('行情时间戳缺失或已过期')
                        # 09:30后连续竞价: 当前价优先；open只作最后代理。
                        for col in ['price', 'trade', 'open']:
                            if col in row and float(row[col]) > 0:
                                sell_reference = float(row[col])
                                break
                except Exception as e:
                    logger.warning(f"获取 {code} 行情失败: {e}")

                # 获取失败时保留持仓，不能用成本价伪造成交。
                if sell_reference is None:
                    detail.append({
                        'code': code,
                        'name': p.get('name', ''),
                        'success': False,
                        'message': '无可用09:30行情，持仓未平仓',
                    })
                    continue

                # 平仓
                sell_price = round(costs.sell_fill_price(sell_reference), 2)
                closed = self._account.close_position(
                    code, sell_price, sell_reason='09:30连续竞价'
                )
                buy_price = float(p['buy_price'])

                detail.append({
                    'code': code,
                    'name': p.get('name', ''),
                    'success': True,
                    'buy_price': buy_price,
                    'sell_reference': sell_reference,
                    'sell_price': sell_price,
                    'pnl_pct': closed.get('pnl_pct', 0.0),
                    'pnl_amount': closed.get('pnl_amount', 0.0),
                    'total_fees': closed.get('total_fees', 0.0),
                    'target_1pct': closed.get('target_1pct', False),
                })

            # 每日结算
            today_str = date.today().strftime('%Y-%m-%d')
            self._account.daily_settle(today_str)

            return {
                'success': True,
                'message': f'成功卖出 {sum(1 for item in detail if item.get("success"))} 只',
                'sold': sum(1 for item in detail if item.get('success')),
                'detail': detail,
            }

        except Exception as e:
            logger.error(f"执行卖出失败: {e}")
            return {'success': False, 'message': f'卖出失败: {str(e)}', 'sold': 0, 'detail': []}

    # ── 重置 ──────────────────────────────────────────────

    def reset(self, initial_capital: float = 100000.0):
        """重置模拟账户"""
        if self._account is None:
            self.load_state()
        if self._account is not None:
            self._account.reset(initial_capital)
            self._candidates = []
            self._last_screen_time = None
            logger.info(f"模拟账户已重置, 初始本金 ¥{initial_capital:,.2f}")
# P0P1 v2
