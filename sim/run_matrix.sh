#!/usr/bin/env bash
# Measured SF12 Doppler limit: repeats the sensitivity, latitude and link-only tests with the limit
# from flight and laboratory data. Seeds 16-20 choose margins; seeds 21-25 test them.
# Job fields: policy gain n seed margin rxSet scintDb dopplerLimits part
set -euo pipefail
mkdir -p results
JOBS=$(( $(nproc) > 1 ? $(nproc) - 1 : 1 ))
run_one() {
  results/bin/leo_policies --minElevationDeg=20 --policy="$1" --gainDb="$2" --nDevices="$3" --RngRun="$4" \
    --windowPhase=1 --crossTrackKm=-1 --marginDb="$5" --passes=20 --channelMode=1 --rxSet="$6" \
    --scintDb="$7" --dopplerLimits="$8" | sed "s/^RUN /RUN part=$9 /"
}
export -f run_one
{
  # G1: the old limits reproduce the parent results.
  for seed in 16 17 18 19 20; do
    for g in 5 10; do
      echo "3 $g 100 $seed -1 1 7.69 0 regress"
      echo "2 $g 100 $seed 0 1 7.69 0 regress"
      echo "0 $g 100 $seed 3 1 7.69 0 regress"
    done
  done
  for part_seeds in "search 16 17 18 19 20" "confirm 21 22 23 24 25"; do
    set -- $part_seeds
    part=$1
    shift
    for rx in 1 2; do
      for scint in 7.69 0; do
        for seed in "$@"; do
          for g in 5 10; do
            for n in 100 2000 5000; do
              for margin in -2 -1 0 1 3; do
                echo "3 $g $n $seed $margin $rx $scint 1 $part"
                echo "2 $g $n $seed $margin $rx $scint 1 $part"
              done
              echo "0 $g $n $seed 3 $rx $scint 1 $part"
            done
          done
        done
      done
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8"' | tee results/runs.txt
echo "SUMMARY"
python3 scripts/summarize.py results/runs.txt | tee results/summary.txt
