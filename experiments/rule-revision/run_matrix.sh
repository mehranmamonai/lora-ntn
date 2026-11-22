#!/usr/bin/env bash
# Revised SF12 cut-off rule. The rule sets the cut-off at the first 10-degree bin b >= min-bin whose
# SF12 share falls below share-frac times the share in the bins below min-bin (old rule: 0.5, 2).
# Phase 1 tunes (share-frac, min-bin) on seeds 16-20; phase 2 tests the choice on seeds 21-30 in all
# 192 scenarios. Controller otherwise as in ae2d1534 (beacons, exploration 0.1, no load rule).
set -euo pipefail
mkdir -p results/cases
JOBS=$(( $(nproc) > 1 ? $(nproc) - 1 : 1 ))
# Job fields: part policy collision mode n scint margin gain seed frac minbin
run_one() {
  local part=$1 pol=$2 col=$3 mode=$4 n=$5 scint=$6 margin=$7 gain=$8 seed=$9 frac=${10} minbin=${11}
  local id="$part-pol$pol-c$col-m$mode-n$n-s$scint-g$gain-seed$seed-f$frac-b$minbin"
  local extra=()
  if [ "$pol" = 7 ]; then
    extra+=("--exploreProb=0.1"
            "--controller=python3,scripts/controller.py,--mode,adaptive,--p,1,--margin,$margin,--k,0,--adapt-margin,0,--h,0,--share-frac,$frac,--min-bin,$minbin")
  fi
  results/bin/leo_policies --minElevationDeg=20 --policy="$pol" --gainDb="$gain" --nDevices="$n" --RngRun="$seed" \
    --windowPhase=1 --crossTrackKm=-1 --marginDb="$margin" --passes=20 --channelMode=1 --rxSet=1 \
    --scintDb="$scint" --dopplerLimits="$mode" --txProb=1 --collision="$col" "${extra[@]}" > "results/cases/$id.log"
  grep '^RUN ' "results/cases/$id.log" | sed "s/^RUN /RUN part=$part case=$id frac=$frac minbin=$minbin /"
}
export -f run_one
COMBOS=("0.5 2" "0.6 2" "0.7 2" "0.8 2" "0.9 2" "0.5 1" "0.6 1" "0.7 1" "0.8 1" "0.9 1")
{
  # Regression: the old rule must reproduce ae2d1534 exactly.
  for n in 100 2000; do echo "regress 7 3 1 $n 7.69 -2 5 21 0.5 2"; done
  for seed in 16 17 18 19 20; do
    # Target: low latitude, 5 dBi, R1 R2 R3 (C3).
    for mode in 1 5 2; do
      for n in 100 500 2000 5000; do
        echo "tune 2 3 $mode $n 7.69 -2 5 $seed none none"
        for c in "${COMBOS[@]}"; do read -r f b <<< "$c"; echo "tune 7 3 $mode $n 7.69 -2 5 $seed $f $b"; done
      done
    done
    # Harm check where the old rule never acted: mid-latitude 5 dBi and low latitude 10 dBi (R1, C3).
    for scen in "0 0 5" "7.69 -2 10"; do
      read -r scint lock gain <<< "$scen"
      for n in 500 5000; do
        echo "tune 2 3 1 $n $scint $lock $gain $seed none none"
        for c in "${COMBOS[@]}"; do read -r f b <<< "$c"; echo "tune 7 3 1 $n $scint $lock $gain $seed $f $b"; done
      done
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$9" "${10}"' | tee results/runs.txt
echo "CHOOSE"
python3 scripts/summarize.py choose results/runs.txt | tee results/choice.txt
read -r F B < <(grep '^CHOSEN' results/choice.txt | sed -E 's/.*frac=([^ ]+) minbin=([^ ]+).*/\1 \2/')
{
  for seed in 21 22 23 24 25 26 27 28 29 30; do
    for col in 1 2 3; do
      for mode in 1 5 2 3; do
        for scen in "7.69 -2" "0 0"; do
          read -r scint lock <<< "$scen"
          for gain in 5 10; do
            for n in 100 500 2000 5000; do
              echo "test 7 $col $mode $n $scint $lock $gain $seed $F $B"
            done
          done
        done
      done
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$9" "${10}"' | tee -a results/runs.txt
echo "SUMMARY"
python3 scripts/summarize.py final results/runs.txt experiments | tee results/summary.txt
