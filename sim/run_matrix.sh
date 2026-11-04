#!/usr/bin/env bash
# Baseline lock. Job fields: policy gain n seed crossTrackKm marginDb passes part channelMode
# crossTrackKm=-1 uses the footprint radius at the 20 deg minimum elevation (Sant'Ana et al.).
set -euo pipefail
mkdir -p results
JOBS=$(( $(nproc) > 1 ? $(nproc) - 1 : 1 ))
NEW_SEEDS="11 12 13 14 15"
run_one() {
  local min=10
  if [ "$5" = "-1" ]; then min=20; fi
  results/bin/leo_policies --minElevationDeg="$min" --policy="$1" --gainDb="$2" --nDevices="$3" --RngRun="$4" --windowPhase=1 \
    --crossTrackKm="$5" --marginDb="$6" --passes="$7" --channelMode="$9" | sed "s/^RUN /RUN part=$8 /"
}
export -f run_one
{
  # L1: regression with the parent's seeds and no fading.
  for g in 5 10; do
    for policy in 0 2 3 4; do
      for seed in 6 7 8 9 10; do
        echo "$policy $g 100 $seed 1500 3 20 regress 0"
      done
    done
  done
  for g in 5 10; do
    for k in 0 1 2; do
      for seed in $NEW_SEEDS; do
        # Margin sweep for the rule and the LDRO variant.
        for n in 100 2000; do
          for margin in -2 -1 0 1 2 3; do
            for policy in 3 4; do
              echo "$policy $g $n $seed -1 $margin 20 sweep $k"
            done
          done
          # Link only, at three margins.
          for margin in 0 1 3; do
            echo "2 $g $n $seed -1 $margin 20 sweep $k"
          done
        done
        # Fixed SF12 has no margin to choose.
        for n in 100 500 2000 5000; do
          echo "0 $g $n $seed -1 3 20 sf12 $k"
        done
      done
    done
    for seed in $NEW_SEEDS; do
      # Long run on the TR 38.811 channel.
      for n in 100 500; do
        echo "1 $g $n $seed -1 3 100 long 1"
        for margin in 0 1 3; do
          echo "3 $g $n $seed -1 $margin 100 long 1"
        done
      done
      # Largest network on the TR 38.811 channel.
      for margin in -1 0 1 3; do
        echo "3 $g 5000 $seed -1 $margin 20 large 1"
      done
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8"' | tee results/runs.txt
echo "SUMMARY"
python3 scripts/summarize.py results/runs.txt | tee results/summary.txt
