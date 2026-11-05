#!/usr/bin/env bash
# Sensitivity of the elevation-aware lead to unmeasured Doppler limits. Primary scenario only:
# sensitivity set 1, 7.69 dB scintillation. Seeds 16-20 choose margins; seeds 21-25 test them.
# Job fields: policy gain n seed margin dopplerLimits part
set -euo pipefail
mkdir -p results
JOBS=$(( $(nproc) > 1 ? $(nproc) - 1 : 1 ))
run_one() {
  results/bin/leo_policies --minElevationDeg=20 --policy="$1" --gainDb="$2" --nDevices="$3" --RngRun="$4" \
    --windowPhase=1 --crossTrackKm=-1 --marginDb="$5" --passes=20 --channelMode=1 --rxSet=1 \
    --scintDb=7.69 --dopplerLimits="$6" | sed "s/^RUN /RUN part=$7 /"
}
export -f run_one
{
  for mode_gains in "1 5 10" "2 5 10" "3 10"; do
    set -- $mode_gains
    mode=$1
    shift
    for g in "$@"; do
      for seed in 16 17 18 19 20; do
        for n in 100 2000; do
          for margin in -4 -3 -2 -1 0; do
            echo "3 $g $n $seed $margin $mode search"
            echo "2 $g $n $seed $margin $mode search"
          done
        done
      done
      for seed in 21 22 23 24 25; do
        for n in 100 2000 5000; do
          for margin in -4 -3 -2 -1 0; do
            echo "3 $g $n $seed $margin $mode confirm"
            echo "2 $g $n $seed $margin $mode confirm"
          done
          echo "0 $g $n $seed 3 $mode confirm"
        done
      done
    done
  done
  # H6: with both assumptions relaxed the rule should have nothing left to gate.
  for g in 5 10; do
    for seed in 21 22 23 24 25; do
      echo "3 $g 100 $seed -2 4 check"
      echo "2 $g 100 $seed -2 4 check"
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2" "$3" "$4" "$5" "$6"' | tee results/runs.txt
echo "SUMMARY"
python3 scripts/summarize.py results/runs.txt | tee results/summary.txt
