#!/usr/bin/env bash
# A/B-tested SF12 cut-off. Passes 0-3: the Stage 4 share rule. Passes 4-15: hill climb in 10-degree
# steps, comparing incumbent and challenger cut-offs within each pass between odd and even device
# addresses (groups swap every pass), by received packets. Passes 16-19: the winner for all devices. Until a challenger wins, the incumbent follows the share rule.
# Phase 1 tunes (comparison length L, acceptance margin delta) on seeds 16-20; link-only and old-rule
# tuning baselines come from b055586b (experiments/rule-revision). Phase 2 tests on seeds 21-30.
set -euo pipefail
mkdir -p results/cases
JOBS=$(( $(nproc) > 1 ? $(nproc) - 1 : 1 ))
# Job fields: part policy collision mode n scint margin gain seed ablen abdelta (ablen 0 = old rule)
run_one() {
  local part=$1 pol=$2 col=$3 mode=$4 n=$5 scint=$6 margin=$7 gain=$8 seed=$9 ablen=${10} abdelta=${11}
  local id="$part-pol$pol-c$col-m$mode-n$n-s$scint-g$gain-seed$seed-L$ablen-d$abdelta"
  local extra=("--exploreProb=0.1")
  if [ "$ablen" = 0 ]; then
    extra+=("--controller=python3,scripts/controller.py,--mode,adaptive,--p,1,--margin,$margin,--k,0,--adapt-margin,0,--h,0")
  else
    extra+=("--controller=python3,scripts/controller.py,--mode,abtest,--p,1,--margin,$margin,--k,0,--adapt-margin,0,--h,0,--ab-len,$ablen,--ab-delta,$abdelta")
  fi
  results/bin/leo_policies --minElevationDeg=20 --policy="$pol" --gainDb="$gain" --nDevices="$n" --RngRun="$seed" \
    --windowPhase=1 --crossTrackKm=-1 --marginDb="$margin" --passes=20 --channelMode=1 --rxSet=1 \
    --scintDb="$scint" --dopplerLimits="$mode" --txProb=1 --collision="$col" "${extra[@]}" > "results/cases/$id.log"
  grep '^RUN ' "results/cases/$id.log" | sed "s/^RUN /RUN part=$part case=$id ablen=$ablen abdelta=$abdelta /"
}
export -f run_one
COMBOS=("2 0" "2 0.02" "4 0" "4 0.02")
{
  # Regression: the old rule must reproduce ae2d1534 exactly.
  for n in 100 2000; do echo "regress 7 3 1 $n 7.69 -2 5 21 0 0"; done
  for seed in 16 17 18 19 20; do
    # Target: low latitude, 5 dBi, R1 R2 R3 (C3).
    for mode in 1 5 2; do
      for n in 100 500 2000 5000; do
        for c in "${COMBOS[@]}"; do read -r f b <<< "$c"; echo "tune 7 3 $mode $n 7.69 -2 5 $seed $f $b"; done
      done
    done
    # Harm check where the old rule never acted: mid-latitude 5 dBi and low latitude 10 dBi (R1, C3).
    for scen in "0 0 5" "7.69 -2 10"; do
      read -r scint lock gain <<< "$scen"
      for n in 500 5000; do
        for c in "${COMBOS[@]}"; do read -r f b <<< "$c"; echo "tune 7 3 1 $n $scint $lock $gain $seed $f $b"; done
      done
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$9" "${10}"' | tee results/runs.txt
echo "CHOOSE"
python3 scripts/summarize.py choose results/runs.txt experiments | tee results/choice.txt
read -r F B < <(grep '^CHOSEN' results/choice.txt | sed -E 's/.*ablen=([^ ]+) abdelta=([^ ]+).*/\1 \2/')
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
