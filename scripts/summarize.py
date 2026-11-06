"""Test the efficiency upper bound against the criteria fixed before the experiment."""
import math
import statistics as st
import sys
from collections import defaultdict

T_95_DF4 = 2.776
PS_LOW = [0.5, 0.25, 0.125, 0.0625]
GAINS = (5.0, 10.0)
SCINTS = (7.69, 0.0)
LOCK = {7.69: -2.0, 0.0: 0.0}
MODES = (1, 5, 2, 3)
READINGS = {1: "R1", 5: "R2", 2: "R3", 3: "R4"}
NS = (100, 500, 2000, 5000)


def load(path, only_link):
    rows = []
    with open(path) as f:
        for line in f:
            if line.startswith("RUN "):
                d = dict(kv.split("=") for kv in line.split()[1:])
                if not only_link or d["policy"] == "link_only":
                    rows.append(d)
    return rows


new_rows = load(sys.argv[1], False)
parent_rows = load(sys.argv[2], True)

# K1: exact match against the parent run.
parent_index = {(d["gain"], d["n"], d["seed"], d["marginDb"], d["scintDb"], d["dopplerLimits"], d["txProb"]): d
                for d in parent_rows}
regress = [d for d in new_rows if d["part"] == "regress"]
matches = [parent_index[(d["gain"], d["n"], d["seed"], d["marginDb"], d["scintDb"], d["dopplerLimits"], d["txProb"])]
           for d in regress]
same = all(a["received"] == b["received"] and a["sent"] == b["sent"] and a["airtimeS"] == b["airtimeS"]
           for a, b in zip(regress, matches))
print(f"K1 cases={len(regress)} exact_match={same}")

groups = defaultdict(list)
for d in parent_rows + [r for r in new_rows if r["part"] != "regress"]:
    key = (d["part"], float(d["scintDb"]), int(d["dopplerLimits"]), float(d["gain"]), int(d["n"]),
           float(d["marginDb"]), float(d["txProb"]))
    groups[key].append(d)


def ci(values):
    return st.mean(values), T_95_DF4 * st.stdev(values) / len(values) ** 0.5


metrics = {}
for key, runs in sorted(groups.items()):
    part, scint, mode, g, n, m, p = key
    delivered = ci([float(r["received"]) / (float(r["n"]) * float(r["passes"])) for r in runs])
    per_seed = [float(r["airtimeS"]) / float(r["received"]) if float(r["received"]) else math.inf for r in runs]
    airtime = ci(per_seed) if all(math.isfinite(x) for x in per_seed) else (math.inf, 0.0)
    metrics[key] = (delivered, airtime)
    print(f"RESULT part={part} scint={scint:g} reading={READINGS[mode]} gain={g:g} n={n} margin={m:g} p={p:g} "
          f"runs={len(runs)} delivered={delivered[0]:.3f}+-{delivered[1]:.3f} "
          f"air_per_delivered={airtime[0]:.2f}+-{airtime[1]:.2f} "
          f"jain={st.mean(float(r['jain']) for r in runs):.3f}")


def M(part, scint, mode, g, n, p, margin=None):
    return metrics[(part, scint, mode, g, n, LOCK[scint] if margin is None else margin, p)]


def clearly_below(a, b):
    return a[0] + a[1] < b[0] - b[1]


wins = 0
by_reading = defaultdict(int)
for scint in SCINTS:
    for mode in MODES:
        for g in GAINS:
            base = M("search", scint, mode, g, 5000, 1.0)
            ok = [p for p in PS_LOW if not clearly_below(M("search", scint, mode, g, 5000, p)[0], base[0])
                  and math.isfinite(M("search", scint, mode, g, 5000, p)[1][0])]
            if not ok:
                print(f"K2 scint={scint:g} {READINGS[mode]} gain={g:g} no_candidate win=False")
                continue
            chosen = min(ok, key=lambda p: M("search", scint, mode, g, 5000, p)[1][0])
            a = M("confirm", scint, mode, g, 5000, chosen)
            b = M("confirm", scint, mode, g, 5000, 1.0)
            cheaper = a[1][0] + a[1][1] < b[1][0] - b[1][1]
            win = cheaper and not clearly_below(a[0], b[0])
            wins += win
            by_reading[mode] += win
            print(f"K2 scint={scint:g} {READINGS[mode]} gain={g:g} p={chosen:g} "
                  f"delivered={a[0][0]:.3f}+-{a[0][1]:.3f} vs {b[0][0]:.3f}+-{b[0][1]:.3f} "
                  f"air={a[1][0]:.2f}+-{a[1][1]:.2f} vs {b[1][0]:.2f}+-{b[1][1]:.2f} "
                  f"air_ratio={a[1][0] / b[1][0]:.2f} win={win}")
k2 = wins >= 8
print(f"K2 wins={wins}/16 needed=8 holds={k2}")
print("K5 " + " ".join(f"{READINGS[m]}={by_reading[m]}/4" for m in MODES))

serves_all = []
for p in PS_LOW:
    counts = {}
    for n in NS:
        counts[n] = sum(
            not clearly_below(M("confirm", s, mode, g, n, p)[0], M("confirm", s, mode, g, n, 1.0)[0])
            for s in SCINTS for mode in MODES for g in GAINS)
    serves = all(c >= 12 for c in counts.values())
    if serves:
        serves_all.append(p)
    print(f"K3 p={p:g} not_clearly_worse " + " ".join(f"n{n}={counts[n]}/16" for n in NS) + f" serves_all={serves}")
k3 = not serves_all
print(f"K3 holds={k3}")
print(f"GATE K2={k2} K3={k3} passes={k2 and k3}")

for scint in SCINTS:
    margins = [LOCK[scint] - 1, LOCK[scint], LOCK[scint] + 1]
    for mode in (1, 2):
        for g in GAINS:
            for n in (2000, 5000):
                options = [(m, p) for m in margins for p in (1.0, 0.5, 0.25)]
                best = max(options, key=lambda o: M("search", scint, mode, g, n, o[1], o[0])[0][0])
                a = M("confirm", scint, mode, g, n, best[1], best[0])
                b = M("confirm", scint, mode, g, n, 1.0)
                print(f"K4 scint={scint:g} {READINGS[mode]} gain={g:g} n={n} margin={best[0]:g} p={best[1]:g} "
                      f"delivered={a[0][0]:.3f}+-{a[0][1]:.3f} vs {b[0][0]:.3f}+-{b[0][1]:.3f} "
                      f"ratio={a[0][0] / b[0][0] if b[0][0] else float('nan'):.2f} "
                      f"win={a[0][0] - a[0][1] > b[0][0] + b[0][1]}")
