#!/usr/bin/env bash
# Satellite-altitude validation: 6 altitudes, 2 antenna gains, 20 seeds, 5 degree beam.
set -euo pipefail
OUT=results/csv
mkdir -p "$OUT"
JOBS=$(( $(nproc) > 1 ? $(nproc) - 1 : 1 ))
run_one() {
  results/bin/sat_altitude --altitudeKm="$1" --totalGainDb="$2" --beamwidthDeg=5 --periodS=60 \
    --nPeriods=20 --RngRun="$3" --csv="$OUT/h$1_g$2_seed$3.csv"
}
export -f run_one
export OUT
for h in 200 300 400 500 600 700; do
  for g in 5 10; do
    for seed in $(seq 1 20); do
      echo "$h $g $seed"
    done
  done
done | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2"' > results/runs.txt
echo "SUMMARY runs=$(wc -l < results/runs.txt)"
python3 scripts/summarize.py "$OUT" results/runs.txt
