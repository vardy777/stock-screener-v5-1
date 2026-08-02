"""V3 推送工具"""
import hashlib
import html
import os
import urllib.request
import urllib.parse
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from v3.config import DATA_DIR, POSITION_SIZE, PUSHPLUS_TOKEN

logger = logging.getLogger(__name__)
PUSH_RECEIPT_PATH = Path(DATA_DIR) / "push_receipts.json"


def _load_receipts() -> dict:
    try:
        value = json.loads(PUSH_RECEIPT_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, TypeError, ValueError):
        return {}


def _already_sent(message_key: str) -> bool:
    return bool(message_key and message_key in _load_receipts())


def _record_sent(message_key: str, title: str, content: str) -> None:
    if not message_key:
        return
    receipts = _load_receipts()
    cutoff = datetime.now(timezone.utc) - timedelta(days=45)
    clean = {}
    for key, value in receipts.items():
        try:
            sent_at = datetime.fromisoformat(str(value.get("sent_at", "")))
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
            if sent_at >= cutoff:
                clean[key] = value
        except (AttributeError, TypeError, ValueError):
            continue
    clean[message_key] = {
        "sent_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "title": title,
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }
    PUSH_RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = PUSH_RECEIPT_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(clean, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(PUSH_RECEIPT_PATH)


def send_wechat(
    title,
    content,
    template="html",
    *,
    message_key=None,
    attempts=3,
    retry_delay_seconds=1.0,
):
    """通过 PushPlus 发送微信推送，并提供重试和每日幂等保护。"""
    if os.getenv("PUSHPLUS_DRY_RUN", "").strip().lower() in {
        "1", "true", "yes"
    }:
        logger.info("PushPlus dry-run: title=%s content_length=%d", title, len(content))
        return True
    if message_key and _already_sent(str(message_key)):
        logger.info("PushPlus duplicate suppressed: key=%s", message_key)
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
    attempts = max(1, min(int(attempts), 5))
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, data=data, method='POST')
            req.add_header('Content-Type', 'application/x-www-form-urlencoded')
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = resp.read().decode()
            try:
                payload = json.loads(result)
            except (TypeError, ValueError):
                logger.error('PushPlus returned invalid JSON (attempt %d/%d)', attempt, attempts)
                payload = {}
            success = int(payload.get('code', 0) or 0) == 200
            if success:
                _record_sent(str(message_key or ""), title, content)
                logger.info('PushPlus accepted message: code=200 attempt=%d', attempt)
                return True
            logger.error(
                'PushPlus rejected message: code=%s msg=%s attempt=%d/%d',
                payload.get('code'), payload.get('msg', 'unknown'), attempt, attempts,
            )
        except Exception as exc:
            logger.error(
                'PushPlus send failed: %s attempt=%d/%d', exc, attempt, attempts
            )
        if attempt < attempts and retry_delay_seconds > 0:
            time.sleep(float(retry_delay_seconds) * attempt)
    return False


def _market_diagnostics(market_state: dict, candidates) -> str:
    coverage = float(market_state.get("quote_coverage", 0.0) or 0.0) * 100
    valid = "有效" if market_state.get("data_valid") is True else "无效/不足"
    raw_regime = market_state.get("regime_score", -1.0)
    regime = float(raw_regime if raw_regime is not None else -1.0)
    quote_time = next(
        (str(item.get("quote_time")) for item in candidates if item.get("quote_time")),
        "未知",
    )
    return (
        f'<p>全市场覆盖: {coverage:.1f}%（{valid}） | 环境分: {regime:+.2f}'
        f' | 行情时间: {html.escape(quote_time)}</p>'
    )

def build_morning_card(candidates, market_state, positions=None) -> str:
    """构建09:25观察候选与待卖持仓HTML卡片。"""
    mode = market_state.get('mode_label', '?')
    card = f'<h3>🌅 09:25早盘观察池</h3><p>市场: {html.escape(str(mode))}</p>'
    card += _market_diagnostics(market_state, candidates)
    card += '<p style="color:#d97706">仅建立观察池，必须等待14:50尾盘确认，早盘不买入。</p>'
    card += '<table>'
    card += '<tr><th>#</th><th>代码</th><th>名称</th><th>评分</th><th>涨幅</th></tr>'
    for i, s in enumerate(candidates[:5]):
        color = '#ff4757' if s.get('pct_chg',0) > 0 else '#2ed573'
        card += f'<tr><td>{i+1}</td><td>{html.escape(str(s.get("code","")))}</td><td>{html.escape(str(s.get("name","")))}</td>'
        score = float(s.get('final_score', s.get('score', 0)) or 0)
        card += f'<td>{score:.0f}</td><td style="color:{color}">{float(s.get("pct_chg",0) or 0):+.2f}%</td></tr>'
    card += '</table>'
    positions = positions or []
    if positions:
        card += '<h4>⏰ 09:30待卖持仓</h4><ul>'
        for position in positions:
            card += (
                f'<li>{html.escape(str(position.get("code","")))} {html.escape(str(position.get("name","")))} '
                f'成本¥{float(position.get("buy_price",0) or 0):.2f}</li>'
            )
        card += '</ul>'
    else:
        card += '<p>当前无待卖持仓。</p>'
    card += '<p style="color:#888;font-size:12px">📌 早盘候选不是买入指令；14:50重新计算后才确认。</p>'
    return card

def build_afternoon_card(candidates, market_state, positions) -> str:
    """构建尾盘买入建议HTML卡片"""
    tradable = [item for item in candidates if item.get('v4_tradable')]
    card = '<h3>🎯 V4 14:50尾盘确认</h3>'
    card += f'<p>市场: {html.escape(str(market_state.get("mode_label","?")))}</p>'
    card += _market_diagnostics(market_state, candidates)
    if not tradable:
        card += '<p style="color:#d97706">当前仅输出观察候选，V4没有生成可执行买入。</p>'
    else:
        selected = tradable[0]
        card += (
            '<p style="color:#15803d">唯一确认Top1：'
            f'{html.escape(str(selected.get("code","")))} {html.escape(str(selected.get("name","")))}</p>'
        )
    card += '<table><tr><th>#</th><th>代码</th><th>名称</th><th>模型预期</th><th>盈利概率</th><th>大亏概率</th><th>V4决策</th></tr>'
    for i, s in enumerate(candidates[:3]):
        card += f'<tr><td>{i+1}</td><td>{html.escape(str(s.get("code","")))}</td><td>{html.escape(str(s.get("name","")))}</td>'
        expected = s.get('predicted_return')
        positive = s.get('predicted_positive_probability')
        loss = s.get('predicted_large_loss_probability')
        expected_text = f'{float(expected)*100:+.2f}%' if expected is not None else '—'
        positive_text = f'{float(positive)*100:.1f}%' if positive is not None else '—'
        loss_text = f'{float(loss)*100:.1f}%' if loss is not None else '—'
        reasons = '、'.join(s.get('v4_block_reasons', [])) or '通过'
        decision = '✅ 可模拟' if s.get('v4_tradable') else f'⏸ {reasons}'
        card += f'<td>{expected_text}</td><td>{positive_text}</td><td>{loss_text}</td><td>{html.escape(decision)}</td></tr>'
    card += '</table>'
    if positions:
        card += f'<p>当前持仓: {len(positions)} 只</p>'
    card += '<p style="color:#888;font-size:12px">⚠️ 仅当V4显示“可模拟”时才通过研究门禁；次日09:30连续竞价卖出。</p>'
    return card

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
