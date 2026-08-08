#!/usr/bin/env python3
"""
Phase 6: 持续学习系统 - 自动闭环
每天收盘后运行:
  00:00 更新数据库
  00:01 计算100+因子  
  00:02 训练LightGBM
  00:03 生成次日候选股票
  00:04 自动模拟交易
  00:05 更新分析报告
"""
import sys, os, json, pickle, time
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

BASE = Path(__file__).parent.parent  # phase1/
DATA = BASE / 'data'
FACTOR = DATA / 'factor' 
MODEL_DIR = DATA / 'model'
REPORT = DATA / 'report'

# ============================================================
#  Step 1: 更新数据
# ============================================================
def update_data():
    """仅获取今日最新数据"""
    print("[1/5] 更新今日数据...")
    sys.path.insert(0, r'C:\Users\lisha\stock-screener')
    from v4.data import DataFetcher
    
    df = DataFetcher()
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 仅更新已有股票的最新一日数据
    daily_dir = DATA / 'daily'
    files = sorted(daily_dir.glob('*.csv'))[:100]  # 先测试100只
    updated = 0
    
    for f in files:
        code = f.name.replace('.csv','')
        try:
            kline = df.fetch_kline(code, days=10)
            if kline is not None and len(kline) > 0:
                kline.to_csv(f, index=False)
                updated += 1
        except:
            pass
        time.sleep(0.1)
    
    print(f"  ✅ 更新 {updated} 只")

# ============================================================
#  Step 2: 计算因子
# ============================================================
def compute_factors():
    """批量计算100+因子"""
    print("[2/5] 计算因子...")
    
    from scripts.compute_factors import FactorComputer
    daily_dir = DATA / 'daily'
    files = sorted(daily_dir.glob('*.csv'))
    
    all_factors = {}
    for f in files:
        code = f.name.replace('.csv','')
        try:
            fac = FactorComputer.compute(code, f)
            if fac:
                fac['code'] = code
                all_factors[code] = fac
        except:
            pass
    
    df = pd.DataFrame.from_dict(all_factors, orient='index')
    df.index.name = 'code'
    df.to_csv(FACTOR / 'daily_factors.csv')
    print(f"  ✅ {len(df)} 只, {len(df.columns)} 因子")

# ============================================================
#  Step 3: 训练模型
# ============================================================
def train_model():
    """LightGBM训练"""
    print("[3/5] 训练模型...")
    
    try:
        import lightgbm as lgb
    except ImportError:
        print("  ❌ lightgbm 未安装")
        return None
    
    df = pd.read_csv(FACTOR / 'daily_factors.csv', index_col='code')
    
    # 排除688/ST
    codes = df.index.astype(str)
    df = df[~codes.str.startswith('688') & ~codes.str.startswith('8')]
    
    # 标签: 用已有动量方向作为代理
    df['label'] = np.where(df.get('ret_5d', 0) > 0.5, 1, 0)
    
    features = [c for c in df.columns 
                if c not in ('code','rule_score','label','name')
                and df[c].dtype in ('float64','float32','int64','int32')
                and not c.startswith('_')]
    
    X = df[features].fillna(0).astype(float)
    y = df['label']
    
    if len(df) < 100:
        print(f"  ❌ 样本不足 ({len(df)})")
        return None
    
    lgb_train = lgb.Dataset(X, y)
    params = {
        'objective': 'binary',
        'metric': 'auc',
        'boosting': 'gbdt',
        'num_leaves': 21,
        'learning_rate': 0.03,
        'max_depth': 5,
        'min_child_samples': 30,
        'verbose': -1,
    }
    
    model = lgb.train(params, lgb_train, num_boost_round=80)
    
    with open(MODEL_DIR / 'lightgbm_latest.pkl', 'wb') as f:
        pickle.dump(model, f)
    
    # 记录训练时间
    with open(MODEL_DIR / 'last_train.txt', 'w') as f:
        f.write(datetime.now().isoformat())
    
    print(f"  ✅ 模型已训练: {len(features)} 特征, {len(df)} 样本")

# ============================================================
#  Step 4: 生成次日候选
# ============================================================
def generate_candidates():
    """使用模型预测生成Top10候选"""
    print("[4/5] 生成候选...")
    
    df = pd.read_csv(FACTOR / 'daily_factors.csv', index_col='code')
    codes = df.index.astype(str)
    df = df[~codes.str.startswith('688') & ~codes.str.startswith('8')]
    
    # 加载模型
    model_path = MODEL_DIR / 'lightgbm_latest.pkl'
    if not model_path.exists():
        print("  ❌ 无模型, 使用规则评分")
        top = df.nlargest(10, 'rule_score')
        candidates = [(code, row['rule_score'], 'rule') 
                      for code, row in top.iterrows()]
    else:
        with open(model_path, 'rb') as f:
            model = pickle.load(f)
        
        features = [c for c in df.columns 
                    if c not in ('code','rule_score','label','name')
                    and df[c].dtype in ('float64','float32','int64','int32')
                    and not c.startswith('_')]
        
        X = df[features].fillna(0).astype(float)
        preds = model.predict(X.values)
        df['ai_score'] = preds
        top = df.nlargest(10, 'ai_score')
        candidates = [(code, row['ai_score'], 'ai') 
                      for code, row in top.iterrows()]
    
    # 保存
    today = datetime.now().strftime('%Y-%m-%d')
    result = {
        'date': today,
        'generated_at': datetime.now().isoformat(),
        'candidates': [{
            'rank': i+1,
            'code': str(c[0]),
            'score': round(float(c[1]), 3),
            'source': c[2]
        } for i, c in enumerate(candidates)]
    }
    
    with open(REPORT / 'daily_candidates.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"  ✅ Top10:")
    for i, (code, score, source) in enumerate(candidates[:5]):
        print(f"    #{i+1} {code} score={score:.3f} [{source}]")

# ============================================================
#  Step 5: 生成报告
# ============================================================
def generate_report():
    """生成每日分析摘要"""
    print("[5/5] 生成报告...")
    
    # 读取最新交易记录
    trades_path = REPORT / 'trade_details.csv'
    if trades_path.exists():
        trades = pd.read_csv(trades_path)
        recent = trades.tail(30)
        
        wins = len(recent[recent['pnl_pct'] > 0])
        total = len(recent)
        avg_pnl = recent['pnl_pct'].mean()
        
        status = "✅ 盈利" if avg_pnl > 0 else "❌ 亏损"
        print(f"    近期30笔: {wins}/{total} 胜, 平均{avg_pnl:+.2f}% {status}")
    
    # 更新运行日志
    log_path = REPORT / 'pipeline_log.json'
    logs = []
    if log_path.exists():
        with open(log_path, 'r') as f:
            logs = json.load(f)
    
    logs.append({
        'timestamp': datetime.now().isoformat(),
        'status': 'success'
    })
    
    with open(log_path, 'w') as f:
        json.dump(logs[-100:], f, indent=2)  # 只保留最近100条
    
    print(f"  ✅ 完成")

# ============================================================
#  Main
# ============================================================
if __name__ == '__main__':
    print(f"""
╔══════════════════════════════════════════╗
║   Phase 6: 持续学习系统                   ║
║   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}                    ║
╚══════════════════════════════════════════╝
""")
    
    start = time.time()
    
    try:
        # update_data()      # 每日更新
        compute_factors()    # 因子重算
        train_model()        # 模型训练
        generate_candidates() # 生成候选
        generate_report()    # 分析报告
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
    
    elapsed = time.time() - start
    print(f"\n⏱️  总耗时: {elapsed:.0f}s")
    print(f"📊 报告: {REPORT}")
    print(f"📈 候选: {REPORT / 'daily_candidates.json'}")
    print(f"🤖 模型: {MODEL_DIR / 'lightgbm_latest.pkl'}")
