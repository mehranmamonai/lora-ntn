"""Extract the small tables the paper figures need from the raw run files.

Usage: python figs/extract_data.py <artifacts_dir>
<artifacts_dir> holds one folder per experiment with data/runs.txt and data/summary.txt
(efficiency-bound = a7feb12a, load-control-bound = 17491a20, collision-model-gate = 5fff0738,
collision-locking-gate = 8a1478bb, stage4-controller = f1c0467c, stage4-revision = ae2d1534,
beacon-reach = b083617b). Writes CSVs to figs/data/.
"""
import csv
import os
import re
import statistics as st
import sys
from collections import defaultdict

T_95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262}
LOCK = {7.69: -2.0, 0.0: 0.0}  # link margin locked per latitude
READINGS = {1: "R1", 5: "R2", 2: "R3", 3: "R4"}
SEEDS = range(21, 26)
BASE_SOURCES = (("efficiency-bound", "1"), ("load-control-bound", "1"),
                ("collision-model-gate", "2"), ("collision-locking-gate", "3"))

root = sys.argv[1]
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(out, exist_ok=True)


def rows(name, default_collision):
    with open(os.path.join(root, name, "data", "runs.txt")) as f:
        for line in f:
            if line.startswith("RUN "):
                d = dict(kv.split("=", 1) for kv in line.split()[1:])
                d.setdefault("collision", default_collision)
                yield d


def cell(r):
    return (int(r["collision"]), int(r["dopplerLimits"]), float(r["scintDb"]), float(r["gain"]), int(r["n"]))


def delivered(r):
    return float(r["received"]) / (float(r["n"]) * float(r["passes"]))


def ci(v):
    return st.mean(v), T_95[len(v) - 1] * st.stdev(v) / len(v) ** 0.5


def is_base(r):
    return (r["policy"] == "link_only" and float(r["txProb"]) == 1.0 and int(r["seed"]) in SEEDS
            and float(r["marginDb"]) == LOCK[float(r["scintDb"])] and r.get("part") != "regress")


# 1. Headroom: elevation-aware oracle (f1c0467c) vs link-only baselines, same seeds 21-25.
base, orc = defaultdict(dict), defaultdict(dict)
for name, col in BASE_SOURCES:
    for r in rows(name, col):
        if is_base(r):
            base[cell(r)][int(r["seed"])] = delivered(r)
for r in rows("stage4-controller", "1"):
    if r.get("part") == "oracle" and int(r["seed"]) in SEEDS:
        orc[cell(r)][int(r["seed"])] = delivered(r)
with open(os.path.join(out, "headroom.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["collision", "reading", "latitude", "gain_dbi", "devices", "link_only", "link_only_ci",
                "oracle", "oracle_ci", "verdict"])
    for k in sorted(orc):
        if len(base.get(k, {})) != 5 or len(orc[k]) != 5:
            sys.exit(f"incomplete cell {k}: base {len(base.get(k, {}))} oracle {len(orc[k])}")
        b, o = ci(list(base[k].values())), ci(list(orc[k].values()))
        verdict = "better" if o[0] - o[1] > b[0] + b[1] else "worse" if b[0] - b[1] > o[0] + o[1] else "overlap"
        w.writerow([f"C{k[0]}", READINGS[k[1]], "low" if k[2] else "mid", k[3], k[4],
                    f"{b[0]:.4f}", f"{b[1]:.4f}", f"{o[0]:.4f}", f"{o[1]:.4f}", verdict])

# 2. Doppler-loss share, link-only vs controller: the recorded T2 lines of ae2d1534 (10 seeds).
pat = re.compile(r"T2 cell (C\d) (R\d) scint=([\d.]+) gain=(\d+) n=(\d+) dop ctrl=([\d.]+)\+-([\d.]+) "
                 r"link=([\d.]+)\+-([\d.]+) lower=(\w+)")
with open(os.path.join(root, "stage4-revision", "data", "summary.txt")) as f, \
        open(os.path.join(out, "doppler_loss.csv"), "w", newline="") as g:
    w = csv.writer(g)
    w.writerow(["collision", "reading", "latitude", "gain_dbi", "devices", "controller", "controller_ci",
                "link_only", "link_only_ci", "clearly_lower"])
    for line in f:
        m = pat.match(line)
        if m:
            w.writerow([m[1], m[2], "low" if float(m[3]) else "mid", m[4], m[5], m[6], m[7], m[8], m[9], m[10]])

# 3. Delivery with beacon and instant distribution vs the oracle: the recorded B1 lines of b083617b,
#    plus link-only for the same cells (seeds 21-25 from the baselines, 26-30 from ae2d1534).
pat = re.compile(r"B1 (C\d) (R\d) n=(\d+) instant=([\d.]+)\+-([\d.]+) beacon=([\d.]+)\+-([\d.]+) oracle=([\d.]+)")
link = defaultdict(dict)
for r in rows("stage4-revision", "1"):
    if r["policy"] == "link_only" and r.get("part") == "base":
        link[cell(r)][int(r["seed"])] = delivered(r)
for name, col in BASE_SOURCES:
    for r in rows(name, col):
        if is_base(r):
            link[cell(r)][int(r["seed"])] = delivered(r)
inv = {v: k for k, v in READINGS.items()}
with open(os.path.join(root, "beacon-reach", "data", "summary.txt")) as f, \
        open(os.path.join(out, "delivery_limit.csv"), "w", newline="") as g:
    w = csv.writer(g)
    w.writerow(["collision", "reading", "devices", "link_only", "link_only_ci", "link_only_seeds",
                "beacon", "beacon_ci", "instant", "instant_ci", "oracle", "oracle_ci"])
    for line in f:
        m = pat.match(line)
        if not m:
            continue
        k = (int(m[1][1]), inv[m[2]], 7.69, 5.0, int(m[3]))
        lo, o = ci(list(link[k].values())), ci(list(orc[k].values()))
        w.writerow([m[1], m[2], m[3], f"{lo[0]:.4f}", f"{lo[1]:.4f}", len(link[k]),
                    m[6], m[7], m[4], m[5], f"{o[0]:.4f}", f"{o[1]:.4f}"])

# 4. Per-pass trajectory (C3, R1, 500 devices, low latitude, 5 dBi, seeds 21-25), extracted earlier from
#    the PASS lines of the ae2d1534 case logs.
with open(os.path.join(root, "dashboard-data", "trajectory.csv")) as f, \
        open(os.path.join(out, "trajectory.csv"), "w", newline="") as g:
    g.write(f.read())
print("wrote", sorted(os.listdir(out)))
