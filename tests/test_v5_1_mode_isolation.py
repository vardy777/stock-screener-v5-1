from pathlib import Path
import pytest
from shared_core.core import ContractViolation
from v5_1.runtime import V51Runtime

class N: pass
class C: pass

@pytest.mark.parametrize("mode,relative",[("REPLAY","data"),("REPLAY","data/child"),("TEST","shadow_data/child")])
def test_non_live_modes_cannot_target_live_root_or_descendant(mode,relative):
    root=Path(__file__).parents[1]/"v5_1"/relative
    with pytest.raises(ContractViolation,match="cannot target production or shadow"):V51Runtime(root,mode=mode,provider=N(),master_provider=N(),calendar=C())

def test_replay_independent_root_is_allowed(tmp_path):
    assert V51Runtime(tmp_path/"replay",mode="REPLAY",provider=N(),master_provider=N(),calendar=C()).cohort=="V51_REPLAY"
