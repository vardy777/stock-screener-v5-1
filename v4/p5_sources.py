"""Read-only adapters from persisted V4 artifacts to the P5 read model.

This module deliberately performs no recovery, migration, selection, quote fetch,
notification, or account write.  Malformed inputs are reported as source issues
instead of being silently replaced with plausible business values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from .execution import CHINA_TZ
from .p5_read_model import DashboardReadModelBuilder
from .p3_account import OfflinePaperLedger
from .calendar import TradingCalendar


@dataclass(frozen=True)
class ReadOnlyArtifactV1:
    name: str
    path: str
    status: str
    sha256: str = ""
    error: str = ""


class P5ReadOnlySources:
    """Load a dashboard projection without mutating any source artifact."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)

    @staticmethod
    def _read(path: Path, name: str) -> tuple[dict, ReadOnlyArtifactV1]:
        try:
            raw = path.read_bytes()
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("root must be an object")
            return value, ReadOnlyArtifactV1(name, str(path), "VALID", hashlib.sha256(raw).hexdigest())
        except FileNotFoundError:
            return {}, ReadOnlyArtifactV1(name, str(path), "MISSING", error="file not found")
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            return {}, ReadOnlyArtifactV1(name, str(path), "INVALID", error=str(exc))

    def latest_journal(self) -> tuple[dict, ReadOnlyArtifactV1]:
        directory = self.data_dir / "candidate_journal"
        paths = sorted(directory.glob("*.json")) if directory.is_dir() else []
        if not paths:
            path = directory / "<latest>.json"
            return {}, ReadOnlyArtifactV1("candidate_journal", str(path), "MISSING", error="no journal")
        return self._read(paths[-1], "candidate_journal")

    @staticmethod
    def _market(context: dict, journal: dict) -> dict:
        raw = dict(context.get("market_state", {}) or {})
        if not raw:
            raw = dict((journal.get("confirmation") or journal.get("morning") or {}).get("market_state", {}) or {})
        sentiment = dict(context.get("sentiment", {}) or {})
        aliases = {
            "rise_count": ("rise_count", "up_count", "rising_count"),
            "fall_count": ("fall_count", "down_count", "falling_count"),
            "flat_count": ("flat_count", "unchanged_count"),
            "limit_up_count": ("limit_up_count", "limit_up"),
            "limit_down_count": ("limit_down_count", "limit_down"),
            "market_total_amount_yi": ("market_total_amount_yi", "total_amount_yi", "turnover_yi"),
            "fresh_quote_coverage": ("fresh_quote_coverage", "coverage"),
        }
        merged = {**sentiment, **raw}
        for target, names in aliases.items():
            if target not in raw:
                raw[target] = next((merged[n] for n in names if n in merged), 0)
        raw.setdefault("as_of", context.get("generated_at", ""))
        raw.setdefault("data_source", "v4/data/market_context.json")
        raw.setdefault("data_valid", bool(raw) and raw.get("data_valid", True))
        return raw

    @staticmethod
    def _fund_flow(value: dict) -> dict:
        if not value:
            return {}
        flows = value.get("sector_flows", {})
        if isinstance(flows, list):
            flows = {str(row.get("name", row.get("sector", ""))): row for row in flows if isinstance(row, dict)}
        return {"status": "current" if flows else "unavailable", "sector_flows": flows,
                "as_of": value.get("time", value.get("date", "")),
                "source": "v4/data/sector_fund_flow.json"}

    def _optional_artifacts(self):
        specs = (
            ("p3_ledger", self.data_dir / "p3" / "paper_ledger.json"),
            ("p3_execution_results", self.data_dir / "p3" / "paper_execution_results.json"),
            ("p4_task_receipts", self.data_dir / "p4" / "task_receipts.json"),
            ("p4_heartbeat", self.data_dir / "p4" / "heartbeat.json"),
            ("live_window_acceptance", self.data_dir / "acceptance" / "live_window_acceptance.json"),
            ("cutover_readiness", self.data_dir / "acceptance" / "cutover_readiness.json"),
            ("strict_model_admission", self.data_dir / "research" / "strict_model_admission.json"),
            ("production_authorization", self.data_dir / "cutover" / "production_authorization.json"),
        )
        return {name: self._read(path, name) for name, path in specs}

    def build(self, *, generated_at: datetime | None = None, production_status: str = "research_locked",
              ledger: dict | None = None, operations: dict | None = None, evidence: dict | None = None):
        generated_at = generated_at or datetime.now(CHINA_TZ)
        journal, journal_meta = self.latest_journal()
        journal_day=str(journal.get("trade_date", ""))
        for key in ("morning","confirmation"):
            if isinstance(journal.get(key),dict) and journal_day:
                journal[key]={**journal[key],"trade_date":journal[key].get("trade_date",journal_day)}
        context, context_meta = self._read(self.data_dir / "market_context.json", "market_context")
        flow, flow_meta = self._read(self.data_dir / "sector_fund_flow.json", "sector_fund_flow")
        operations = dict(operations or {}); evidence = dict(evidence or {})
        optional = self._optional_artifacts()
        # Optional future-owner artifacts appear once created; their absence before
        # cutover is expected and must not masquerade as seven production faults.
        artifacts = [journal_meta, context_meta, flow_meta,
                     *[meta for _, meta in optional.values() if meta.status != "MISSING"]]
        p3_ledger = optional["p3_ledger"][0]
        p3_results = optional["p3_execution_results"][0]
        p4_receipts = optional["p4_task_receipts"][0]
        if ledger is None and p3_ledger:
            account=OfflinePaperLedger(self.data_dir/"p3",initial_cash=p3_ledger.get("initial_cash",100000))
            snapshot=account.snapshot()
            ledger = {**snapshot,"equity":snapshot["cash"]+sum(float(x.get("notional",0)) for x in snapshot["positions"]),
                      "fills":account.fills(),"round_trips":account.round_trips()}
        if not p4_receipts:
            paths=sorted((self.data_dir/"p4"/"outputs").glob("*/*.json")) if (self.data_dir/"p4"/"outputs").is_dir() else []
            p4_receipts={"receipts":[self._read(path,"p4_task_output")[0] for path in paths[-90:]]}
        operations.setdefault("task_receipts", p4_receipts.get("receipts", p4_receipts.get("results", [])))
        if "heartbeat" not in operations:
            heartbeat=optional["p4_heartbeat"][0]
            if not heartbeat:
                is_open=TradingCalendar().is_open(generated_at.date())
                status=("IDLE_NON_TRADING_DAY" if is_open is False else
                        "AWAITING_FIRST_WINDOW" if generated_at.timetz().replace(tzinfo=None) < datetime.strptime("09:25","%H:%M").time()
                        else "MISSING")
                heartbeat={"status":status,"recorded_at":generated_at.isoformat(timespec="seconds"),
                           "schema_version":"p4-derived-heartbeat-v1","derived":True}
            operations["heartbeat"]=heartbeat
        operations.setdefault("cutover", optional["cutover_readiness"][0])
        authorization=optional["production_authorization"][0]
        if authorization.get("apply_allowed") is True:
            owners=authorization.get("owners",{})
            operations.setdefault("ownership",{"decision":owners.get("candidate_decision","P2"),
                "account_execution":owners.get("paper_account","P3"),
                "scheduler_notifications":owners.get("task_receipts","P4"),
                "dashboard":owners.get("dashboard","P5")})
            operations["cutover"]={"ready":True,"apply_allowed":False,"applied":True,
                "plan_id":authorization.get("authorization_id","")}
        evidence.setdefault("live_windows", optional["live_window_acceptance"][0])
        evidence.setdefault("strict_admission", optional["strict_model_admission"][0])
        evidence.setdefault("execution_result_count", len(p3_results.get("results", [])))
        source_issues = [{"severity": "ERROR" if a.status != "VALID" else "INFO",
                          "reason_code": f"SOURCE_{a.status}", "message": f"{a.name}: {a.error}"}
                         for a in artifacts if a.status != "VALID"]
        model = DashboardReadModelBuilder().build(
            generated_at=generated_at, production_status=production_status,
            morning=journal.get("morning"), confirmation=journal.get("confirmation"),
            market=self._market(context, journal), fund_flow=self._fund_flow(flow), ledger=ledger or {},
            task_receipts=operations.get("task_receipts", ()), heartbeat=operations.get("heartbeat"),
            alerts=operations.get("alerts", ()), evidence=evidence, ownership=operations.get("ownership"),
            cutover=operations.get("cutover"), source_artifacts=[a.__dict__ for a in artifacts],
            source_issues=source_issues)
        return model
