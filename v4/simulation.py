"""Standalone V4 selection, paper-account and market-data orchestration."""
import json
import os
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import pandas as pd

from market_universe import is_eligible_a_share, list_universe_codes
from strategy_spec import DEFAULT_SPEC, TradeCostModel

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
V4_DASHBOARD_STATE_PATH = ROOT / 'v4' / 'data' / 'dashboard_state.json'
V4_PAPER_ACCOUNT_PATH = ROOT / 'v4' / 'data' / 'paper_account.json'

try:
    from v4.sim_engine import SimAccount, BuyDecision
    from v4.data import DataFetcher
except ImportError:
    SimAccount = None
    BuyDecision = None
    DataFetcher = None
    logger.warning("兼容账户或行情模块导入失败, SimulationEngine 可能不可用")


class SimulationEngine:
    """Stable compatibility facade around V4 selection and legacy account I/O."""

    @staticmethod
    def health_check() -> bool:
        """每日自检: API可达 + 账户可读写"""
        try:
            from v4.data import DataFetcher
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
        self._sector_ranks = {}
        self._sentiment = {}
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
            self._account = SimAccount(str(V4_PAPER_ACCOUNT_PATH))
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
        if self._sentiment:
            return dict(self._sentiment)
        try:
            from v4.market import load_market_cache

            cached = load_market_cache().get('sentiment', {})
            return cached if isinstance(cached, dict) else {}
        except Exception:
            return {
                'limit_up': 0, 'limit_down': 0, 'up_ratio': 0.5,
                'avg_change': 0, 'score': 5, 'label': '不可用',
                'source': 'V4无可用全市场快照',
            }

    def _get_sector_ranks(self) -> dict:
        """读取V4生成的板块观测摘要。"""
        if self._sector_ranks:
            return dict(self._sector_ranks)
        try:
            from v4.market import load_market_cache

            cached = load_market_cache().get('sector_ranks', {})
            return cached if isinstance(cached, dict) else {}
        except Exception:
            return {
                'top': [], 'bottom': [], 'activity_top': [], 'time': '',
                'total_sectors': 0, 'classification_reliable': False,
                'classification': 'V4名称关键词代理行业',
            }

    def _get_market_state(self, quotes=None, *, expected_codes: int = 0) -> dict:
        """Delegate current-session market analytics exclusively to V4."""
        if quotes is None and self._last_market_state is not None:
            return dict(self._last_market_state)
        try:
            if quotes is None or quotes.empty:
                return self._empty_market_state()
            from v4.market import analyze_market

            analysis = analyze_market(quotes, expected_codes=expected_codes)
            state = analysis.get('market_state', {})
            self._sentiment = analysis.get('sentiment', {})
            self._sector_ranks = analysis.get('sector_ranks', {})
            self._last_market_state = dict(state)
            return state
        except Exception as exc:
            logger.warning('V4全市场状态计算失败: %s', exc)
            return self._empty_market_state()

    @staticmethod
    def _empty_market_state() -> dict:
        from v4.market import empty_market_state

        return empty_market_state()

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

    def screen_today(self, stage: str = 'auto') -> list:
        """Fetch the full market and let V4 exclusively generate Top5."""
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

            current = datetime.now()
            if stage == 'auto':
                stage = 'confirmation' if current.hour == 14 and current.minute >= 50 else 'morning'
            if stage == 'confirmation':
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

            from v4.candidate_journal import CandidateJournal
            journal = CandidateJournal()
            trade_date = current.strftime('%Y-%m-%d')
            allowed_codes = None
            if stage == 'confirmation':
                morning_rows = journal.morning_candidates(trade_date)
                allowed_codes = {item.get('code') for item in morning_rows if item.get('code')}
                if not journal.has_morning(trade_date):
                    logger.error('Missing current-session 09:25 mother pool; confirmation is empty')
                    self._candidates = []
                    self._last_screen_time = current.strftime('%H:%M:%S')
                    market_state['v4_selection'] = {
                        'status': 'blocked',
                        'stage': 'confirmation_1450',
                        'source': 'v4_morning_pool_link',
                        'reason': 'missing current-session 09:25 mother pool',
                    }
                    self._last_market_state = dict(market_state)
                    self._save_candidates([], stage='confirmation')
                    return self._candidates
                if not allowed_codes:
                    logger.info('Current-session 09:25 mother pool is valid but empty')
                    journal.save_confirmation(trade_date, [], market_state)
                    market_state['v4_selection'] = {
                        'status': 'empty',
                        'stage': 'confirmation_1450',
                        'source': 'v4_morning_pool_link',
                        'reason': '09:25 mother pool was empty',
                    }
                    self._last_market_state = dict(market_state)
                    self._candidates = []
                    self._last_screen_time = current.strftime('%H:%M:%S')
                    self._save_candidates([], stage='confirmation')
                    return self._candidates
                # The full-market request is intentionally batched and can take
                # tens of seconds. Refresh the tiny locked mother pool once more
                # so paper execution is judged on genuinely current 14:50 quotes
                # rather than on whichever full-market batch contained a code.
                refreshed_pool = df.batch_fetch_quotes(sorted(allowed_codes))
                if refreshed_pool is not None and not refreshed_pool.empty:
                    refreshed_pool = refreshed_pool.copy()
                    refreshed_pool['code'] = (
                        refreshed_pool['code'].astype(str).str.zfill(6)
                    )
                    q = q[~q['code'].isin(allowed_codes)].copy()
                    q = pd.concat([q, refreshed_pool], ignore_index=True)
            v4_runtime = V4Runtime()
            candidates = v4_runtime.evaluate_universe(
                q,
                market_state=market_state,
                allowed_codes=allowed_codes,
            )
            if stage == 'morning':
                journal.save_morning(trade_date, candidates, market_state)
            else:
                candidates = journal.link_confirmation_candidates(trade_date, candidates)
                candidates = v4_runtime.evaluate_candidates(candidates, market_state)
                journal.save_confirmation(trade_date, candidates, market_state)
                candidates = journal.load(trade_date).get('confirmation', {}).get('candidates', [])
            market_state['v4_selection'] = dict(v4_runtime.last_selection)
            self._last_market_state = dict(market_state)
            self._candidates = candidates
            self._last_screen_time = datetime.now().strftime('%H:%M:%S')
            self._save_candidates(candidates, stage=stage)
            logger.info(
                "V4候选生成完成: %d只 source=%s status=%s",
                len(candidates),
                v4_runtime.last_selection.get('source', 'unknown'),
                v4_runtime.last_selection.get('status', 'unknown'),
            )
            return candidates

        except Exception as e:
            logger.error(f"选股失败: {e}")
            self._candidates = []
            self._last_screen_time = datetime.now().strftime('%H:%M:%S')
            return self._candidates

    def _save_candidates(self, candidates: list, *, stage: str = 'auto') -> None:
        """Atomically persist only V4-origin candidates for the dashboard."""
        try:
            if any(c.get('is_mock') for c in candidates):
                logger.warning("跳过保存mock候选, 避免自动交易误买")
                return
            if any(c.get('v4_candidate_origin') != 'V4' for c in candidates):
                logger.error("拒绝保存非V4来源候选")
                return
            path = V4_DASHBOARD_STATE_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            market_state = self._last_market_state or {}
            if not market_state and path.exists():
                try:
                    existing = json.loads(path.read_text(encoding='utf-8'))
                    market_state = existing.get('market_state', {}) or {}
                except (OSError, ValueError, TypeError):
                    market_state = {}
            payload = {
                'candidate_engine': 'V4',
                'candidates': candidates,
                'market_state': market_state,
                'selection': market_state.get('v4_selection', {}),
                'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'date': datetime.now().strftime('%Y-%m-%d'),
                'stage': stage,
            }
            temporary = path.with_suffix('.tmp')
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
            temporary.replace(path)
        except Exception as e:
            logger.warning(f"保存候选失败: {e}")

    def load_candidates_from_file(self) -> list:
        """Load only candidates generated by the V4 engine."""
        try:
            if not V4_DASHBOARD_STATE_PATH.exists():
                return []
            data = json.loads(V4_DASHBOARD_STATE_PATH.read_text(encoding='utf-8'))
            if data.get('candidate_engine') != 'V4':
                return []
            candidates = data.get('candidates', [])
            if not isinstance(candidates, list):
                return []
            return [
                item for item in candidates
                if isinstance(item, dict) and item.get('v4_candidate_origin') == 'V4'
            ]
        except Exception:
            return []

    def load_market_state_from_file(self) -> dict:
        """Read the latest V4 market state without triggering a quote request."""
        try:
            if not V4_DASHBOARD_STATE_PATH.exists():
                return {}
            data = json.loads(V4_DASHBOARD_STATE_PATH.read_text(encoding='utf-8'))
            if data.get('candidate_engine') != 'V4':
                return {}
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
        paper_observation: bool = False,
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
            self.screen_today(stage='confirmation')

        if not self._candidates:
            return {
                'success': True,
                'message': '当日14:50无合格确认候选，模拟账户保持空仓',
                'bought': 0,
                'detail': [],
                'decision': 'empty',
            }

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
                    'v4_tradable': (
                        c.get('v4_paper_eligible', False)
                        if paper_observation else c.get('v4_tradable', False)
                    ),
                    'v4_model_ranked': c.get('v4_model_ranked', False),
                    'v4_decision': c.get('v4_decision', '观察/空仓'),
                    'v4_block_reasons': c.get('v4_block_reasons', []),
                    'predicted_positive_probability': c.get(
                        'predicted_positive_probability'
                    ),
                    'predicted_large_loss_probability': c.get(
                        'predicted_large_loss_probability'
                    ),
                    'strategy': 'v4_paper_observation' if paper_observation else 'v4_production',
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
                            capture_frame(
                                quotes,
                                'sell',
                                expected_codes=[code],
                                minimum_coverage=1.0,
                                require_order_book=True,
                                capture_role='paper_execution',
                                evidence_cohort='paper_only',
                            )
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
