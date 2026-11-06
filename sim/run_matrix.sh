#!/usr/bin/env bash
# Upper bound on load control across Doppler readings. Sensitivity set 1. Seeds 16-20 choose the
# transmit probability; seeds 21-25 test it. Margins are the locks from experiment 85386008.
# Job fields: policy gain n seed margin scintDb dopplerLimits txProb part
set -euo pipefail
mkdir -p results
JOBS=$(( $(nproc) > 1 ? $(nproc) - 1 : 1 ))
run_one() {
  results/bin/leo_policies --minElevationDeg=20 --policy="$1" --gainDb="$2" --nDevices="$3" --RngRun="$4" \
    --windowPhase=1 --crossTrackKm=-1 --marginDb="$5" --passes=20 --channelMode=1 --rxSet=1 \
    --scintDb="$6" --dopplerLimits="$7" --txProb="$8" | sed "s/^RUN /RUN part=$9 /"
}
export -f run_one
{
  for part_seeds in "search 16 17 18 19 20" "confirm 21 22 23 24 25"; do
    set -- $part_seeds
    part=$1
    shift
    for scen in "7.69 -2" "0 0"; do
      set -- $scen "$@"
      scint=$1
      margin=$2
      shift 2
      for seed in "$@"; do
        for g in 5 10; do
          for n in 2000 5000; do
            for p in 1 0.5 0.25 0.125 0.0625; do
              for mode in 1 5 2 3; do
                echo "2 $g $n $seed $margin $scint $mode $p $part"
              done
              for mode in 1 5; do
                echo "3 $g $n $seed $margin $scint $mode $p $part"
              done
            done
          done
        done
      done
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8"' | tee results/runs.txt
echo "SUMMARY"
python3 scripts/summarize.py results/runs.txt | tee results/summary.txt
