#!/usr/bin/env python
"""
push_14_50.py — 14:50运行, 尾盘3支精选+Kelly仓位
最终精选3支
计算Kelly仓位(每只分配百分比)
行业分散检查
通过 PushPlus 推送最终买入建议
"""
import sys, os, json, logging, math
from datetime import datetime, date
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from v2.config import DATA_DIR, PUSHPLUS_TOKEN, KELLY, RISK

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s %(message)s')
logger = logging.getLogger('push_14_50')


def load_verify_data():
    """从 dashboard_data.json 加载验证后的候选池"""
    path = os.path.join(DATA_DIR, "dashboard_data.json")
    if not os.path.exists(path):
        logger.error("dashboard_data.json 不存在")
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
        verify = data.get("verify", {})
        candidates = verify.get("candidates", [])
        if not candidates:
            # fallback to morning candidates
            morning = data.get("morning", {})
            candidates = morning.get("candidates", [])
        return candidates
    except Exception as e:
        logger.error(f"加载验证数据失败: {e}")
        return []


def load_win_rate():
    """加载历史胜率用于 Kelly 计算"""
    path = os.path.join(DATA_DIR, "win_rate_data.json")
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            cum = data.get("cumulative", {})
            return {
                "win_rate": cum.get("win_rate", KELLY["win_rate_default"]) / 100,
                "total_trades": cum.get("total_trades", 0),
            }
        except Exception:
            pass
    return {"win_rate": KELLY["win_rate_default"], "total_trades": 0}


def calc_kelly_pct(win_rate, avg_win=2.0, avg_loss=-1.5):
    """
    Kelly 公式: f* = (p * b - q) / b
    其中 p=胜率, q=1-p, b=盈亏比(赢/输绝对值)
    """
    if avg_loss >= 0:
        return KELLY["min_single_pct"] / 100
    b = abs(avg_win / avg_loss)  # 盈亏比
    p = win_rate
    q = 1 - p
    f = (p * b - q) / b
    # 限制范围
    f = max(KELLY["min_single_pct"] / 100, min(f, KELLY["max_single_pct"] / 100))
    return f


def check_industry_diversification(picks):
    """行业分散检查: 同行业不超过 max_same_industry_pct"""
    industry_count = defaultdict(int)
    for p in picks:
        ind = p.get("industry", "未知") or "未知"
        industry_count[ind] += 1
    max_pct = RISK["max_same_industry_pct"] / 100
    total = len(picks)
    for ind, cnt in industry_count.items():
        if cnt / total > max_pct:
            return False, f"行业 {ind} 占比 {cnt/total:.0%}, 超过限制 {max_pct:.0%}"
    return True, "行业分散 OK"


def score_for_final_pick(candidate):
    """对候选进行最终评分精选"""
    score = 0
    # 涨幅适中
    cp = candidate.get("change_pct", 0)
    if 1.0 <= cp <= 5.0:
        score += 30
    elif cp > 5.0:
        score += 15
    elif cp < 0:
        score -= 10

    # 日内位置
    pos = candidate.get("close_position", 0.5)
    if 0.3 <= pos <= 0.8:
        score += 25
    elif pos > 0.9:
        score -= 5

    # 成交量健康
    if candidate.get("volume_healthy", False):
        score += 20

    # 无风险
    risks = candidate.get("risks", [])
    score -= len(risks) * 10

    return score


def push_to_wechat(title, content):
    if not PUSHPLUS_TOKEN:
        logger.warning("PUSHPLUS_TOKEN 未设置, 跳过推送")
        return
    import urllib.request
    import urllib.parse
    data = urllib.parse.urlencode({
        "token": PUSHPLUS_TOKEN,
        "title": title,
        "content": content,
        "template": "html",
    }).encode()
    url = "https://pushplus.plus/send"
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = resp.read().decode()
            logger.info(f"PushPlus 推送结果: {result}")
    except Exception as e:
        logger.error(f"PushPlus 推送失败: {e}")


def generate_html_report(picks):
    """生成最终买入建议 HTML"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = ""
    total_alloc = sum(p.get("kelly_pct", 0) for p in picks)
    for i, p in enumerate(picks):
        kp = p.get("kelly_pct", 0)
        amount_pct = round(kp / total_alloc * 100, 1) if total_alloc > 0 else 0
        rows += f"""
        <tr>
            <td>{i+1}</td>
            <td><b>{p.get('code','')}</b></td>
            <td>{p.get('name','')}</td>
            <td>{p.get('change_pct',0):+.2f}%</td>
            <td>{p.get('industry','N/A')}</td>
            <td>{p.get('final_score',0)}</td>
            <td>{kp:.1f}%</td>
            <td>{amount_pct:.1f}%</td>
        </tr>"""

    html = f"""
    <html>
    <head><meta charset="utf-8"><style>
        body {{ font-family: 'Microsoft YaHei', sans-serif; background: #1a1a2e; color: #eee; padding: 16px; }}
        h2 {{ color: #e94560; border-bottom: 2px solid #e94560; padding-bottom: 8px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
        th {{ background: #16213e; color: #00a8ff; padding: 8px; text-align: left; }}
        td {{ padding: 8px; border-bottom: 1px solid #333; }}
        .score {{ color: #4ecca3; }}
        .warn {{ color: #ffd93d; }}
        .summary {{ background: #16213e; border-radius: 8px; padding: 12px; margin: 8px 0; }}
    </style></head>
    <body>
        <h2>🎯 尾盘精选买入建议</h2>
        <p>⏰ {now}</p>
        <div class="summary">
            <p><b>总仓位:</b> {KELLY['total_position_pct']}%</p>
            <p><b>持仓上限:</b> {RISK['max_positions']} 只</p>
            <p><b>止损:</b> {RISK['stop_loss_pct']:.0f}%</p>
        </div>
        <table>
            <tr><th>#</th><th>代码</th><th>名称</th><th>涨幅</th><th>行业</th><th>评分</th><th>Kelly</th><th>建议仓位</th></tr>
            {rows}
        </table>
        <p style="color:#888;">💡 买入窗口: 14:50-14:55, 尾盘集合竞价前完成</p>
    </body>
    </html>"""
    return html


def main():
    today = date.today().strftime("%Y-%m-%d")
    logger.info(f"=== 尾盘精选推送 {today} ===")

    # 1. 加载候选数据
    candidates = load_verify_data()
    if not candidates:
        logger.error("无候选数据")
        return

    logger.info(f"候选池: {len(candidates)} 只")

    # 2. 精选评分
    for c in candidates:
        c["final_score"] = score_for_final_pick(c)

    candidates.sort(key=lambda x: x.get("final_score", 0), reverse=True)

    # 3. 行业分散检查, 精选3只
    top3 = []
    seen_industries = defaultdict(int)
    for c in candidates:
        if len(top3) >= RISK["max_positions"]:
            break
        ind = c.get("industry", "未知") or "未知"
        # 同行业最多选1只
        max_same = max(1, int(RISK["max_positions"] * (1 - RISK["max_same_industry_pct"] / 100)))
        if seen_industries[ind] >= max_same:
            continue
        top3.append(c)
        seen_industries[ind] += 1

    # 如果还不够3只, 从剩余随便补
    if len(top3) < RISK["max_positions"]:
        for c in candidates:
            if c not in top3 and len(top3) < RISK["max_positions"]:
                top3.append(c)

    logger.info(f"精选 {len(top3)} 只")

    # 4. 计算 Kelly 仓位
    wr_data = load_win_rate()
    win_rate = wr_data["win_rate"]
    kelly_fraction = calc_kelly_pct(win_rate, KELLY["avg_win_pct"], KELLY["avg_loss_pct"])

    logger.info(f"Kelly 参数: 胜率={win_rate:.1%}, 仓位比例={kelly_fraction:.1%}")

    for p in top3:
        # 基于 Kelly 比例再根据评分微调
        score_factor = p.get("final_score", 50) / 100
        pct = kelly_fraction * (0.8 + 0.4 * score_factor) * 100
        pct = max(KELLY["min_single_pct"], min(pct, KELLY["max_single_pct"]))
        p["kelly_pct"] = round(pct, 1)

    logger.info(f"精选结果:")
    for p in top3:
        logger.info(f"  {p.get('code','')} {p.get('name','')} "
                    f"评分{p.get('final_score',0)} Kelly:{p.get('kelly_pct',0):.1f}% "
                    f"行业:{p.get('industry','N/A')}")

    # 5. 行业分散报告
    ok, msg = check_industry_diversification(top3)
    logger.info(f"行业分散检查: {msg}")

    # 6. 保存到 dashboard
    dashboard_path = os.path.join(DATA_DIR, "dashboard_data.json")
    if os.path.exists(dashboard_path):
        try:
            existing = json.load(open(dashboard_path, "r"))
            existing["final_picks"] = {
                "picks": [{
                    "code": p.get("code", ""),
                    "name": p.get("name", ""),
                    "price": p.get("price", 0),
                    "change_pct": p.get("change_pct", 0),
                    "industry": p.get("industry", ""),
                    "kelly_pct": p.get("kelly_pct", 0),
                    "final_score": p.get("final_score", 0),
                } for p in top3],
                "time": datetime.now().strftime("%H:%M"),
                "diversification": msg,
            }
            with open(dashboard_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存 dashboard 失败: {e}")

    # 7. PushPlus 推送
    html = generate_html_report(top3)
    push_to_wechat(f"🎯 尾盘精选 {today}", html)

    logger.info("=== 尾盘精选推送完成 ===")


if __name__ == "__main__":
    main()
