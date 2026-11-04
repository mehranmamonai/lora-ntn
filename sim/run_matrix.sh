#!/usr/bin/env bash
# Baseline matrix: stock ADR (HistoryRange=20) at two uplink periods, five seeds each.
set -euo pipefail
OUT=results/csv
mkdir -p "$OUT"
JOBS=$(( $(nproc) > 1 ? $(nproc) - 1 : 1 ))
run_one() {
  results/bin/adr_baseline --nDevices=100 --periodS="$1" --nPeriods=30 --HistoryRange=20 \
    --RngRun="$2" --csv="$OUT/period$1_hist20_seed$2.csv"
}
export -f run_one
export OUT
for period in 300 1200; do
  for seed in 1 2 3 4 5; do
    echo "$period $seed"
  done
done | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1"'
echo "SUMMARY"
python3 scripts/summarize.py "$OUT"
