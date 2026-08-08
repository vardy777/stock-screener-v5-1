"""Offline P7 release-bundle audit; never publishes or changes runtime gates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .model_registry import PublishedModelRegistry


def _sha(path: Path) -> str:
    try: return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError: return ""


def audit_release_bundle(model_dir: Path, normal_report: Path, stress_report: Path) -> dict:
    model_dir=Path(model_dir); normal_report=Path(normal_report); stress_report=Path(stress_report)
    registry=PublishedModelRegistry(model_dir); reasons=[]
    if not registry.available: reasons.append("REGISTRY_REJECTED:"+(registry.error or "unknown"))
    training=dict(registry.info)
    if training.get("research_only",True): reasons.append("RESEARCH_ONLY")
    if training.get("normal_report_sha256") != _sha(normal_report): reasons.append("NORMAL_REPORT_LINEAGE_MISMATCH")
    if training.get("stress_report_sha256") != _sha(stress_report): reasons.append("STRESS_REPORT_LINEAGE_MISMATCH")
    if not normal_report.is_file(): reasons.append("NORMAL_REPORT_MISSING")
    if not stress_report.is_file(): reasons.append("STRESS_REPORT_MISSING")
    facts={"model_manifest_sha256":_sha(model_dir/"published_model.json"),
           "normal_report_sha256":_sha(normal_report),"stress_report_sha256":_sha(stress_report)}
    raw=json.dumps({"reasons":reasons,"facts":facts},sort_keys=True,separators=(",",":"))
    return {"schema_version":"model-release-audit-v1","passed":not reasons,"reasons":reasons,
            "facts":facts,"audit_id":"mra1-"+hashlib.sha256(raw.encode()).hexdigest()[:24],
            "changes_production_status":False}
