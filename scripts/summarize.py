"""Aggregate per-device CSVs into per-configuration results for the run log."""
import csv
import glob
import os
import re
import statistics as st
import sys
from collections import defaultdict

root = sys.argv[1]
groups = defaultdict(list)
for path in sorted(glob.glob(os.path.join(root, "*.csv"))):
    m = re.search(r"period(\d+)_hist(\d+)_seed(\d+)", path)
    with open(path) as f:
        groups[(int(m[1]), int(m[2]))].append(list(csv.DictReader(f)))

for (period, hist), runs in sorted(groups.items()):
    rows = [r for run in runs for r in run]
    changed = [r for r in rows if float(r["first_change_s"]) >= 0]
    times = [float(r["first_change_s"]) for r in changed]
    uplinks = [int(r["sent_at_change"]) for r in changed]
    finals = defaultdict(int)
    for r in rows:
        finals[int(r["final_dr"])] += 1
    print(
        f"period={period}s history={hist} seeds={len(runs)} devices={len(rows)} "
        f"frac_changed={len(changed) / len(rows):.3f} "
        f"median_first_change_s={st.median(times) if times else 'NA'} "
        f"min_first_change_s={min(times) if times else 'NA'} "
        f"median_uplinks_at_change={st.median(uplinks) if uplinks else 'NA'} "
        f"min_uplinks_at_change={min(uplinks) if uplinks else 'NA'} "
        f"initial_dr={sorted({int(r['initial_dr']) for r in rows})} "
        f"final_dr_counts={dict(sorted(finals.items()))}"
    )
