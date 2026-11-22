"""Fairness and energy for the Stage 4 controller vs link-only (review items M3-1, M3-2).
Paired per-seed differences, seeds 21-30, in the 36 scenarios with SF12 Doppler loss.
Jain's index and served devices come from the run line; energy is reported as transmit airtime per
delivered packet (transmit energy is proportional to airtime at fixed 14 dBm).
Usage: fairness_energy.py <experiments dir>"""
import math
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

from scipy import stats

E = Path(sys.argv[1])
LOCK = {7.69: -2.0, 0.0: 0.0}


def rows(path, dc):
    out = []
    for line in open(path):
        if line.startswith("RUN "):
            d = dict(kv.split("=", 1) for kv in line.split()[1:])
            d.setdefault("collision", dc)
            out.append(d)
    return out


def key(r):
    return (int(r["collision"]), int(r["dopplerLimits"]), float(r["scintDb"]), float(r["gain"]), int(r["n"]))


rev = rows(E / "stage4-revision/data/runs.txt", "1")
base_rows = (rows(E / "efficiency-bound/data/runs.txt", "1") + rows(E / "load-control-bound/data/runs.txt", "1")
             + rows(E / "collision-model-gate/data/runs.txt", "2") + rows(E / "collision-locking-gate/data/runs.txt", "3")
             + [r for r in rev if r["part"] == "base"])
link, ctrl = defaultdict(dict), defaultdict(dict)
for r in base_rows:
    if (r["policy"] == "link_only" and float(r["txProb"]) == 1.0 and 21 <= int(r["seed"]) <= 30
            and float(r["marginDb"]) == LOCK[float(r["scintDb"])] and r.get("part") != "regress"):
        link[key(r)][int(r["seed"])] = r
for r in rev:
    if r["part"] == "test":
        ctrl[key(r)][int(r["seed"])] = r

metrics = {
    "jain": lambda r: float(r["jain"]),
    "served_share": lambda r: float(r["served"]) / float(r["n"]),
    "air_per_delivered_s": lambda r: float(r["airtimeS"]) / float(r["received"]),
    "air_per_device_s": lambda r: float(r["airtimeS"]) / float(r["n"]),
}
keys = [k for k in sorted(ctrl) if k[1] in (1, 5, 3) and k[2] == 7.69 and k[3] == 5]
print(f"scenarios={len(keys)} (36 with SF12 Doppler loss; R4 duplicates R1)")
for name, fn in metrics.items():
    up = down = 0
    rel = []
    for k in keys:
        d = [fn(ctrl[k][s]) - fn(link[k][s]) for s in range(21, 31)]
        m = st.mean(d)
        h = stats.t.ppf(0.975, 9) * st.stdev(d) / math.sqrt(10) if st.stdev(d) > 0 else 0
        up += m - h > 0
        down += m + h < 0
        rel.append(st.mean(fn(ctrl[k][s]) for s in range(21, 31)) / st.mean(fn(link[k][s]) for s in range(21, 31)))
    print(f"{name:22s} significantly_up={up:2d} significantly_down={down:2d} ratio ctrl/link median={st.median(rel):.3f} "
          f"range={min(rel):.3f}-{max(rel):.3f}")
