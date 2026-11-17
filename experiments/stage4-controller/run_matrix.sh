#!/usr/bin/env bash
# Stage 4: rule-based controller for Doppler cut-off, margin and load, delivered by beacons.
# Phase 1 tunes on seeds 16-20 (collision C3, readings R1 and R3); phase 2 tests the chosen settings
# on seeds 21-25 under C1-C3 and R1-R4, with elevation-aware given the true reading as an oracle.
# Link-only p=1 baselines come from earlier runs on the VM (see summarize.py).
set -euo pipefail
mkdir -p results/cases
JOBS=$(( $(nproc) > 1 ? $(nproc) - 1 : 1 ))
# Job fields: policy collision mode n scint margin gain seed k adapt eps part
run_one() {
  local pol=$1 col=$2 mode=$3 n=$4 scint=$5 margin=$6 gain=$7 seed=$8 k=$9 adapt=${10} eps=${11} part=${12}
  local id="$part-pol$pol-c$col-m$mode-n$n-s$scint-g$gain-seed$seed-k$k-a$adapt-e$eps"
  local extra=()
  if [ "$pol" = 7 ]; then
    if [ "$k" = frozen ]; then
      extra+=("--controller=python3,scripts/controller.py,--p,1,--margin,$margin")
    else
      extra+=("--controller=python3,scripts/controller.py,--mode,adaptive,--p,1,--margin,$margin,--k,$k,--adapt-margin,$adapt")
      extra+=("--exploreProb=$eps")
    fi
  fi
  results/bin/leo_policies --minElevationDeg=20 --policy="$pol" --gainDb="$gain" --nDevices="$n" --RngRun="$seed" \
    --windowPhase=1 --crossTrackKm=-1 --marginDb="$margin" --passes=20 --channelMode=1 --rxSet=1 \
    --scintDb="$scint" --dopplerLimits="$mode" --txProb=1 --collision="$col" "${extra[@]}" > "results/cases/$id.log"
  grep '^RUN ' "results/cases/$id.log" | sed "s/^RUN /RUN part=$part case=$id k=$k adapt=$adapt /"
}
export -f run_one
SCENS=("7.69 -2" "0 0")
{
  # Z0: frozen controlled policy against link-only, both with the same settings.
  for col in 1 2 3; do
    for n in 100 2000; do
      echo "2 $col 1 $n 7.69 -2 5 21 none 0 0 z0"
      echo "7 $col 1 $n 7.69 -2 5 21 frozen 0 0 z0"
    done
  done
  # Phase 1 tuning: controlled combinations and link-only baselines at N=500 (N=5000 baselines exist).
  for seed in 16 17 18 19 20; do
    for scen in "${SCENS[@]}"; do
      read -r scint lock <<< "$scen"
      for gain in 5 10; do
        for mode in 1 2; do
          echo "2 3 $mode 500 $scint $lock $gain $seed none 0 0 tune"
          for n in 500 5000; do
            for k in 150 400 0; do
              for adapt in 1 0; do
                echo "7 3 $mode $n $scint $lock $gain $seed $k $adapt 0.1 tune"
              done
            done
          done
        done
      done
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$9" "${10}" "${11}"' | tee results/runs.txt
echo "CHOOSE"
python3 scripts/summarize.py choose results/runs.txt "$HOME/lora-ntn-runs/8a1478bb-d9f6ec6/repo/results/runs.txt" \
  | tee results/choice.txt
read -r K ADAPT < <(grep '^CHOSEN' results/choice.txt | sed -E 's/.*k=([^ ]+) adapt=([^ ]+).*/\1 \2/')
{
  # Phase 2 test: chosen controller and the elevation-aware oracle on unused seeds.
  for seed in 21 22 23 24 25; do
    for col in 1 2 3; do
      for mode in 1 5 2 3; do
        for scen in "${SCENS[@]}"; do
          read -r scint lock <<< "$scen"
          for gain in 5 10; do
            for n in 100 500 2000 5000; do
              echo "7 $col $mode $n $scint $lock $gain $seed $K $ADAPT 0.1 test"
              echo "3 $col $mode $n $scint $lock $gain $seed none 0 0 oracle"
            done
          done
        done
      done
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$9" "${10}" "${11}"' | tee -a results/runs.txt
echo "SUMMARY"
python3 scripts/summarize.py final results/runs.txt results/cases \
  "$HOME/lora-ntn-runs/a7feb12a-f7ecea4/repo/results/runs.txt" "$HOME/lora-ntn-runs/17491a20-b34999c/repo/results/runs.txt" \
  "$HOME/lora-ntn-runs/5fff0738-26c488b/repo/results/runs.txt" "$HOME/lora-ntn-runs/8a1478bb-d9f6ec6/repo/results/runs.txt" \
  | tee results/summary.txt
