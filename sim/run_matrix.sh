#!/usr/bin/env bash
# Sourced receiver sensitivity and latitude. All runs use the TR 38.811 rural channel,
# footprint-derived scenario, and 20 deg minimum elevation.
# Job fields: policy gain n seed margin rxSet scintDb part
set -euo pipefail
mkdir -p results
JOBS=$(( $(nproc) > 1 ? $(nproc) - 1 : 1 ))
run_one() {
  results/bin/leo_policies --minElevationDeg=20 --policy="$1" --gainDb="$2" --nDevices="$3" --RngRun="$4" \
    --windowPhase=1 --crossTrackKm=-1 --marginDb="$5" --passes=20 --channelMode=1 --rxSet="$6" \
    --scintDb="$7" | sed "s/^RUN /RUN part=$8 /"
}
export -f run_one
{
  # M1: regression against the baseline lock.
  for g in 5 10; do
    for seed in 11 12 13 14 15; do
      echo "3 $g 100 $seed 0 0 7.69 regress"
    done
  done
  for rx in 1 2; do
    for scint in 7.69 0; do
      for g in 5 10; do
        for seed in 16 17 18 19 20; do
          for n in 100 2000; do
            for margin in -1 0 1 2 3; do
              echo "3 $g $n $seed $margin $rx $scint main"
            done
            for margin in 0 1 3; do
              echo "2 $g $n $seed $margin $rx $scint main"
            done
          done
          for n in 100 2000 5000; do
            echo "0 $g $n $seed 3 $rx $scint main"
          done
          for margin in 0 1 3; do
            echo "3 $g 5000 $seed $margin $rx $scint main"
          done
        done
      done
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2" "$3" "$4" "$5" "$6" "$7"' | tee results/runs.txt
echo "SUMMARY"
python3 scripts/summarize.py results/runs.txt | tee results/summary.txt
