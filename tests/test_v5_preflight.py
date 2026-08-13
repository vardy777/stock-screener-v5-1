from pathlib import Path
def test_preflight_is_explicitly_diagnostic_prepares_universe_and_never_strict_evidence():
 text=(Path(__file__).resolve().parents[1]/"v5/preflight.py").read_text(encoding="utf-8");assert '"diagnostic_only":True' in text and '"strict_evidence":False' in text and 'refresh_universe(root,now=now)' in text and "notification" not in text and "PaperLedger" not in text
