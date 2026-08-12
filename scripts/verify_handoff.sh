#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -x .venv/bin/python ]]; then
  echo "Missing .venv. Follow the setup steps in HANDOFF.md first." >&2
  exit 2
fi

echo "1. Running automated tests"
.venv/bin/pytest -q

echo
echo "2. Validating the synthetic sample feed"
.venv/bin/python - <<'PY'
from pathlib import Path

from pcqc.io import read_sales_text

sales = read_sales_text(Path("examples/sample-sales.csv").read_text())
assert len(sales) == 3
assert {sale.identifier for sale in sales} == {
    "demo-regular",
    "demo-condition",
    "demo-bundle",
}
print("Synthetic sample: 3 valid rows")
PY

echo
echo "3. Verifying active policy metadata"
.venv/bin/python - <<'PY'
import json
from pathlib import Path

from pcqc.version import REVIEW_POLICY_VERSION

policy = json.loads(Path("config/review-policy.json").read_text())
assert policy["version"] == REVIEW_POLICY_VERSION
assert policy["model_output"]["confidence_allowed"] is False
assert policy["model_output"]["routing_allowed"] is False
print(f"Active policy: {REVIEW_POLICY_VERSION}")
PY

echo
echo "Handoff verification complete. No external API or model calls were made."
