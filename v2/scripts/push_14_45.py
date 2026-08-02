#!/usr/bin/env python
"""
push_14_45.py — 14:45运行, 走势+健康度验证
重新拉取候选池股票的实时行情
检查VWAP位置、成交量健康度、风险排查
通过 PushPlus 推送验证报告
"""
import sys, os, json, sqlite3, logging, urllib.request, re, time
from datetime import datetime, date
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from v2.config import DATA_DIR, MARKET_DB, PUSHPLUS_TOKEN, RISK

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s %(message)s')
logger = logging.getLogger('push_14_45')

SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def fetch_realtime_quotes(codes):
    """从新浪获取实时行情"""
    if not codes:
        return {}
    result = {}
    batch_size = 200
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        sina_codes = []
        for code in batch:
            code = str(code).strip()
            if code.startswith("6"):
                sina_codes.append(f"sh{code}")
            else:
                sina_codes.append(f"sz{code}")
        url = "https://hq.sinajs.cn/list=" + ",".join(sina_codes)
        try:
            req = urllib.request.Request(url, headers=SINA_HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                text = raw.decode("gbk", errors="replace")
            for line in text.strip().split("\n"):
                line = line.strip()
                if not line or not line.startswith("var hq_str_"):
                    continue
                match = re.search(r'"(.+)"', line)
                if not match:
                    continue
                fields = match.group(1).split(",")
                if len(fields) < 10:
                    continue
                try:
                    name = fields[0].strip()
                    if not name or name == "0":
                        continue
                    prev_close = float(fields[2]) if fields[2] else 0
                    price = float(fields[3]) if fields[3] else 0
                    open_price = float(fields[1]) if fields[1] else 0
                    high = float(fields[4]) if fields[4] else 0
                    low = float(fields[5]) if fields[5] else 0
                    volume_hand = float(fields[8]) if fields[8] else 0
                    amount = float(fields[9]) if fields[9] else 0
                    if price <= 0 or prev_close <= 0:
                        continue
                    code_match = re.search(r'var hq_str_(sh|sz)(\d+)="', line)
                    code = code_match.group(2) if code_match else "000000"
                    change_pct = round((price - prev_close) / prev_close * 100, 2)
                    result[code] = {
                        "code": code, "name": name,
                        "price": round(price, 2),
                        "change_pct": change_pct,
                        "high": round(high, 2), "low": round(low, 2),
                        "open": round(open_price, 2),
                        "prev_close": round(prev_close, 2),
                        "volume": int(volume_hand * 100),
                        "amount": round(amount, 2),
                        "close_position": round((price - low) / (high - low), 2) if (high - low) > 0 else 0.5,
                    }
                except (ValueError, IndexError, TypeError):
                    continue
        except Exception as e:
            logger.warning(f"获取行情失败: {e}")
        time.sleep(0.3)
    return result


def calc_vwap(stock):
    """估算 VWAP 位置"""
    price = stock.get("price", 0)
    high = stock.get("high", 0)
    low = stock.get("low", 0)
    if price <= 0 or high <= 0 or low <= 0:
        return 0.5
    # 简单估算: (价格 - 最低) / (最高 - 最低)
    if high == low:
        return 0.5
    return round((price - low) / (high - low), 2)


def check_volume_health(stock):
    """成交量健康度检查"""
    amount = stock.get("amount", 0)
    volume = stock.get("volume", 0)
    price = stock.get("price", 0)
    if amount <= 0 or price <= 0:
        return {"healthy": False, "reason": "数据不足"}
    # 判断成交额是否足够
    if amount < 3e7:
        return {"healthy": False, "reason": f"成交额不足: {amount/1e4:.0f}万"}
    return {"healthy": True, "reason": f"成交额 {amount/1e4:.0f}万"}


def check_risk(stock):
    """风险排查"""
    risks = []
    price = stock.get("price", 0)
    change_pct = stock.get("change_pct", 0)
    high = stock.get("high", 0)
    close_position = stock.get("close_position", 0.5)

    if change_pct > 7:
        risks.append("涨幅过高>7%")
    if close_position > 0.95:
        risks.append("接近日内最高")
    if close_position < 0.2:
        risks.append("位于日内低位")
    if amount := stock.get("amount", 0):
        if amount > 1e10:
            risks.append("成交额过大>100亿")
    return risks


def load_candidate_codes():
    """从 dashboard_data.json 加载候选代码"""
    path = os.path.join(DATA_DIR, "dashboard_data.json")
    if not os.path.exists(path):
        logger.warning("dashboard_data.json 不存在, 尝试从 market.db 加载")
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
        morning = data.get("morning", {})
        candidates = morning.get("candidates", [])
        return [c["code"] for c in candidates]
    except Exception as e:
        logger.error(f"加载候选失败: {e}")
        return []


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


def generate_html_report(verified):
    """生成验证报告 HTML"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = ""
    for s in verified:
        cp = s.get("close_position", 0.5)
        vwap = s.get("vwap_position", 0.5)
        cp_icon = "🟢" if 0.3 <= cp <= 0.85 else "🔴"
        vwap_icon = "🟢" if abs(cp - vwap) < 0.15 else "🟡"
        health_icon = "🟢" if s.get("volume_healthy", False) else "🔴"
        risks = s.get("risks", [])
        risk_str = " | ".join(risks) if risks else "🟢 无异常"
        rows += f"""
        <tr>
            <td><b>{s.get('code','')}</b></td>
            <td>{s.get('name','')}</td>
            <td>{s.get('change_pct',0):+.2f}%</td>
            <td>{cp_icon} {cp:.0%}</td>
            <td>{vwap_icon} {s.get('vwap_position','N/A')}</td>
            <td>{health_icon}</td>
            <td>{risk_str}</td>
        </tr>"""

    html = f"""
    <html>
    <head><meta charset="utf-8"><style>
        body {{ font-family: 'Microsoft YaHei', sans-serif; background: #1a1a2e; color: #eee; padding: 16px; }}
        h2 {{ color: #e94560; }}
        table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
        th {{ background: #16213e; color: #00a8ff; padding: 8px; text-align: left; }}
        td {{ padding: 8px; border-bottom: 1px solid #333; }}
        .pass {{ color: #4ecca3; }}
        .warn {{ color: #ffd93d; }}
        .fail {{ color: #ff6b6b; }}
    </style></head>
    <body>
        <h2>🔍 14:45 走势验证报告</h2>
        <p>⏰ {now}</p>
        <p>🟢 健康 | 🟡 关注 | 🔴 预警</p>
        <table>
            <tr><th>代码</th><th>名称</th><th>涨幅</th><th>位置</th><th>VWAP</th><th>量能</th><th>风险排查</th></tr>
            {rows}
        </table>
        <p style="color:#888;">💡 14:50运行尾盘精选脚本确定最终买入</p>
    </body>
    </html>"""
    return html


def main():
    today = date.today().strftime("%Y-%m-%d")
    logger.info(f"=== 14:45 走势验证 {today} ===")

    # 1. 加载候选股票
    codes = load_candidate_codes()
    if not codes:
        logger.warning("未找到候选股票, 尝试从 market.db 读取今日快照的高评分股票")
        if os.path.exists(MARKET_DB):
            conn = sqlite3.connect(MARKET_DB)
            c = conn.cursor()
            c.execute("""
                SELECT code FROM daily_snapshot WHERE date=? AND amount > 5e7
                ORDER BY change_pct DESC LIMIT 15
            """, (today,))
            codes = [row[0] for row in c.fetchall()]
            conn.close()

    if not codes:
        logger.error("无可验证的候选股票")
        return

    logger.info(f"待验证候选: {len(codes)} 只: {codes}")

    # 2. 重新拉取实时行情
    quotes = fetch_realtime_quotes(codes)
    if not quotes:
        logger.error("获取实时行情失败")
        return

    # 3. 验证每只股票
    verified = []
    for code in codes:
        if code not in quotes:
            logger.warning(f"{code} 无实时数据")
            continue
        q = quotes[code]
        q["vwap_position"] = calc_vwap(q)
        vol_health = check_volume_health(q)
        q["volume_healthy"] = vol_health["healthy"]
        q["volume_note"] = vol_health["reason"]
        risks = check_risk(q)
        q["risks"] = risks
        verified.append(q)

    logger.info(f"验证完成: {len(verified)} 只")

    for s in verified:
        status = "🟢" if not s.get("risks") and s.get("volume_healthy") else "🟡" if len(s.get("risks", [])) <= 1 else "🔴"
        logger.info(f"  {status} {s['code']} {s['name']} {s['change_pct']:+.2f}% 位置{s.get('close_position',0):.0%}")

    # 4. 保存到 dashboard
    dashboard_path = os.path.join(DATA_DIR, "dashboard_data.json")
    if os.path.exists(dashboard_path):
        try:
            existing = json.load(open(dashboard_path, "r"))
            existing["verify"] = {
                "candidates": [{
                    "code": s["code"], "name": s["name"],
                    "price": s["price"], "change_pct": s["change_pct"],
                    "close_position": s.get("close_position", 0),
                    "volume_healthy": s.get("volume_healthy", False),
                    "risks": s.get("risks", []),
                } for s in verified],
                "time": datetime.now().strftime("%H:%M"),
            }
            with open(dashboard_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # 5. PushPlus 推送
    html = generate_html_report(verified)
    push_to_wechat(f"🔍 走势验证 {today}", html)

    logger.info("=== 14:45 验证完成 ===")


if __name__ == "__main__":
    main()
