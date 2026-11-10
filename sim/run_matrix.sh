#!/usr/bin/env bash
# Stage 3: control loop with a constant controller. S1 runs every case with and without the loop;
# S3 runs scripted controllers. Gain 5 dBi, sensitivity set 1, locked margins.
# Job fields: policy collision dopplerLimits n txProb scintDb margin seed kind part
#   kind: none (no loop), const (constant controller), p0 (p=0 from pass 10), m3 (margin +3 dB from pass 10)
set -euo pipefail
mkdir -p results/cases
JOBS=$(( $(nproc) > 1 ? $(nproc) - 1 : 1 ))
run_one() {
  local pol=$1 col=$2 mode=$3 n=$4 p=$5 scint=$6 margin=$7 seed=$8 kind=$9 part=${10}
  local id="$part-pol$pol-c$col-m$mode-n$n-p$p-s$scint-seed$seed-$kind"
  local ctrl=""
  # Words separated by commas: ns-3 cuts option values at spaces, and the simulator turns commas back.
  case "$kind" in
    const) ctrl="python3,scripts/controller.py,--p,$p,--margin,$margin" ;;
    p0) ctrl="python3,scripts/controller.py,--p,$p,--margin,$margin,--p-from,10:0" ;;
    m3) ctrl="python3,scripts/controller.py,--p,$p,--margin,$margin,--margin-from,10:$(python3 -c "print($margin + 3)")" ;;
  esac
  # ns-3 rejects an empty --controller=, so the option is passed only when a controller is used.
  local extra=()
  [ -n "$ctrl" ] && extra+=("--controller=$ctrl")
  local start end
  start=$(date +%s.%N)
  results/bin/leo_policies --minElevationDeg=20 --policy="$pol" --gainDb=5 --nDevices="$n" --RngRun="$seed" \
    --windowPhase=1 --crossTrackKm=-1 --marginDb="$margin" --passes=20 --channelMode=1 --rxSet=1 \
    --scintDb="$scint" --dopplerLimits="$mode" --txProb="$p" --collision="$col" "${extra[@]}" \
    > "results/cases/$id.log"
  end=$(date +%s.%N)
  grep '^RUN ' "results/cases/$id.log" | sed "s/^RUN /RUN part=$part kind=$kind case=$id wallS=$(python3 -c "print(round($end - $start, 3))") /"
}
export -f run_one
{
  for pol in 2 3; do
    for col in 1 2; do
      for mode in 1 5 2 3; do
        for n in 100 5000; do
          for p in 1 0.5; do
            for scen in "7.69 -2" "0 0"; do
              read -r scint lock <<< "$scen"
              for seed in 21 22; do
                echo "$pol $col $mode $n $p $scint $lock $seed none s1"
                echo "$pol $col $mode $n $p $scint $lock $seed const s1"
              done
            done
          done
        done
      done
    done
  done
  for kind in const p0 m3; do
    echo "2 1 1 2000 1 0 0 21 $kind s3"
  done
} | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$9"' | tee results/runs.txt
echo "SUMMARY"
python3 scripts/summarize.py results/runs.txt results/cases | tee results/summary.txt
