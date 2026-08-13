import json
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest
from v5.ownership import load,require
from v5.core import ContractViolation
def test_default_ownership_prevents_v5_paper_writer_and_authorized_contract_is_exclusive():
 with TemporaryDirectory() as d:
  path=Path(d)/"ownership.json";assert load(path)["paper_writer"]=="v4"
  with pytest.raises(ContractViolation):require(path,"paper_writer")
  path.write_text(json.dumps({"schema_version":"v5-ownership-v1","paper_writer":"v5","scheduler":"v5","dashboard":"v5","notifications":"v5","authorized":True}),encoding="utf-8");assert require(path,"paper_writer")["paper_writer"]=="v5"
