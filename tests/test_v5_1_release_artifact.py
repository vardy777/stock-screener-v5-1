import ast,json
from pathlib import Path
from v5_1.production_acceptance import dependency_scan,verify_release

def test_dependency_scan_rejects_reintroduced_v5_runtime_import(tmp_path):
    folder=tmp_path/"v5_1";folder.mkdir();(folder/"bad.py").write_text("from v5.core import ContractViolation\n",encoding="utf-8")
    assert dependency_scan(tmp_path)==["bad.py:1:v5.core"]

def test_release_hash_mismatch_is_blocking(tmp_path):
    (tmp_path/"payload.txt").write_text("original",encoding="utf-8")
    import hashlib
    digest=hashlib.sha256((tmp_path/"payload.txt").read_bytes()).hexdigest()
    (tmp_path/"MANIFEST_SHA256.json").write_text(json.dumps({"payload.txt":digest}),encoding="utf-8")
    assert verify_release(tmp_path)[0]
    (tmp_path/"payload.txt").write_text("tampered",encoding="utf-8")
    assert verify_release(tmp_path)[0] is False

def test_release_config_is_fail_closed():
    row=json.loads((Path(__file__).parents[1]/"v5_1"/"release_config_schema.json").read_text(encoding="utf-8"))
    assert row["required"]=={"research_locked":True,"broker_orders":False,"minimum_market_coverage":0.95,"production_cutover_authorized":False}
