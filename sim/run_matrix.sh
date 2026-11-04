#!/usr/bin/env bash
# Random transmit timing across all sizes, plus fixed timing at N=100,500 for comparison.
set -euo pipefail
mkdir -p results
JOBS=$(( $(nproc) > 1 ? $(nproc) - 1 : 1 ))
run_one() {
  results/bin/leo_policies --policy="$1" --gainDb="$2" --nDevices="$3" --RngRun="$4" --randomPhase="$5"
}
export -f run_one
{
  for n in 100 500; do
    for g in 5 10; do
      for policy in 0 2 3 4; do
        for seed in 1 2 3 4 5; do
          echo "$policy $g $n $seed 0"
        done
      done
    done
  done
  for n in 100 500 2000 5000; do
    for g in 5 10; do
      for policy in 0 1 2 3 4; do
        for seed in 1 2 3 4 5; do
          echo "$policy $g $n $seed 1"
        done
      done
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2" "$3" "$4"' | tee results/runs.txt
echo "SUMMARY"
python3 scripts/summarize.py results/runs.txt | tee results/summary.txt
