"""Small, testable P5 HTML components; inputs are read-model projections only."""
import html

def _esc(value): return html.escape(str(value))

def render_acceptance_panels(state):
    evidence=state.get("evidence",{}); operations=state.get("operations",{})
    windows=evidence.get("live_windows",[])
    rows="".join(f"<tr><td>{_esc(x.get('name'))}</td><td>{_esc(x.get('status'))}</td><td>{_esc(', '.join(x.get('reasons',[])) or '—')}</td></tr>" for x in windows)
    admission=evidence.get("strict_admission",{}); cutover=operations.get("cutover",{})
    return f"""<section class='card span12' data-component='live-window-acceptance'><h2>四个真实窗口验收</h2><table><thead><tr><th>窗口</th><th>状态</th><th>原因</th></tr></thead><tbody>{rows}</tbody></table></section>
<section class='card span6' data-component='strict-sample-admission'><h2>严格样本与模型准入</h2><p>严格样本：<b>{int(admission.get('sample_count',0))}</b></p><p>准入：<b>{'PASSED' if admission.get('passed') else 'BLOCKED'}</b></p><p class='muted'>{_esc(', '.join(admission.get('reasons',[])) or '等待严格 14:50/次日 09:30 样本')}</p></section>
<section class='card span6' data-component='cutover-readiness'><h2>生产切换状态</h2><p>状态：<b>{'APPLIED' if cutover.get('applied') else ('READY' if cutover.get('ready') else 'BLOCKED')}</b></p><p>待执行授权：<b>{'允许' if cutover.get('apply_allowed') else '无'}</b></p><p class='muted'>{_esc(cutover.get('plan_id','尚无切换计划'))}</p></section>"""
