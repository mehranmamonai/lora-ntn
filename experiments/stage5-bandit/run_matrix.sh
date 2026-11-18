#!/usr/bin/env bash
# Stage 5: contextual bandit choosing an SF12 Doppler-rate threshold from gateway data.
# Phase 1 trains on seeds 16-20 (C3, R1-R4) with a random threshold each pass; phase 2 tests the learned
# Q-table on seeds 21-30 under C1-C3 and R1-R4. Comparators come from earlier runs (see summarize.py).
set -euo pipefail
mkdir -p results/cases
JOBS=$(( $(nproc) > 1 ? $(nproc) - 1 : 1 ))
# Job fields: policy collision mode n scint margin gain seed kind part
#   kind: none (link-only), frozen (constant controller, no threshold), train (random arm), test (Q-table)
run_one() {
  local pol=$1 col=$2 mode=$3 n=$4 scint=$5 margin=$6 gain=$7 seed=$8 kind=$9 part=${10}
  local id="$part-pol$pol-c$col-m$mode-n$n-s$scint-g$gain-seed$seed-$kind"
  local extra=()
  case "$kind" in
    frozen) extra+=("--controller=python3,scripts/controller.py,--p,1,--margin,$margin" "--sf12RateRule=1") ;;
    train) extra+=("--controller=python3,scripts/controller.py,--mode,bandit,--p,1,--margin,$margin,--train-seed,$((seed * 7919 + mode * 131 + n + gain * 17 + col))"
                   "--sf12RateRule=1" "--exploreProb=0.1") ;;
    test) extra+=("--controller=python3,scripts/controller.py,--mode,bandit,--p,1,--margin,$margin,--qtable,results/qtable.json"
                  "--sf12RateRule=1" "--exploreProb=0.1") ;;
  esac
  results/bin/leo_policies --minElevationDeg=20 --policy="$pol" --gainDb="$gain" --nDevices="$n" --RngRun="$seed" \
    --windowPhase=1 --crossTrackKm=-1 --marginDb="$margin" --passes=20 --channelMode=1 --rxSet=1 \
    --scintDb="$scint" --dopplerLimits="$mode" --txProb=1 --collision="$col" "${extra[@]}" > "results/cases/$id.log"
  grep '^RUN ' "results/cases/$id.log" | sed "s/^RUN /RUN part=$part case=$id kind=$kind /"
}
export -f run_one
SCENS=("7.69 -2" "0 0")
{
  # ML0: link-only against the controlled policy with no threshold and no exploration.
  for col in 1 2 3; do
    for n in 100 2000; do
      echo "2 $col 1 $n 7.69 -2 5 21 none z0"
      echo "7 $col 1 $n 7.69 -2 5 21 frozen z0"
    done
  done
  # Phase 1 training.
  for seed in 16 17 18 19 20; do
    for scen in "${SCENS[@]}"; do
      read -r scint lock <<< "$scen"
      for gain in 5 10; do
        for mode in 1 5 2 3; do
          for n in 500 2000 5000; do
            echo "7 3 $mode $n $scint $lock $gain $seed train train"
          done
        done
      done
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$9"' | tee results/runs.txt
echo "TRAIN"
(cd scripts && python3 train_bandit.py ../results/cases ../results/qtable.json) | tee results/training.txt
{
  # Phase 2 test on unused seeds.
  for seed in 21 22 23 24 25 26 27 28 29 30; do
    for col in 1 2 3; do
      for mode in 1 5 2 3; do
        for scen in "${SCENS[@]}"; do
          read -r scint lock <<< "$scen"
          for gain in 5 10; do
            for n in 100 500 2000 5000; do
              echo "7 $col $mode $n $scint $lock $gain $seed test test"
            done
          done
        done
      done
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$9"' | tee -a results/runs.txt
echo "SUMMARY"
P="$HOME/lora-ntn-runs"
python3 scripts/summarize.py results/runs.txt \
  "$P/a7feb12a-f7ecea4/repo/results/runs.txt" "$P/17491a20-b34999c/repo/results/runs.txt" \
  "$P/5fff0738-26c488b/repo/results/runs.txt" "$P/8a1478bb-d9f6ec6/repo/results/runs.txt" \
  "$P/ae2d1534-a903e7d/repo/results/runs.txt" "$P/f1c0467c-436368e/repo/results/runs.txt" | tee results/summary.txt
