#!/usr/bin/env bash
# Export today and the preceding six calendar days to a dated CSV file.
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python="$project_dir/.venv/bin/python"

if [[ ! -x "$python" ]]; then
  echo "Virtual environment not found. Run: python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 1
fi

from_date="$(date -d '6 days ago' +%F)"
to_date="$(date +%F)"
from_stamp="$(date -d '6 days ago' +%y%m%d)"
to_stamp="$(date +%y%m%d)"
output="$project_dir/exports/polar_activities_${from_stamp}-${to_stamp}.csv"

mkdir -p "$project_dir/exports"
export PYTHONPATH="$project_dir/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$python" -m polar_mcp.polar_export \
  --from "$from_date" \
  --to "$to_date" \
  --output "$output"
