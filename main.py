#!/usr/bin/env python
"""
选股系统 - 历史工具入口（V1/V2）与 V4 运维辅助

用法:
    python main.py                      # 显示操作清单
    python main.py morning              # V1 早盘选股池
    python main.py afternoon            # V1 尾盘买入确认
    python main.py review               # V1 交易复盘
    python main.py buy <代码> <价格>     # V1 记录买入
    python main.py sell <代码> <价格>    # V1 记录卖出
    python main.py backtest             # V1 回测
    python main.py v2-scan              # V2 21因子扫描
    python main.py v2-snapshot          # V2 全市场快照
    python main.py v2-settle            # V2 结算昨日
    python main.py v2-dashboard         # V2 启动看板
    python main.py v2-cron-list         # V2 查看所有cron任务
    python main.py v2-ic                # V2 计算因子IC
数据源: 新浪财经 API（实时行情）| V4: 14:50→次日09:30 隔夜决策与执行门禁
"""

import sys
import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("urllib3").setLevel(logging.WARNING)


def banner():
    # Task Scheduler and older Windows terminals can still expose a GBK-only
    # stdout.  Keep the legacy entrypoint alive even when decorative Unicode
    # characters are not representable by that console.
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    print()
    print("  ╔══════════════════════════════════════╗")
    # Keep the legacy CLI usable from Windows Task Scheduler/GBK consoles.
    print("  ║      A股隔夜交易研究系统 V4          ║")
    print("  ║  14:50买入 · 次日09:30卖出 · 强门禁  ║")
    print("  ╚══════════════════════════════════════╝")
    print()


# ============================================================
# V1 (legacy) commands
# ============================================================

def cmd_morning():
    """早盘选股池"""
    from morning_screener import morning_screen
    from reporter import generate_morning_report
    banner()
    candidates, sectors, market = morning_screen()
    generate_morning_report(candidates, sectors, market)
    if candidates is not None and len(candidates) > 0:
        _save_codes(candidates)
    print("\n  ✅ V1 早盘完成。14:30 再运行: python main.py afternoon")


def cmd_afternoon():
    """尾盘买入确认"""
    from afternoon_screener import afternoon_confirm
    from reporter import generate_afternoon_report
    banner()
    codes_df = _load_codes()
    final = afternoon_confirm(codes_df)
    generate_afternoon_report(final, None)
    if final is not None and len(final) > 0:
        print("\n  ✅ V1 发现买入信号，跟踪以上股票到 14:55")
    else:
        print("\n  ✅ V1 尾盘完成，今日无操作")


def cmd_review():
    """交易复盘"""
    from trade_journal import review_period, show_pending_trades
    banner()
    review_period(30)
    show_pending_trades()


def cmd_buy(args):
    """记录买入"""
    from trade_journal import record_buy
    from data_fetcher import batch_fetch_quotes
    if len(args) < 2:
        print("  ❌ 用法: python main.py buy <代码> <价格> [理由]")
        return
    code = args[0]
    price = float(args[1])
    reason = " ".join(args[2:]) if len(args) > 2 else ""
    name = code
    df = batch_fetch_quotes([code])
    if df is not None and len(df) > 0:
        name = str(df.iloc[0].get("name", code))
    trade_id = record_buy(code, name, price, reason)
    if trade_id:
        print(f"  ✅ 买入已记录 (ID: {trade_id})")


def cmd_sell(args):
    """记录卖出"""
    from trade_journal import record_sell, init_journal
    if len(args) < 2:
        print("  ❌ 用法: python main.py sell <代码> <价格> [理由]")
        return
    code = args[0]
    price = float(args[1])
    reason = " ".join(args[2:]) if len(args) > 2 else ""
    df = init_journal()
    df["code"] = df["code"].astype(str).str.strip()
    mask = (df["code"] == str(code).strip()) & ((df["sell_price"] == 0) | df["sell_price"].isna())
    if mask.sum() > 0:
        buy_price = float(df[mask].iloc[-1]["buy_price"])
        profit = round((price - buy_price) / buy_price * 100, 2)
        print(f"  📊 盈亏: {profit:+.2f}%")
    record_sell(code, price, reason)


def cmd_backtest():
    """运行V1回测"""
    banner()
    print("  🔬 运行V1策略回测...\n")
    from backtest import run_backtest
    engine = run_backtest(market_filter=True)
    print("\n  ✅ V1 回测完成")


# ============================================================
# V2 commands
# ============================================================

def cmd_v2_scan():
    """V2 21因子扫描 + 策略选股 (多周期市场状态)"""
    banner()
    print("  🔬 V2: 21因子扫描 + 策略选股 (多周期市场状态)...\n")
    from v2.data import DataFetcher
    from v2.factors import FactorComputer
    from v2.normalizer import CrossSectionNormalizer
    from v2.scorer import ICWeightedScorer
    from v2.strategies import (
        BreakthroughStrategy, MomentumStrategy, OversoldStrategy,
        MarketAdaptiveAllocator
    )
    from datetime import datetime

    # 1. 获取多周期市场状态
    df = DataFetcher()
    market_state = df.get_market_state()
    print(f"  市场状态 (多周期):")
    print(f"    综合评分: {market_state['composite']:.1f} → {market_state['mode_label']}")
    print(f"    上证 1d: {market_state['sh_1d_pct']:+.2f}% | "
          f"5d: {market_state['sh_5d_pct']:+.2f}% | "
          f"20d: {market_state['sh_20d_pct']:+.2f}%")
    print(f"    上涨家数: {market_state['advance_ratio']*100:.0f}%")

    # 2. 获取实时行情
    sample = df.get_market_summary()
    quotes = df.batch_fetch_quotes(["sh000001", "sz000001", "600000", "000002"])
    print(f"  行情数据: {len(quotes) if quotes is not None else 0} 只")

    # 3. 21因子 + 行业中性化 + IC加权 (完整流程)
    print("  📐 加载 ICWeightedScorer...")
    scorer = ICWeightedScorer()
    print(f"     {sum(1 for v in scorer.weights.values() if v>0)}/{len(scorer.weights)} 因子活跃")

    # 4. 策略过滤 + 多周期市场自适应分配
    allocator = MarketAdaptiveAllocator()
    mode = allocator.get_market_mode(market_state)
    quotas = allocator.get_quotas(mode)
    print(f"    市场模式: {mode} | 配额: {quotas}")

    # 5. 构建策略字典
    strategies = {
        "breakthrough": BreakthroughStrategy(),
        "momentum": MomentumStrategy(),
        "oversold": OversoldStrategy(),
    }
    print(f"    策略: {list(strategies.keys())} (均就绪)")

    print(f"\n  {'='*55}")
    print(f"  📊 V2 系统诊断 ({datetime.now().strftime('%H:%M')})")
    print(f"  {'='*55}")
    print(f"  市场: {market_state['mode_label']} (综合评分 {market_state['composite']:.1f})")
    print(f"  上证: 1d={market_state['sh_1d_pct']:+.2f}%  "
          f"5d={market_state['sh_5d_pct']:+.2f}%  "
          f"20d={market_state['sh_20d_pct']:+.2f}%")
    print(f"  宽度: 上涨 {market_state['advance_ratio']*100:.0f}%  |  "
          f"策略配额: {quotas}")
    print(f"  IC权重: {sum(1 for v in scorer.weights.values() if v>0)} 因子活跃")
    print(f"  {'='*55}")
    print(f"  💡 提示: 完整21因子选股需在交易时段运行")
    print(f"  运行 cron 查看: python main.py v2-cron-list")


def cmd_v2_snapshot():
    """V2 全市场快照"""
    banner()
    print("  📸 V2: 全市场快照...\n")
    from v2.scripts.save_daily_snapshot import main as snap_main
    snap_main()


def cmd_v2_settle():
    """V2 结算昨日交易"""
    banner()
    print("  💰 V2: 结算昨日交易...\n")
    from v2.scripts.push_settlement import main as settle_main
    settle_main()


def cmd_v2_dashboard():
    """V2 启动看板"""
    banner()
    print("  📊 V2: 启动实时看板...\n")
    print(f"  访问: http://localhost:8899")
    from v2.dashboard import run_dashboard
    run_dashboard(port=8899)


def cmd_v2_cron_list():
    """查看本机Windows定时任务。"""
    banner()
    print("  ⏰ 查看A股系统Windows定时任务...\n")
    _print_windows_tasks()


def _print_windows_tasks():
    """List local AStock tasks without any agent or external scheduler."""
    import subprocess
    try:
        result = subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                "Get-ScheduledTask -TaskName 'AStock-*' | Sort-Object TaskName | "
                "ForEach-Object { $i=Get-ScheduledTaskInfo -TaskName $_.TaskName; "
                "'{0,-38} {1,-10} {2}' -f $_.TaskName,$_.State,$i.NextRunTime }",
            ],
            capture_output=True, text=True, timeout=10
        )
        print(result.stdout or "  (无输出)")
        if result.stderr:
            print(f"  (stderr): {result.stderr}")
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        print(f"  ❌ 无法读取Windows定时任务: {exc}")

def cmd_v2_ic():
    """V2 计算/查看因子IC"""
    banner()
    from v2.scorer import ICWeightedScorer
    scorer = ICWeightedScorer()
    print(f"  当前IC权重 ({len(scorer.ic_dict)} 因子, {sum(1 for v in scorer.weights.values() if v>0)} 活跃):\n")
    if scorer.weights:
        for factor, w in sorted(scorer.weights.items(), key=lambda x: -x[1]):
            ic = scorer.ic_dict.get(factor, 0)
            bar = "█" * int(w * 40)
            print(f"  {factor:25s}  IC={ic:+.4f}  weight={w:.4f}  {bar}")
    else:
        print("  (IC数据未加载, 使用默认值)")
        for factor, ic in sorted(scorer.ic_dict.items(), key=lambda x: -abs(x[1])):
            print(f"  {factor:25s}  IC={ic:+.4f}")


# ============================================================
# V4 兼容模拟工具命令（生产执行由 P3/P4 管理）
# ============================================================

def cmd_sim_status():
    """显示模拟账户状态"""
    banner()
    from v4.sim_engine import SimAccount
    acct = SimAccount()
    print(f"  💼 模拟账户状态\n")
    print(f"  初始本金: ¥{acct.data['initial_capital']:>10,.2f}")
    print(f"  当前权益: ¥{acct.total_equity:>10,.2f}")
    print(f"  可用资金: ¥{acct.available_capital:>10,.2f}")
    print(f"  累计收益: {acct.cumulative_return:>+9.2f}%")
    print(f"  持仓数量: {acct.position_count} 只")
    print(f"  交易笔数: {len(acct.data['history'])} 笔")
    if acct.data['history']:
        wins = sum(1 for t in acct.data['history'] if t.get('pnl_pct', 0) > 0)
        print(f"  胜    率: {wins/len(acct.data['history'])*100:.1f}%")


def cmd_sim_buy(date_str=None):
    """模拟买入: 保留命令名，内部统一走V4安全链路。"""
    banner()
    from v4.simulation import SimulationEngine

    engine = SimulationEngine()
    engine.load_state()
    result = engine.execute_buy()
    print(f"  {result.get('message', 'V4买入流程完成')}")
    for item in result.get('detail', []):
        print(
            f"  {item.get('code','')} {item.get('name','')} "
            f"¥{item.get('buy_price',0):.2f} × {item.get('shares',0)}股"
        )


def cmd_sim_sell():
    """模拟卖出: 保留命令名，内部统一走V4行情和时间控制。"""
    banner()
    from v4.simulation import SimulationEngine

    engine = SimulationEngine()
    engine.load_state()
    result = engine.execute_sell()
    print(f"  {result.get('message', 'V4卖出流程完成')}")
    for item in result.get('detail', []):
        if item.get('success'):
            print(
                f"  {item.get('code','')} {item.get('name','')} "
                f"{item.get('pnl_pct',0):+.2f}%"
            )
        else:
            print(f"  {item.get('code','')}: {item.get('message','未成交')}")

def cmd_sim_reset():
    """重置模拟账户"""
    from v4.sim_engine import SimAccount
    acct = SimAccount()
    acct.reset()
    print("  ✅ 模拟账户已重置为初始状态 (¥100,000)")


def cmd_sim_plan(*, engine=None, runtime=None, output_path=None):
    """生成今日V4观察与交易计划，保留原命令入口。"""
    banner()
    import json
    from datetime import date
    from pathlib import Path

    from v4.config import DATA_DIR
    from v4.sim_engine import BuyDecision
    from v4.simulation import SimulationEngine
    from v4.runtime import V4Runtime

    engine = engine or SimulationEngine()
    engine.load_state()
    candidates = engine.screen_today()
    market = engine._get_market_state()
    runtime = runtime or V4Runtime()
    state = runtime.system_state(market)
    print(f"  V4状态: {state['readiness']['headline']}")
    print(f"  买入窗口: {state['clock']['buy']['reason']}")
    for candidate in candidates:
        reasons = '、'.join(candidate.get('v4_block_reasons', [])) or '通过'
        print(
            f"  #{candidate.get('rank','?')} {candidate.get('code','')} "
            f"{candidate.get('name','')} | {candidate.get('v4_decision','观察')} | {reasons}"
        )

    account = engine.account
    positions = engine.positions
    decision_candidates = [
        {
            'code': candidate.get('code', ''),
            'name': candidate.get('name', ''),
            'price': candidate.get('price', 0),
            'final_score': candidate.get(
                'final_score', candidate.get('score', 0)
            ),
            'quote_time': candidate.get('quote_time'),
            'v4_tradable': candidate.get('v4_tradable', False),
            'v4_model_ranked': candidate.get('v4_model_ranked', False),
            'v4_decision': candidate.get('v4_decision', '观察/空仓'),
            'v4_block_reasons': candidate.get('v4_block_reasons', []),
            'predicted_positive_probability': candidate.get(
                'predicted_positive_probability'
            ),
            'predicted_large_loss_probability': candidate.get(
                'predicted_large_loss_probability'
            ),
        }
        for candidate in candidates
    ]
    decisions = (
        BuyDecision.select(decision_candidates, account, market)
        if account is not None
        else []
    )

    if positions:
        print(f"  🟢 当前持仓")
        for p in positions:
            print(f"    {p['code']} {p['name']} 成本¥{p['buy_price']:.2f} × {p['shares']}股")
            print(f"    目标: ¥{p['target_sell']:.2f}  止损: ¥{p['stop_loss']:.2f}")
    
    # 保存到dashboard_data供看板读取
    plan_data = {
        'date': date.today().isoformat(),
        'system_version': state.get('system_version', '4.0.0-research'),
        'pipeline_id': state.get('pipeline_id', 'overnight-1450-0930'),
        'readiness': state.get('readiness', {}),
        'market': market,
        'account': {
            'capital': account.available_capital if account is not None else 0,
            'initial_capital': (
                account.data.get('initial_capital', 100_000)
                if account is not None else 100_000
            ),
            'equity': account.total_equity if account is not None else 0,
            'cumulative_return': (
                account.cumulative_return if account is not None else 0
            ),
            'position_count': account.position_count if account is not None else 0,
        },
        'buy_plan': decisions,
        'candidates': candidates,
        'positions': positions,
    }
    destination = Path(output_path) if output_path else Path(DATA_DIR) / 'trade_plan.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(plan_data, handle, indent=2, ensure_ascii=False, default=str)
    temporary.replace(destination)
    print(f"\n  ✅ 计划已保存 → {destination}")
    return plan_data


# ============================================================
# Helpers
# ============================================================

def _save_codes(candidates):
    import json
    from config import DATA_DIR
    from datetime import date
    today = date.today().strftime("%Y-%m-%d")
    path = os.path.join(DATA_DIR, f"candidates_{today}.json")
    with open(path, "w") as f:
        json.dump(candidates["code"].tolist(), f)


def _load_codes():
    import json
    from config import DATA_DIR
    from datetime import date
    import pandas as pd
    today = date.today().strftime("%Y-%m-%d")
    path = os.path.join(DATA_DIR, f"candidates_{today}.json")
    if os.path.exists(path):
        with open(path) as f:
            codes = json.load(f)
        print(f"  📂 加载早盘候选: {len(codes)} 只")
        return pd.DataFrame({"code": codes})
    return None


def main():
    if len(sys.argv) < 2:
        from reporter import show_daily_checklist
        show_daily_checklist()
        return

    cmd = sys.argv[1].lower()

    commands = {
        # V1
        "morning": cmd_morning,
        "afternoon": cmd_afternoon,
        "review": cmd_review,
        "buy": lambda: cmd_buy(sys.argv[2:]),
        "sell": lambda: cmd_sell(sys.argv[2:]),
        "backtest": cmd_backtest,
        "checklist": lambda: (
            banner(),
            __import__("reporter", fromlist=["show_daily_checklist"]).show_daily_checklist()
        ),
        # V2
        "v2-scan": cmd_v2_scan,
        "v2-snapshot": cmd_v2_snapshot,
        "v2-settle": cmd_v2_settle,
        "v2-dashboard": cmd_v2_dashboard,
        "v2-cron-list": cmd_v2_cron_list,
        "v2-ic": cmd_v2_ic,
        # V4 兼容模拟工具
        "sim-status": cmd_sim_status,
        "sim-plan": cmd_sim_plan,
        "sim-buy": cmd_sim_buy,
        "sim-sell": cmd_sim_sell,
        "sim-reset": cmd_sim_reset,
    }

    if cmd in commands:
        commands[cmd]()
    else:
        print(f"  ❌ 未知命令: {cmd}")
        print("  可用命令:")
        print("  V1: morning / afternoon / review / buy / sell / backtest / checklist")
        print("  V2: v2-scan / v2-snapshot / v2-settle / v2-dashboard / v2-cron-list / v2-ic")
        print("  SIM: sim-status / sim-plan / sim-buy / sim-sell / sim-reset")


if __name__ == "__main__":
    main()
