#!/usr/bin/env bash
# Review revision: is the single elevation threshold, or the learning rule, what keeps the controller
# from the oracle? Low latitude, 5 dBi, C1-C3, R1 and R2 (R4 equals R1 here), N=100-5000, seeds 21-30.
#   check : link-only and a fixed cut-off of 90 deg on seed 21; must match exactly (option is inert).
#   fixed : every device holds a fixed SF12 cut-off theta in {20,...,80} from the start; no beacons,
#           no exploration, no controller. The best theta per scenario, chosen on the test seeds
#           themselves, is the hindsight-optimal single-threshold baseline.
#   eps0  : the Stage 4 controller (beacons, H off) without exploration.
#   oracle: elevation-aware oracle on seeds 26-30, so it covers all ten test seeds with ae2d1534's 21-25
#           from f1c0467c.
set -euo pipefail
mkdir -p results/cases
JOBS=$(( $(nproc) > 1 ? $(nproc) - 1 : 1 ))
COMMON="--minElevationDeg=20 --gainDb=5 --windowPhase=1 --crossTrackKm=-1 --marginDb=-2 --passes=20 \
--channelMode=1 --rxSet=1 --scintDb=7.69 --txProb=1"
# Job fields: part policy collision mode n seed theta
run_one() {
  local part=$1 pol=$2 col=$3 mode=$4 n=$5 seed=$6 theta=$7
  local id="$part-pol$pol-c$col-m$mode-n$n-seed$seed-t$theta"
  local extra=()
  case "$part" in
    check|fixed) [ "$pol" = 7 ] && extra+=("--thetaDeg=$theta" "--beacons=0" "--exploreProb=0") ;;
    eps0) extra+=("--exploreProb=0"
                  "--controller=python3,scripts/controller.py,--mode,adaptive,--p,1,--margin,-2,--k,0,--adapt-margin,0,--h,0") ;;
  esac
  # shellcheck disable=SC2086
  results/bin/leo_policies $COMMON --policy="$pol" --nDevices="$n" --RngRun="$seed" --dopplerLimits="$mode" \
    --collision="$col" "${extra[@]}" > "results/cases/$id.log"
  grep '^RUN ' "results/cases/$id.log" | sed "s/^RUN /RUN part=$part case=$id /"
}
export -f run_one
export COMMON
{
  for col in 1 3; do
    for n in 100 2000; do
      echo "check 2 $col 1 $n 21 90"
      echo "check 7 $col 1 $n 21 90"
    done
  done
  for seed in 21 22 23 24 25 26 27 28 29 30; do
    for col in 1 2 3; do
      for mode in 1 5; do
        for n in 100 500 2000 5000; do
          for theta in 20 30 40 50 60 70 80; do
            echo "fixed 7 $col $mode $n $seed $theta"
          done
          echo "eps0 7 $col $mode $n $seed 90"
          if [ "$seed" -ge 26 ]; then echo "oracle 3 $col $mode $n $seed 90"; fi
        done
      done
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2" "$3" "$4" "$5" "$6"' | tee results/runs.txt
echo "SUMMARY"
python3 scripts/summarize.py experiments results/runs.txt | tee results/summary.txt
