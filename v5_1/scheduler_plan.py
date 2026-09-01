"""Report-only V5 to V5.1 scheduler migration plan. Never registers tasks."""
from __future__ import annotations
import json
from pathlib import Path

CHANGES=(
 {"task":"V51-Shadow-Master-Recovery","old":"none","new":"08:10/08:30/08:50/09:05/09:20 idempotent Master recovery attempts","writer":"v5.1-shadow","stage":"preflight","enabled":False},
 {"task":"V51-Shadow-Market-Observation","old":"none","new":"09:30:00 daily status + dual-source observation","writer":"v5.1-shadow","stage":"morning_observation","enabled":False},
 {"task":"V51-Shadow-Morning-Pool","old":"09:25:05","new":"09:35:00","writer":"v5.1-shadow","stage":"morning_pool","enabled":False},
 {"task":"Morning-Facts-Daily","old":"09:25:05","new":"09:35:00","writer":"v5.1"},
 {"task":"Morning-Push-Daily","old":"09:25:50","new":"09:35:45","writer":"v5.1"},
 {"task":"Feature-Freeze-Daily","old":"14:49:00 baseline only","new":"14:49:00 shared freeze for baseline and CloseScan","writer":"v5.1"},
 {"task":"Confirmation-Daily","old":"14:50 baseline","new":"14:50 baseline confirmation + independent CloseScan selection","writer":"v5.1"},
 {"task":"Paper-Buy-Daily","old":"14:50:40 baseline","new":"14:50:40 shared execution capture; two isolated ledgers","writer":"v5.1"},
 {"task":"Paper-Sell-Daily","old":"09:30:10","new":"09:30:10 post-open execution capture; two isolated ledgers","writer":"v5.1"},
)
def build():return {"schema_version":"v5.1-scheduler-migration-plan-v2","report_only":True,"authorized":False,"registers_tasks":False,"all_definitions_disabled":True,"duplicate_business_writers_allowed":False,"changes":[{**row,"enabled":False} for row in CHANGES],"dependencies":{"baseline_confirmation":["daily_tradability","morning_pool_0935","feature_freeze_1449"],"closescan_selection":["daily_tradability","feature_freeze_1449"],"paper_buy":["strategy_selection","post_decision_execution_snapshot"]}}
if __name__=="__main__":print(json.dumps(build(),ensure_ascii=False,indent=2))
