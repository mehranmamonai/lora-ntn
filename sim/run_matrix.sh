#!/usr/bin/env bash
# Link-only comparison at negative margins, primary scenario only: sensitivity set 1, 7.69 dB
# scintillation. Seeds 16-20 choose margins; seeds 21-25 test them.
# Job fields: policy gain n seed margin part
set -euo pipefail
mkdir -p results
JOBS=$(( $(nproc) > 1 ? $(nproc) - 1 : 1 ))
run_one() {
  results/bin/leo_policies --minElevationDeg=20 --policy="$1" --gainDb="$2" --nDevices="$3" --RngRun="$4" \
    --windowPhase=1 --crossTrackKm=-1 --marginDb="$5" --passes=20 --channelMode=1 --rxSet=1 \
    --scintDb=7.69 | sed "s/^RUN /RUN part=$6 /"
}
export -f run_one
{
  for part_seeds in "search 16 17 18 19 20" "confirm 21 22 23 24 25"; do
    set -- $part_seeds
    part=$1
    shift
    for seed in "$@"; do
      for g in 5 10; do
        for n in 100 2000 5000; do
          for margin in -4 -3 -2 -1 0; do
            echo "3 $g $n $seed $margin $part"
            echo "2 $g $n $seed $margin $part"
          done
          echo "0 $g $n $seed 3 $part"
        done
      done
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2" "$3" "$4" "$5"' | tee results/runs.txt
echo "SUMMARY"
python3 scripts/summarize.py results/runs.txt | tee results/summary.txt
