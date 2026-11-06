#!/usr/bin/env bash
# Efficiency upper bound across load and margin. Link-only, sensitivity set 1. Seeds 16-20 choose;
# seeds 21-25 test. N=2000, 5000 at the locked margin are reused from experiment 17491a20.
# Job fields: gain n seed margin scintDb dopplerLimits txProb part
set -euo pipefail
mkdir -p results
JOBS=$(( $(nproc) > 1 ? $(nproc) - 1 : 1 ))
PARENT_RUNS="$HOME/lora-ntn-runs/17491a20-b34999c/repo/results/runs.txt"
run_one() {
  results/bin/leo_policies --minElevationDeg=20 --policy=2 --gainDb="$1" --nDevices="$2" --RngRun="$3" \
    --windowPhase=1 --crossTrackKm=-1 --marginDb="$4" --passes=20 --channelMode=1 --rxSet=1 \
    --scintDb="$5" --dopplerLimits="$6" --txProb="$7" | sed "s/^RUN /RUN part=$8 /"
}
export -f run_one
{
  # K1: exact repeats of cases from 17491a20.
  for p in 1 0.5; do
    for g in 5 10; do
      echo "$g 2000 21 -2 7.69 1 $p regress"
    done
  done
  echo "5 5000 21 0 0 1 0.5 regress"
  echo "10 5000 21 0 0 3 1 regress"
  for part_seeds in "search 16 17 18 19 20" "confirm 21 22 23 24 25"; do
    set -- $part_seeds
    part=$1
    shift
    for seed in "$@"; do
      for g in 5 10; do
        for scen in "7.69 -2" "0 0"; do
          read -r scint lock <<< "$scen"
          # A: light loads at the locked margin.
          for n in 100 500; do
            for p in 1 0.5 0.25 0.125 0.0625; do
              for mode in 1 5 2 3; do
                echo "$g $n $seed $lock $scint $mode $p $part"
              done
            done
          done
          # B: margins either side of the lock, readings that bracket the SF12 hole.
          for n in 2000 5000; do
            for margin in $((lock - 1)) $((lock + 1)); do
              for p in 1 0.5 0.25; do
                for mode in 1 2; do
                  echo "$g $n $seed $margin $scint $mode $p $part"
                done
              done
            done
          done
        done
      done
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2" "$3" "$4" "$5" "$6" "$7"' | tee results/runs.txt
echo "SUMMARY"
python3 scripts/summarize.py results/runs.txt "$PARENT_RUNS" | tee results/summary.txt
