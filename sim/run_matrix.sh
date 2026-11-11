#!/usr/bin/env bash
# Does beacon reach limit the Stage 4 controller? The Stage 4 revision controller (Doppler cut-off,
# H off, eps 0.1) with settings applied to every device at each pass boundary and beacons off.
# Low latitude only, seeds 21-30, compared with ae2d1534 (beacon delivery) on the same seeds.
set -euo pipefail
mkdir -p results/cases
JOBS=$(( $(nproc) > 1 ? $(nproc) - 1 : 1 ))
# Job fields: collision mode n gain seed
run_one() {
  local col=$1 mode=$2 n=$3 gain=$4 seed=$5
  local id="instant-c$col-m$mode-n$n-g$gain-seed$seed"
  results/bin/leo_policies --minElevationDeg=20 --policy=7 --gainDb="$gain" --nDevices="$n" --RngRun="$seed" \
    --windowPhase=1 --crossTrackKm=-1 --marginDb=-2 --passes=20 --channelMode=1 --rxSet=1 \
    --scintDb=7.69 --dopplerLimits="$mode" --txProb=1 --collision="$col" --exploreProb=0.1 \
    --beacons=0 --instantSettings=1 \
    "--controller=python3,scripts/controller.py,--mode,adaptive,--p,1,--margin,-2,--k,0,--adapt-margin,0,--h,0" \
    > "results/cases/$id.log"
  grep '^RUN ' "results/cases/$id.log" | sed "s/^RUN /RUN part=instant case=$id /"
}
export -f run_one
{
  for seed in 21 22 23 24 25 26 27 28 29 30; do
    for col in 1 2 3; do
      for mode in 1 5 2 3; do
        for gain in 5 10; do
          for n in 100 500 2000 5000; do
            echo "$col $mode $n $gain $seed"
          done
        done
      done
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2" "$3" "$4"' | tee results/runs.txt
echo "SUMMARY"
python3 scripts/summarize.py results/runs.txt "$HOME/lora-ntn-runs/ae2d1534-a903e7d/repo/results/runs.txt" \
  "$HOME/lora-ntn-runs/f1c0467c-436368e/repo/results/runs.txt" | tee results/summary.txt
