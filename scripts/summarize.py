"""Stage 4: choose the controller settings on seeds 16-20, then test criteria Z0 and T1-T4.
Usage: summarize.py choose runs.txt c3_parent_runs.txt
       summarize.py final runs.txt cases_dir c1_runs c1_runs c2_runs c3_runs"""
import math
import os
import statistics as st
import sys
from collections import defaultdict

T_95_DF4 = 2.776
LOCK = {7.69: -2.0, 0.0: 0.0}
READINGS = {1: "R1", 5: "R2", 2: "R3", 3: "R4"}
HOLE_MODES = (1, 5, 3)
NS = (100, 500, 2000, 5000)


def rows(path, default_collision="1"):
    out = []
    with open(path) as f:
        for line in f:
            if line.startswith("RUN "):
                d = dict(kv.split("=", 1) for kv in line.split()[1:])
                d.setdefault("collision", default_collision)
                out.append(d)
    return out


def ci(values):
    return st.mean(values), (T_95_DF4 * st.stdev(values) / len(values) ** 0.5 if len(values) > 1 else 0.0)


def delivered(r):
    return float(r["received"]) / (float(r["n"]) * float(r["passes"]))


def air(r):
    return float(r["airtimeS"]) / float(r["received"]) if float(r["received"]) else math.inf


def doppler_share(r):
    return float(r["rejDoppler"]) / float(r["sent"]) if float(r["sent"]) else 0.0


def clearly_below(a, b):
    return a[0] + a[1] < b[0] - b[1]


def cell(r):
    return (int(r["collision"]), int(r["dopplerLimits"]), float(r["scintDb"]), float(r["gain"]), int(r["n"]))


def is_baseline(r, seeds):
    return (r["policy"] == "link_only" and float(r["txProb"]) == 1.0 and int(r["seed"]) in seeds
            and float(r["marginDb"]) == LOCK[float(r["scintDb"])] and r.get("part") != "regress")


def group(rs):
    g = defaultdict(dict)
    for r in rs:
        g[cell(r)][int(r["seed"])] = r  # one run per seed; duplicates across parents are identical
    return g


def stat(runs, fn):
    values = [fn(r) for r in runs.values()]
    if any(math.isinf(v) for v in values):
        return (math.inf, 0.0)
    return ci(values)


if sys.argv[1] == "choose":
    new = rows(sys.argv[2])
    seeds = {16, 17, 18, 19, 20}
    base = group([r for r in new + rows(sys.argv[3]) if is_baseline(r, seeds) and int(r["collision"]) == 3])
    combos = defaultdict(list)
    for r in new:
        if r["part"] == "tune" and r["policy"] == "controlled":
            combos[(r["k"], r["adapt"])].append(r)
    scores = []
    for combo, rs in sorted(combos.items()):
        g = group(rs)
        ratios, airs = [], []
        for key, runs in sorted(g.items()):
            if key not in base:
                print(f"TUNE missing baseline {key}")
                continue
            b = st.mean(delivered(r) for r in base[key].values())
            c = st.mean(delivered(r) for r in runs.values())
            ratios.append(c / b if b else float("inf"))
            airs.append(st.mean(air(r) for r in runs.values() if math.isfinite(air(r))))
        worst, mean_air = min(ratios), st.mean(airs)
        scores.append((worst, -mean_air, combo))
        print(f"TUNE k={combo[0]} adapt={combo[1]} cells={len(ratios)} worst_ratio={worst:.3f} "
              f"median_ratio={st.median(ratios):.3f} mean_air={mean_air:.2f}")
    best = max(scores)
    print(f"CHOSEN k={best[2][0]} adapt={best[2][1]} worst_ratio={best[0]:.3f}")
    sys.exit(0)

# final
new = rows(sys.argv[2])
cases_dir = sys.argv[3]
c1 = [r for p in sys.argv[4:6] for r in rows(p, "1")]
c2 = rows(sys.argv[6], "2")
c3 = rows(sys.argv[7], "3")
seeds = {21, 22, 23, 24, 25}
base = group([r for r in c1 + c2 + c3 if is_baseline(r, seeds)])
ctrl = group([r for r in new if r["part"] == "test"])
oracle = group([r for r in new if r["part"] == "oracle"])

# Z0
z = defaultdict(dict)
for r in new:
    if r["part"] == "z0":
        z[(r["collision"], r["n"])][r["policy"]] = r
fields = ["sent", "received", "airtimeS", "rejDoppler", "interfered", "underSens", "noDemod"]
z_bad = [k for k, pair in z.items() if len(pair) != 2 or any(pair["link_only"][f] != pair["controlled"][f] for f in fields)]
z0 = len(z) == 6 and not z_bad
print(f"Z0 pairs={len(z)} mismatches={len(z_bad)} holds={z0}")
chosen = next(((r["k"], r["adapt"]) for r in new if r["part"] == "test"), ("?", "?"))
print(f"CHOSEN k={chosen[0]} adapt={chosen[1]}")

missing = [k for k in ctrl if k not in base]
print(f"BASELINES cells={len(ctrl)} missing={len(missing)} {missing[:3]}")

# T1 no harm
harm = []
for key, runs in sorted(ctrl.items()):
    if key in base and clearly_below(stat(runs, delivered), stat(base[key], delivered)):
        harm.append(key)
for key in harm:
    a, b = stat(ctrl[key], delivered), stat(base[key], delivered)
    print(f"T1 harm C{key[0]} {READINGS[key[1]]} scint={key[2]:g} gain={key[3]:g} n={key[4]} "
          f"ctrl={a[0]:.3f}+-{a[1]:.3f} link={b[0]:.3f}+-{b[1]:.3f}")
t1 = not harm and not missing and len(ctrl) == 192
print(f"T1 cells={len(ctrl)} harmed={len(harm)} holds={t1}")

# T2 Doppler
better = hole_cells = worse_r3 = r3_cells = 0
for key, runs in ctrl.items():
    if key not in base:
        continue
    a, b = stat(runs, doppler_share), stat(base[key], doppler_share)
    if key[1] in HOLE_MODES:
        hole_cells += 1
        better += clearly_below(a, b)
    elif key[1] == 2:
        r3_cells += 1
        worse_r3 += clearly_below(b, a)
t2 = hole_cells == 144 and better >= 108 and r3_cells == 48 and worse_r3 == 0
print(f"T2 hole_cells={hole_cells} lower_doppler_loss={better} needed=108 r3_cells={r3_cells} "
      f"r3_higher={worse_r3} holds={t2}")

# T3 load
t3_cells = [k for k in ctrl if k[2] == 0.0 and k[3] == 5.0 and k[4] == 5000 and k in base]
t3_wins = 0
for key in sorted(t3_cells):
    a, b = stat(ctrl[key], air), stat(base[key], air)
    win = clearly_below(a, b)
    t3_wins += win
    print(f"T3 C{key[0]} {READINGS[key[1]]} air ctrl={a[0]:.2f}+-{a[1]:.2f} link={b[0]:.2f}+-{b[1]:.2f} "
          f"delivered ctrl={stat(ctrl[key], delivered)[0]:.3f} link={stat(base[key], delivered)[0]:.3f} win={win}")
t3 = len(t3_cells) == 12 and t3_wins >= 10
print(f"T3 cells={len(t3_cells)} wins={t3_wins} needed=10 holds={t3}")
print(f"GATE Z0={z0} T1={t1} T2={t2} T3={t3} passes={z0 and t1 and t2 and t3}")

# T4 report
ratios_link, ratios_oracle = [], []
for key, runs in ctrl.items():
    c = st.mean(delivered(r) for r in runs.values())
    if key in base:
        b = st.mean(delivered(r) for r in base[key].values())
        if b:
            ratios_link.append(c / b)
    if key in oracle:
        o = st.mean(delivered(r) for r in oracle[key].values())
        if o:
            ratios_oracle.append(c / o)
print(f"T4 delivery ctrl/link median={st.median(ratios_link):.3f} min={min(ratios_link):.3f} max={max(ratios_link):.3f}")
print(f"T4 delivery ctrl/oracle median={st.median(ratios_oracle):.3f} min={min(ratios_oracle):.3f} max={max(ratios_oracle):.3f}")
for scint in (7.69, 0.0):
    heard = sum(int(r["beaconsHeard"]) for r in new if r["part"] == "test" and float(r["scintDb"]) == scint)
    missed = sum(int(r["beaconsMissed"]) for r in new if r["part"] == "test" and float(r["scintDb"]) == scint)
    print(f"T4 beacons scint={scint:g} heard_share={heard / (heard + missed):.3f}")
thetas = defaultdict(list)
for r in new:
    if r["part"] == "test":
        path = os.path.join(cases_dir, r["case"] + ".log")
        with open(path) as f:
            last = [line for line in f if line.startswith("PASS ")][-1]
        thetas[int(r["dopplerLimits"])].append(float(dict(kv.split("=") for kv in last.split()[1:])["thetaDeg"]))
for mode in (1, 5, 2, 3):
    values = thetas[mode]
    print(f"T4 theta {READINGS[mode]} final cut-off median={st.median(values):g} "
          f"share_at_90={sum(v == 90 for v in values) / len(values):.2f}")
for key, runs in sorted(ctrl.items()):
    a = stat(runs, delivered)
    b = stat(base[key], delivered) if key in base else (float("nan"), 0)
    o = stat(oracle[key], delivered) if key in oracle else (float("nan"), 0)
    print(f"RESULT C{key[0]} {READINGS[key[1]]} scint={key[2]:g} gain={key[3]:g} n={key[4]} "
          f"ctrl={a[0]:.3f}+-{a[1]:.3f} link={b[0]:.3f}+-{b[1]:.3f} oracle={o[0]:.3f}+-{o[1]:.3f} "
          f"dop_ctrl={stat(runs, doppler_share)[0]:.3f} dop_link={stat(base[key], doppler_share)[0] if key in base else float('nan'):.3f}")
