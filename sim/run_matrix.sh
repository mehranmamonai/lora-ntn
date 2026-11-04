#!/usr/bin/env bash
# Phase 3 checks: analytic Table 5 sweep, then an ns-3 packet-level pass per SF and seed.
set -euo pipefail
mkdir -p results/pass
results/bin/doppler_table5 | tee results/table5.txt
JOBS=$(( $(nproc) > 1 ? $(nproc) - 1 : 1 ))
run_one() {
  results/bin/doppler_pass --sf="$1" --RngRun="$2" --csv="results/pass/sf$1_seed$2.csv"
}
export -f run_one
for sf in 7 8 9 10 11 12; do
  for seed in 1 2 3; do
    echo "$sf $seed"
  done
done | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1"' | tee results/passes.txt
echo "SUMMARY"
python3 scripts/summarize.py results/table5.txt results/passes.txt results/pass
