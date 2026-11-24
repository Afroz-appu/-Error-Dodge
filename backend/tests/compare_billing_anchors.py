"""Reproduce the frozen billing-anchor comparison."""
import argparse
import hashlib
import json
from pathlib import Path

from app.context_v4 import detect_v4
from app.reliability import detect_contextual
from app.schema import LookupArgs, ToolCall
from app.workflow import REFUND

here = Path(__file__).parent
detector_path = here.parent / "app" / "context_v4.py"
expected = "21b2db8925030f540217db75b8864a4b64a6b7e7541aeba7a9e9352de384ac43"
assert hashlib.sha256(detector_path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == expected or \
    hashlib.sha256(detector_path.read_bytes()).hexdigest() == expected
parser = argparse.ArgumentParser()
parser.add_argument("--post-fix", action="store_true")
source = here / "data" / ("billing_anchor_post_fix.json" if parser.parse_args().post_fix else "billing_anchor_v4.json")
raw = source.read_bytes()
fixtures = json.loads(raw.decode("utf-8-sig"))
calls = [ToolCall(id="policy", tool="lookup_policy", arguments=LookupArgs(topic="refund"), output=REFUND)]
results = [
    {**row, **{
        key: "policy_conflict" in {finding.code for finding in fn(row["answer"], calls)}
        for key, fn in (("v3", detect_contextual), ("v4", detect_v4))
    }}
    for row in fixtures
]
print(json.dumps({"detector_sha256": expected, "dataset_sha256": hashlib.sha256(raw).hexdigest(),
                  "rows": results}, indent=2))
