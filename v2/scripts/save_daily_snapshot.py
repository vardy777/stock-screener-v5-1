#!/usr/bin/env python
"""
save_daily_snapshot.py — 每日09:00运行
从新浪API拉取全市场4000+股票实时快照
从东方财富获取PE/PB/流通市值/行业数据
保存到 market.db (sqlite) 和 pe_pb_cache.json
"""
import sys, os, json, sqlite3, logging, urllib.request, re, time
from datetime import datetime, date
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from v2.config import DATA_DIR, MARKET_DB, PE_PB_CACHE

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s %(message)s')
logger = logging.getLogger('save_snapshot')

SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}
EM_HEADERS = {
    "Referer": "https://quote.eastmoney.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

# ── 全市场股票代码枚举 ──
STOCK_RANGES = [
    [f"6{i:05d}" for i in range(0, 1000)],        # sh 600000-600999
    [f"6{i:05d}" for i in range(1000, 2000)],      # sh 601000-601999
    [f"6{i:05d}" for i in range(2000, 3000)],      # sh 602000-602999
    [f"6{i:05d}" for i in range(3000, 4000)],      # sh 603000-603999
    [f"6{i:05d}" for i in range(8000, 8100)],      # sh 688xxx
    [f"0{i:04d}" for i in range(1, 1000)],         # sz 000001-000999
    [f"00{i:04d}" for i in range(2001, 3000)],     # sz 002001-002999
    [f"30{i:04d}" for i in range(1, 500)],         # sz 300001-300499
    [f"30{i:04d}" for i in range(500, 1000)],      # sz 300500-300999
]

# ── 新浪数据获取 ──

def _fetch_url(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers=SINA_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                return raw.decode("gbk")
            except UnicodeDecodeError:
                return raw.decode("gbk", errors="replace")
    except Exception as e:
        return None

def batch_fetch_quotes(codes, batch_size=800):
    if not codes:
        return []
    rows = []
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
        text = _fetch_url(url)
        if text:
            rows.extend(_parse_sina_response(text))
        if i + batch_size < len(codes):
            time.sleep(0.3)
    return rows

def _parse_sina_response(text):
    rows = []
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
            if not name or name == "0" or name.startswith("ST") or "退" in name:
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
            rows.append({
                "code": code, "name": name,
                "price": round(price, 2),
                "change_pct": change_pct,
                "high": round(high, 2), "low": round(low, 2),
                "open": round(open_price, 2),
                "prev_close": round(prev_close, 2),
                "volume": int(volume_hand * 100),
                "amount": round(amount, 2),
            })
        except (ValueError, IndexError, TypeError):
            continue
    return rows

# ── 东方财富 PE/PB/市值 ──

def _fetch_em_json(url, timeout=10):
    try:
        req = urllib.request.Request(url, headers=EM_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        return None

def fetch_pe_pb_batch(codes):
    """批量获取 PE/PB/流通市值/行业，使用东方财富行情 API"""
    if not codes:
        return {}
    # 东方财富接口：一次最多取5000只
    market_codes = []
    for code in codes:
        code = str(code).strip()
        market = 1 if code.startswith("6") else 0
        market_codes.append(f"{market}.{code}")
    code_str = ",".join(market_codes)
    url = (f"https://push2.eastmoney.com/api/qt/clist/get?"
           f"pn=1&pz={len(codes)}&po=1&np=1&fltt=2&invt=2&fid=f3"
           f"&fs=m:0+t:1,m:1+t:2&fields=f12,f14,f9,f23,f20,f21,f57,f58,f100"
           f"&secids={code_str}")
    data = _fetch_em_json(url)
    if not data:
        return {}
    items = data.get("data", {}).get("diff", [])
    result = {}
    for item in items:
        code = str(item.get("f12", ""))
        result[code] = {
            "pe_ttm": item.get("f9"),
            "pb": item.get("f23"),
            "total_market_cap": item.get("f20"),      # 总市值
            "circulating_market_cap": item.get("f21"), # 流通市值
            "industry": item.get("f57"),                # 行业
            "industry_desc": item.get("f58"),           # 行业描述
        }
    return result

# ── SQLite 存储 ──

def init_db():
    conn = sqlite3.connect(MARKET_DB)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT,
            price REAL,
            change_pct REAL,
            high REAL,
            low REAL,
            open REAL,
            prev_close REAL,
            volume INTEGER,
            amount REAL,
            pe_ttm REAL,
            pb REAL,
            total_market_cap REAL,
            circulating_market_cap REAL,
            industry TEXT,
            industry_desc TEXT,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_snapshot_date ON daily_snapshot(date)
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_snapshot_code ON daily_snapshot(code)
    """)
    conn.commit()
    return conn

def save_snapshot(conn, date_str, stocks):
    c = conn.cursor()
    # 先删当日旧数据
    c.execute("DELETE FROM daily_snapshot WHERE date=?", (date_str,))
    now = datetime.now().isoformat()
    rows = []
    for s in stocks:
        rows.append((
            date_str, s.get("code"), s.get("name"),
            s.get("price"), s.get("change_pct"),
            s.get("high"), s.get("low"), s.get("open"),
            s.get("prev_close"), s.get("volume"), s.get("amount"),
            s.get("pe_ttm"), s.get("pb"),
            s.get("total_market_cap"), s.get("circulating_market_cap"),
            s.get("industry"), s.get("industry_desc"),
            now,
        ))
    c.executemany("""
        INSERT INTO daily_snapshot
        (date, code, name, price, change_pct, high, low, open, prev_close,
         volume, amount, pe_ttm, pb, total_market_cap, circulating_market_cap,
         industry, industry_desc, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)
    conn.commit()
    logger.info(f"已保存 {len(rows)} 条快照到 {MARKET_DB}")

# ── 主流程 ──

def main():
    today = date.today().strftime("%Y-%m-%d")
    logger.info(f"=== 开始全市场快照 {today} ===")

    # 1. 获取新浪实时行情
    all_stocks = []
    for codes in STOCK_RANGES:
        batch = batch_fetch_quotes(codes, batch_size=800)
        all_stocks.extend(batch)
        logger.info(f"  范围内 {codes[0]}..{codes[-1]}: 获取 {len(batch)} 只")
        time.sleep(0.2)

    logger.info(f"新浪行情获取完成: 共 {len(all_stocks)} 只股票")

    # 2. 获取 PE/PB/行业
    codes = [s["code"] for s in all_stocks]
    pe_pb = fetch_pe_pb_batch(codes)
    logger.info(f"东方财富数据获取完成: {len(pe_pb)} 只")

    # 3. 合并数据
    for s in all_stocks:
        info = pe_pb.get(s["code"], {})
        s["pe_ttm"] = info.get("pe_ttm")
        s["pb"] = info.get("pb")
        s["total_market_cap"] = info.get("total_market_cap")
        s["circulating_market_cap"] = info.get("circulating_market_cap")
        s["industry"] = info.get("industry")
        s["industry_desc"] = info.get("industry_desc")

    # 4. 保存到 DB
    conn = init_db()
    save_snapshot(conn, today, all_stocks)
    conn.close()

    # 5. 保存 PE/PB 缓存 JSON
    pe_pb_cache = {}
    for code, info in pe_pb.items():
        pe_pb_cache[code] = info
    with open(PE_PB_CACHE, "w", encoding="utf-8") as f:
        json.dump(pe_pb_cache, f, ensure_ascii=False, indent=2)
    logger.info(f"PE/PB 缓存已保存: {PE_PB_CACHE}")

    # 6. 统计摘要
    valid = [s for s in all_stocks if s.get("price", 0) > 0]
    up = sum(1 for s in valid if s.get("change_pct", 0) > 0)
    down = sum(1 for s in valid if s.get("change_pct", 0) < 0)
    logger.info(f"快照摘要: 有效{len(valid)}只, 涨{up}, 跌{down}, 平{len(valid)-up-down}")
    logger.info("=== 快照完成 ===")

if __name__ == "__main__":
    main()
