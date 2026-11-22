"""Extract the small tables the paper figures need from the raw run files.

Usage: python figs/extract_data.py <artifacts_dir>
<artifacts_dir> holds one folder per experiment with data/runs.txt and data/summary.txt
(efficiency-bound = a7feb12a, load-control-bound = 17491a20, collision-model-gate = 5fff0738,
collision-locking-gate = 8a1478bb, stage4-controller = f1c0467c, stage4-revision = ae2d1534,
beacon-reach = b083617b, hindsight-threshold = 373b90c7). Writes CSVs to figs/data/.
Policies that run on the same seeds are compared on paired per-seed differences.
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


def paired(a, b):
    # mean and 95% t half-width of the per-seed differences a - b over the shared seeds
    seeds = sorted(set(a) & set(b))
    return ci([a[s] - b[s] for s in seeds])


def dlost(r):
    return float(r["rejDoppler"]) / (float(r["n"]) * float(r["passes"]))


# 1. Headroom: elevation-aware oracle (f1c0467c) vs link-only baselines, paired on seeds 21-25.
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
        d = paired(orc[k], base[k])
        verdict = "better" if d[0] - d[1] > 0 else "worse" if d[0] + d[1] < 0 else "overlap"
        w.writerow([f"C{k[0]}", READINGS[k[1]], "low" if k[2] else "mid", k[3], k[4],
                    f"{b[0]:.4f}", f"{b[1]:.4f}", f"{o[0]:.4f}", f"{o[1]:.4f}", verdict])

# 2. Doppler-lost packets per device per pass, link-only vs controller (ae2d1534), seeds 21-30, low
#    latitude, 5 dBi; "lower" means the paired 95% interval of controller minus link-only is below zero.
lost_link, lost_ctrl = defaultdict(dict), defaultdict(dict)
for r in rows("stage4-revision", "1"):
    if r.get("part") == "test":
        lost_ctrl[cell(r)][int(r["seed"])] = dlost(r)
    elif r["policy"] == "link_only" and r.get("part") == "base":
        lost_link[cell(r)][int(r["seed"])] = dlost(r)
for name, col in BASE_SOURCES:
    for r in rows(name, col):
        if is_base(r):
            lost_link[cell(r)][int(r["seed"])] = dlost(r)
with open(os.path.join(out, "doppler_lost.csv"), "w", newline="") as g:
    w = csv.writer(g)
    w.writerow(["collision", "reading", "devices", "link_only", "link_only_ci", "controller", "controller_ci",
                "paired_diff", "paired_ci", "lower"])
    for k in sorted(lost_ctrl):
        if k[2] != 7.69 or k[3] != 5.0 or k[1] not in (1, 5):
            continue
        lo, ct, d = ci(list(lost_link[k].values())), ci(list(lost_ctrl[k].values())), paired(lost_ctrl[k], lost_link[k])
        if len(lost_link[k]) != 10:
            sys.exit(f"incomplete link-only cell {k}")
        w.writerow([f"C{k[0]}", READINGS[k[1]], k[4], f"{lo[0]:.4f}", f"{lo[1]:.4f}", f"{ct[0]:.4f}",
                    f"{ct[1]:.4f}", f"{d[0]:.4f}", f"{d[1]:.4f}", d[0] + d[1] < 0])

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
# Oracle on all ten seeds (21-25 from f1c0467c, 26-30 from 373b90c7) and the hindsight-best fixed cut-off.
for r in rows("hindsight-threshold", "1"):
    if r.get("part") == "oracle":
        orc[cell(r)][int(r["seed"])] = delivered(r)
for r in rows("stage4-controller", "1"):
    if r.get("part") == "oracle" and int(r["seed"]) in range(21, 31):
        orc[cell(r)][int(r["seed"])] = delivered(r)
fixed = defaultdict(lambda: defaultdict(dict))
for r in rows("hindsight-threshold", "1"):
    if r.get("part") == "fixed":
        fixed[cell(r)][int(float(r["thetaFixedDeg"]))][int(r["seed"])] = delivered(r)
inv = {v: k for k, v in READINGS.items()}
with open(os.path.join(root, "beacon-reach", "data", "summary.txt")) as f, \
        open(os.path.join(out, "delivery_limit.csv"), "w", newline="") as g:
    w = csv.writer(g)
    w.writerow(["collision", "reading", "devices", "link_only", "link_only_ci", "link_only_seeds",
                "beacon", "beacon_ci", "instant", "instant_ci", "oracle", "oracle_ci", "oracle_seeds",
                "best_fixed", "best_fixed_ci", "best_fixed_deg"])
    for line in f:
        m = pat.match(line)
        if not m:
            continue
        if m[2] == "R4":  # identical to R1 at low latitude, 5 dBi; the hindsight run covers R1 and R2 only
            continue
        k = (int(m[1][1]), inv[m[2]], 7.69, 5.0, int(m[3]))
        lo, o = ci(list(link[k].values())), ci(list(orc[k].values()))
        th = max(fixed[k], key=lambda t: st.mean(fixed[k][t].values()))
        h = ci(list(fixed[k][th].values()))
        w.writerow([m[1], m[2], m[3], f"{lo[0]:.4f}", f"{lo[1]:.4f}", len(link[k]),
                    m[6], m[7], m[4], m[5], f"{o[0]:.4f}", f"{o[1]:.4f}", len(orc[k]),
                    f"{h[0]:.4f}", f"{h[1]:.4f}", th])

# 4. Per-pass trajectory (C3, R1, 500 devices, low latitude, 5 dBi, seeds 21-30) from the PASS lines of
#    the ae2d1534 case logs in stage4-revision/data/cases.tar.gz.
import tarfile  # noqa: E402

with tarfile.open(os.path.join(root, "stage4-revision", "data", "cases.tar.gz")) as tf,         open(os.path.join(out, "trajectory.csv"), "w", newline="") as g:
    w = csv.writer(g)
    w.writerow(["seed", "pass", "cutoff_deg", "sent", "received", "doppler_lost", "beacons_heard", "beacons_missed"])
    for seed in range(21, 31):
        name = f"cases/test-pol7-c3-m1-n500-s7.69-g5-seed{seed}-k0-a0-e0.1.log"
        for line in tf.extractfile(name).read().decode().splitlines():
            if line.startswith("PASS "):
                d = dict(kv.split("=", 1) for kv in line.split()[1:])
                w.writerow([seed, d["pass"], d["thetaDeg"], d["sent"], d["received"], d["rejDoppler"],
                            d["beaconsHeard"], d["beaconsMissed"]])
print("wrote", sorted(os.listdir(out)))
