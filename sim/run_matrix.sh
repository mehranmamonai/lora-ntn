#!/usr/bin/env bash
# Efficiency gate under C3: Croce et al. 2018 Table II thresholds plus the receiver-locking rule of
# Bor et al. 2016. Link-only,
# sensitivity set 1, locked margins. Seeds 16-20 choose; seeds 21-25 test.
# Job fields: gain n seed margin scintDb dopplerLimits txProb collision part
set -euo pipefail
mkdir -p results
JOBS=$(( $(nproc) > 1 ? $(nproc) - 1 : 1 ))
C1_RUNS="$HOME/lora-ntn-runs/a7feb12a-f7ecea4/repo/results/runs.txt $HOME/lora-ntn-runs/17491a20-b34999c/repo/results/runs.txt"
C2_RUNS="$HOME/lora-ntn-runs/5fff0738-26c488b/repo/results/runs.txt"
run_one() {
  results/bin/leo_policies --minElevationDeg=20 --policy=2 --gainDb="$1" --nDevices="$2" --RngRun="$3" \
    --windowPhase=1 --crossTrackKm=-1 --marginDb="$4" --passes=20 --channelMode=1 --rxSet=1 \
    --scintDb="$5" --dopplerLimits="$6" --txProb="$7" --collision="$8" | sed "s/^RUN /RUN part=$9 /"
}
export -f run_one
{
  # N1: exact repeats under C1 (a7feb12a, 17491a20) and under C2 (5fff0738).
  echo "5 100 21 -2 7.69 1 1 1 regress"
  echo "10 500 22 -2 7.69 5 0.5 1 regress"
  echo "5 100 23 0 0 2 0.25 1 regress"
  echo "5 2000 21 -2 7.69 1 1 1 regress"
  echo "10 5000 21 0 0 3 1 1 regress"
  echo "5 2000 16 -2 7.69 1 1 1 regress"
  echo "5 5000 21 -2 7.69 1 1 2 regress"
  echo "10 2000 23 0 0 5 0.5 2 regress"
  echo "5 100 24 0 0 3 0.25 2 regress"
  for seed in 16 17 18 19 20 21 22 23 24 25; do
    part=confirm
    [ "$seed" -le 20 ] && part=search
    for g in 5 10; do
      for scen in "7.69 -2" "0 0"; do
        read -r scint lock <<< "$scen"
        for mode in 1 5 2 3; do
          for p in 1 0.5 0.25 0.125 0.0625; do
            if [ "$part" = search ]; then
              echo "$g 5000 $seed $lock $scint $mode $p 3 $part"
            else
              for n in 100 500 2000 5000; do
                echo "$g $n $seed $lock $scint $mode $p 3 $part"
              done
            fi
          done
        done
      done
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8"' | tee results/runs.txt
echo "SUMMARY"
python3 scripts/summarize.py results/runs.txt "$C2_RUNS" $C1_RUNS | tee results/summary.txt
