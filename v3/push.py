"""V3 推送工具"""
import os
import urllib.request
import urllib.parse
import json
import logging
from v3.config import POSITION_SIZE, PUSHPLUS_TOKEN

logger = logging.getLogger(__name__)

def send_wechat(title, content, template='html'):
    """通过 PushPlus 发送微信推送 (POST)"""
    if os.getenv("PUSHPLUS_DRY_RUN", "").strip().lower() in {
        "1", "true", "yes"
    }:
        logger.info("PushPlus dry-run: title=%s content_length=%d", title, len(content))
        return True
    if not PUSHPLUS_TOKEN:
        logger.warning('PUSHPLUS_TOKEN not set, skipping push')
        fallback = f'\n=== {title} ===\n{content}'
        try:
            print(fallback)
        except UnicodeEncodeError:
            encoding = getattr(__import__('sys').stdout, 'encoding', None) or 'utf-8'
            print(fallback.encode(encoding, errors='replace').decode(encoding))
        return False

    url = 'https://pushplus.plus/send'
    data = urllib.parse.urlencode({
        'token': PUSHPLUS_TOKEN,
        'title': title,
        'content': content,
        'template': template,
    }).encode('utf-8')
    try:
        req = urllib.request.Request(url, data=data, method='POST')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = resp.read().decode()
            try:
                payload = json.loads(result)
            except (TypeError, ValueError):
                logger.error('PushPlus returned invalid JSON')
                return False
            success = int(payload.get('code', 0)) == 200
            if success:
                logger.info('PushPlus accepted message: code=200')
            else:
                logger.error(
                    'PushPlus rejected message: code=%s msg=%s',
                    payload.get('code'), payload.get('msg', 'unknown'),
                )
            return success
    except Exception as e:
        logger.error('PushPlus send failed: %s', e)
        return False

def build_morning_card(candidates, market_state, positions=None) -> str:
    """构建09:25观察候选与待卖持仓HTML卡片。"""
    mode = market_state.get('mode_label', '?')
    html = f'<h3>🌅 09:25早盘观察池</h3><p>市场: {mode}</p>'
    html += '<p style="color:#d97706">仅建立观察池，必须等待14:50尾盘确认，早盘不买入。</p>'
    html += '<table>'
    html += '<tr><th>#</th><th>代码</th><th>名称</th><th>评分</th><th>涨幅</th></tr>'
    for i, s in enumerate(candidates[:5]):
        color = '#ff4757' if s.get('pct_chg',0) > 0 else '#2ed573'
        html += f'<tr><td>{i+1}</td><td>{s.get("code","")}</td><td>{s.get("name","")}</td>'
        score = s.get('final_score', s.get('score', 0))
        html += f'<td>{score:.0f}</td><td style="color:{color}">{s.get("pct_chg",0):+.2f}%</td></tr>'
    html += '</table>'
    positions = positions or []
    if positions:
        html += '<h4>⏰ 09:30待卖持仓</h4><ul>'
        for position in positions:
            html += (
                f'<li>{position.get("code","")} {position.get("name","")} '
                f'成本¥{float(position.get("buy_price",0) or 0):.2f}</li>'
            )
        html += '</ul>'
    else:
        html += '<p>当前无待卖持仓。</p>'
    html += '<p style="color:#888;font-size:12px">📌 早盘候选不是买入指令；14:50重新计算后才确认。</p>'
    return html

def build_afternoon_card(candidates, market_state, positions) -> str:
    """构建尾盘买入建议HTML卡片"""
    tradable = [item for item in candidates if item.get('v4_tradable')]
    html = '<h3>🎯 V4 14:50尾盘确认</h3>'
    html += f'<p>市场: {market_state.get("mode_label","?")}</p>'
    if not tradable:
        html += '<p style="color:#d97706">当前仅输出观察候选，V4没有生成可执行买入。</p>'
    else:
        selected = tradable[0]
        html += (
            '<p style="color:#15803d">唯一确认Top1：'
            f'{selected.get("code","")} {selected.get("name","")}</p>'
        )
    html += '<table><tr><th>#</th><th>代码</th><th>名称</th><th>评分</th><th>影子置信</th><th>V4决策</th></tr>'
    for i, s in enumerate(candidates[:3]):
        html += f'<tr><td>{i+1}</td><td>{s.get("code","")}</td><td>{s.get("name","")}</td>'
        score = s.get('final_score', s.get('score', 0))
        confidence = float(s.get('v4_shadow_confidence', 0) or 0) * 100
        reasons = '、'.join(s.get('v4_block_reasons', [])) or '通过'
        decision = '✅ 可模拟' if s.get('v4_tradable') else f'⏸ {reasons}'
        html += f'<td>{score:.0f}</td><td>{confidence:.0f}%</td><td>{decision}</td></tr>'
    html += '</table>'
    if positions:
        html += f'<p>当前持仓: {len(positions)} 只</p>'
    html += '<p style="color:#888;font-size:12px">⚠️ 仅当V4显示“可模拟”时才通过研究门禁；次日09:30连续竞价卖出。</p>'
    return html

def build_settlement_card(summary: dict) -> str:
    """构建结算报告HTML卡片"""
    html = '<h3>💰 昨日结算</h3>'
    html += f'<p>交易: {summary.get("trades",0)}笔 | 胜率: {summary.get("win_rate",0)*100:.0f}%</p>'
    html += f'<p>总盈亏: <span style="color:{"#ff4757" if summary.get("total_return",0)>0 else "#2ed573"}">{summary.get("total_return",0):+.2f}%</span></p>'
    html += '<table><tr><th>代码</th><th>买入</th><th>卖出</th><th>盈亏</th></tr>'
    for t in summary.get('trades_detail', []):
        color = '#ff4757' if t.get('profit',0) > 0 else '#2ed573'
        html += f'<tr><td>{t.get("code","")}</td><td>{t.get("buy_price",0):.2f}</td><td>{t.get("sell_price",0):.2f}</td>'
        html += f'<td style="color:{color}">{t.get("profit",0):+.2f}%</td></tr>'
    html += '</table>'
    return html
