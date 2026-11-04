"""Compare simulated data-rate shares with Traspadini et al., Figs. 2a and 3a."""
import csv
import glob
import os
import re
import sys
from collections import defaultdict

ALTITUDES = [200, 300, 400, 500, 600, 700]
# Paper values, read from the figure text: PAPER[gain][dr] gives the share at each altitude.
PAPER = {
    5: {
        0: [0.00, 0.00, 0.00, 0.07, 0.74, 0.99],
        1: [0.00, 0.00, 0.08, 0.84, 0.26, 0.01],
        2: [0.00, 0.29, 0.92, 0.09, 0.00, 0.00],
        3: [0.05, 0.71, 0.00, 0.00, 0.00, 0.00],
        4: [0.95, 0.00, 0.00, 0.00, 0.00, 0.00],
        5: [0.00, 0.00, 0.00, 0.00, 0.00, 0.00],
    },
    10: {
        0: [0.00, 0.00, 0.00, 0.00, 0.00, 0.00],
        1: [0.00, 0.00, 0.00, 0.00, 0.00, 0.05],
        2: [0.00, 0.00, 0.00, 0.07, 0.74, 0.94],
        3: [0.00, 0.00, 0.52, 0.93, 0.26, 0.01],
        4: [0.00, 0.76, 0.48, 0.00, 0.00, 0.00],
        5: [1.00, 0.24, 0.00, 0.00, 0.00, 0.00],
    },
}

csv_dir, runs_path = sys.argv[1], sys.argv[2]
counts = defaultdict(lambda: defaultdict(int))
for path in glob.glob(os.path.join(csv_dir, "*.csv")):
    m = re.search(r"h(\d+)_g(\d+)_seed(\d+)", path)
    with open(path) as f:
        for row in csv.DictReader(f):
            counts[(int(m[2]), int(m[1]))][int(row["dr"])] += 1

delivery = defaultdict(lambda: [0.0, 0.0])
with open(runs_path) as f:
    for line in f:
        fields = dict(kv.split("=") for kv in line.split()[1:])
        key = (int(float(fields["totalGainDb"])), int(float(fields["altitudeKm"])))
        delivery[key][0] += float(fields["macSent"])
        delivery[key][1] += float(fields["macReceived"])

all_diffs = []
mode_matches = 0
for gain in (5, 10):
    for i, h in enumerate(ALTITUDES):
        c = counts[(gain, h)]
        total = sum(c.values())
        sim = [c[dr] / total for dr in range(6)]
        paper = [PAPER[gain][dr][i] for dr in range(6)]
        diffs = [abs(a - b) for a, b in zip(sim, paper)]
        all_diffs.extend(diffs)
        sim_mode = max(range(6), key=lambda d: sim[d])
        paper_mode = max(range(6), key=lambda d: paper[d])
        mode_matches += sim_mode == paper_mode
        sent, recv = delivery[(gain, h)]
        print(
            f"gain={gain} h={h} devices={total} "
            f"sim={[round(x, 2) for x in sim]} paper={paper} "
            f"mode_sim=DR{sim_mode} mode_paper=DR{paper_mode} max_diff={max(diffs):.2f} "
            f"macSent={sent:.0f} macReceived={recv:.0f} "
            f"pdr={recv / sent if sent else float('nan'):.3f}"
        )
mean_diff = sum(all_diffs) / len(all_diffs)
print(f"VALIDATION mode_matches={mode_matches}/12 mean_abs_share_diff={mean_diff:.3f} "
      f"pass={mode_matches == 12 and mean_diff <= 0.10}")
