#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SALES_CSV="${SALES_CSV:-}"

if [[ -z "$SALES_CSV" || ! -f "$SALES_CSV" ]]; then
  echo "Set SALES_CSV to an authorized PriceCharting sales export." >&2
  echo "Example: SALES_CSV=/path/to/PRICECHARTING.csv ./scripts/demo_poc.sh" >&2
  exit 2
fi

echo "1. Running automated tests"
.venv/bin/pytest -q

echo
echo "2. Verifying the superseded legacy holdout remains audit-locked"
.venv/bin/python - <<'PY'
import json
from pathlib import Path

lock = json.loads(
    Path("reports/evaluation-final/multimodal/final-evaluation-lock.json").read_text()
)
assert lock["complete"] is True
assert lock["successful_rows"] == lock["sample_count"] == 100
print(json.dumps(lock, indent=2, sort_keys=True))
PY

echo
echo "3. Rebuilding the offline paired comparison (no model/API calls)"
.venv/bin/pcqc compare-evaluations \
  --sales "$SALES_CSV" \
  --rules-dir reports/evaluation-validation/rules \
  --text-only-dir reports/evaluation-validation/text-only \
  --multimodal-dir reports/evaluation-validation/multimodal \
  --output-dir reports/evaluation-validation/comparison >/dev/null

echo
echo "4. Current v7 status and legacy evidence boundary"
.venv/bin/python - <<'PY'
import json
from pathlib import Path

summary = json.loads(Path("reports/executive-summary.json").read_text())
print(json.dumps(summary, indent=2, sort_keys=True))
PY

echo
echo "POC verification complete. This script does not call Gemini or run a v7 final holdout."
