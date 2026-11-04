#!/usr/bin/env bash
# Regression, then varied geometry with new seeds: policy comparison, margin sweep, long ADR run.
# Job fields: policy gain n seed crossTrackKm marginDb passes part
set -euo pipefail
mkdir -p results
JOBS=$(( $(nproc) > 1 ? $(nproc) - 1 : 1 ))
run_one() {
  results/bin/leo_policies --policy="$1" --gainDb="$2" --nDevices="$3" --RngRun="$4" --windowPhase=1 \
    --crossTrackKm="$5" --marginDb="$6" --passes="$7" | sed "s/^RUN /RUN part=$8 /"
}
export -f run_one
{
  # G1: regression at zero offset, parent seeds.
  for g in 5 10; do
    for policy in 0 2 3 4 6; do
      for seed in 1 2 3 4 5; do
        echo "$policy $g 100 $seed 0 3 20 regress"
      done
    done
  done
  # C: long run.
  for n in 100 500; do
    for g in 5 10; do
      for policy in 0 1 3; do
        for seed in 6 7 8 9 10; do
          echo "$policy $g $n $seed 1500 3 100 long"
        done
      done
    done
  done
  # B: margin sweep.
  for n in 100 500 2000; do
    for g in 5 10; do
      for margin in 0 1 2 3 5; do
        for policy in 2 3 4; do
          for seed in 6 7 8 9 10; do
            echo "$policy $g $n $seed 1500 $margin 20 margin"
          done
        done
      done
    done
  done
  # A: policy comparison, largest networks last.
  for n in 100 500 2000 5000; do
    for g in 5 10; do
      for policy in 0 2 3 4 6; do
        for seed in 6 7 8 9 10; do
          echo "$policy $g $n $seed 1500 3 20 compare"
        done
      done
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2" "$3" "$4" "$5" "$6" "$7"' | tee results/runs.txt
echo "SUMMARY"
python3 scripts/summarize.py results/runs.txt | tee results/summary.txt
