#!/usr/bin/env bash
# Re-review (Rev 1) items N-0, N-1, N-3.
#   check : link-only and a fixed 90-deg cut-off on seed 21; must match exactly.
#   fixed : static SF12 cut-off 40 and 50 deg (every device, no beacons, no exploration) in all 192
#           scenarios on seeds 21-30; low-latitude 5 dBi R1/R2 already exist in 373b90c7 and are skipped.
#   cvtune: fixed cut-offs 20-80 deg on tuning seeds 16-20, low latitude 5 dBi, C1-C3, R1 R2, to choose
#           the cut-off per scenario without touching the test seeds.
#   truth : link-only, C3, low latitude 5 dBi, R1 and R3, N=500 and 2000, seeds 21-25, logging SF12 packets
#           sent, Doppler-lost and received per elevation bin.
set -euo pipefail
mkdir -p results/cases
JOBS=$(( $(nproc) > 1 ? $(nproc) - 1 : 1 ))
# Job fields: part policy collision mode n scint margin gain seed theta
run_one() {
  local part=$1 pol=$2 col=$3 mode=$4 n=$5 scint=$6 margin=$7 gain=$8 seed=$9 theta=${10}
  local id="$part-pol$pol-c$col-m$mode-n$n-s$scint-g$gain-seed$seed-t$theta"
  local extra=()
  [ "$pol" = 7 ] && extra+=("--thetaDeg=$theta" "--beacons=0" "--exploreProb=0")
  results/bin/leo_policies --minElevationDeg=20 --policy="$pol" --gainDb="$gain" --nDevices="$n" --RngRun="$seed" \
    --windowPhase=1 --crossTrackKm=-1 --marginDb="$margin" --passes=20 --channelMode=1 --rxSet=1 \
    --scintDb="$scint" --dopplerLimits="$mode" --txProb=1 --collision="$col" "${extra[@]}" > "results/cases/$id.log"
  grep '^RUN ' "results/cases/$id.log" | sed "s/^RUN /RUN part=$part case=$id /"
}
export -f run_one
{
  for col in 1 3; do
    for n in 100 2000; do
      echo "check 2 $col 1 $n 7.69 -2 5 21 90"
      echo "check 7 $col 1 $n 7.69 -2 5 21 90"
    done
  done
  for seed in 21 22 23 24 25; do
    for mode in 1 2; do
      for n in 500 2000; do echo "truth 2 3 $mode $n 7.69 -2 5 $seed 90"; done
    done
  done
  for seed in 16 17 18 19 20; do
    for col in 1 2 3; do
      for mode in 1 5; do
        for n in 100 500 2000 5000; do
          for theta in 20 30 40 50 60 70 80; do echo "cvtune 7 $col $mode $n 7.69 -2 5 $seed $theta"; done
        done
      done
    done
  done
  for seed in 21 22 23 24 25 26 27 28 29 30; do
    for col in 1 2 3; do
      for mode in 1 5 2 3; do
        for scen in "7.69 -2" "0 0"; do
          read -r scint lock <<< "$scen"
          for gain in 5 10; do
            if [ "$scint" = 7.69 ] && [ "$gain" = 5 ] && { [ "$mode" = 1 ] || [ "$mode" = 5 ]; }; then continue; fi
            for n in 100 500 2000 5000; do
              for theta in 40 50; do echo "fixed 7 $col $mode $n $scint $lock $gain $seed $theta"; done
            done
          done
        done
      done
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$9"' | tee results/runs.txt
echo "SUMMARY"
python3 scripts/summarize.py experiments results/runs.txt | tee results/summary.txt
