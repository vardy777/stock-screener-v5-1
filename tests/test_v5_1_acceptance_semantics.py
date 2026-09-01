from v5_1.production_read_model import StageOutcomeFactV51

def fact(outcome,intents,results,rejections):
    return StageOutcomeFactV51("2026-08-28","execution",outcome,("v5.1-baseline-0935-v1",),"2026-08-28T14:50:45+08:00","TEST","V51_TEST",False,intents,results,rejections,tuple(f"i{x}" for x in range(intents)),tuple(f"a{x}" for x in range(intents)))

def test_execution_outcome_semantics_are_not_active_flat_when_intent_exists():
    assert fact("ACTIVE_FLAT",0,0,0).outcome=="ACTIVE_FLAT"
    assert fact("ALL_FILLED",1,1,0).outcome=="ALL_FILLED"
    assert fact("NO_STRICT_FILL",1,0,1).outcome=="NO_STRICT_FILL"
    assert fact("EXECUTION_REJECTED",1,0,1).outcome=="EXECUTION_REJECTED"
    assert fact("PARTIAL_FILL",2,1,1).outcome=="PARTIAL_FILL"
