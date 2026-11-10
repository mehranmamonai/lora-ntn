"""Test the efficiency gate under collision model C3 against the criteria fixed before the run.
Usage: summarize.py new_runs.txt c2_runs.txt c1_runs.txt [c1_runs.txt ...]."""
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


def load(path, default_collision):
    rows = []
    with open(path) as f:
        for line in f:
            if line.startswith("RUN "):
                d = dict(kv.split("=") for kv in line.split()[1:])
                if d["policy"] == "link_only":
                    d.setdefault("collision", default_collision)
                    rows.append(d)
    return rows


def case(d):
    return (float(d["gain"]), int(d["n"]), int(d["seed"]), float(d["marginDb"]), float(d["scintDb"]),
            int(d["dopplerLimits"]), float(d["txProb"]))


new_rows = load(sys.argv[1], "1")
c2_rows = [d for d in load(sys.argv[2], "2") if d["part"] != "regress" and d["collision"] == "2"]
c1_rows = [d for path in sys.argv[3:] for d in load(path, "1") if d["part"] != "regress"]
c3_rows = [d for d in new_rows if d["collision"] == "3"]

# N1: repeats under C1 and C2 match earlier runs exactly.
index = {"1": {case(d): d for d in c1_rows}, "2": {case(d): d for d in c2_rows}}
regress = [d for d in new_rows if d["part"] == "regress"]
found = [index[d["collision"]].get(case(d)) for d in regress]
same = all(b is not None and a["received"] == b["received"] and a["sent"] == b["sent"]
           and a["airtimeS"] == b["airtimeS"] for a, b in zip(regress, found))
print(f"N1 cases={len(regress)} found={sum(b is not None for b in found)} exact_match={same}")

# N0: C3 never delivers more than C2 on identical seeds at p=1; the lock rule acts at N=5000.
c2_index = index["2"]
compared = worse = 0
for d in c3_rows:
    if d["part"] == "confirm" and float(d["txProb"]) == 1.0:
        b = c2_index.get(case(d))
        if b is not None:
            compared += 1
            worse += int(d["received"]) > int(b["received"])
lock_5000 = [int(d["lockLost"]) for d in c3_rows if int(d["n"]) == 5000]
n0 = compared > 0 and worse == 0 and min(lock_5000) > 0
print(f"N0 compared={compared} c3_above_c2={worse} min_lockLost_n5000={min(lock_5000)} "
      f"median_lockLost_n5000={st.median(lock_5000):g} holds={n0}")


def ci(values):
    return st.mean(values), T_95_DF4 * st.stdev(values) / len(values) ** 0.5


def build(rows):
    groups = defaultdict(list)
    for d in rows:
        key = (d["part"], float(d["scintDb"]), int(d["dopplerLimits"]), float(d["gain"]), int(d["n"]),
               float(d["marginDb"]), float(d["txProb"]))
        groups[key].append(d)
    out = {}
    for key, runs in groups.items():
        delivered = ci([float(r["received"]) / (float(r["n"]) * float(r["passes"])) for r in runs])
        per_seed = [float(r["airtimeS"]) / float(r["received"]) if float(r["received"]) else math.inf for r in runs]
        airtime = ci(per_seed) if all(math.isfinite(x) for x in per_seed) else (math.inf, 0.0)
        sent = sum(float(r["sent"]) for r in runs)
        interf = sum(float(r["interfered"]) for r in runs) / sent if sent else 0.0
        out[key] = (delivered, airtime, interf, len(runs))
    return out


c3 = build([d for d in c3_rows if d["part"] != "regress"])
c2 = build(c2_rows)
c1 = build(c1_rows)
for key in sorted(c3):
    part, scint, mode, g, n, m, p = key
    dv, air, interf, runs = c3[key]
    print(f"RESULT collision=C3 part={part} scint={scint:g} reading={READINGS[mode]} gain={g:g} n={n} margin={m:g} "
          f"p={p:g} runs={runs} delivered={dv[0]:.3f}+-{dv[1]:.3f} air_per_delivered={air[0]:.2f}+-{air[1]:.2f} "
          f"lost_interf={interf:.3f}")


def M(part, scint, mode, g, n, p):
    return c3[(part, scint, mode, g, n, LOCK[scint], p)]


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
                print(f"N2 scint={scint:g} {READINGS[mode]} gain={g:g} no_candidate win=False")
                continue
            chosen = min(ok, key=lambda p: M("search", scint, mode, g, 5000, p)[1][0])
            a = M("confirm", scint, mode, g, 5000, chosen)
            b = M("confirm", scint, mode, g, 5000, 1.0)
            cheaper = a[1][0] + a[1][1] < b[1][0] - b[1][1]
            win = cheaper and not clearly_below(a[0], b[0])
            wins += win
            by_reading[mode] += win
            print(f"N2 scint={scint:g} {READINGS[mode]} gain={g:g} p={chosen:g} "
                  f"delivered={a[0][0]:.3f}+-{a[0][1]:.3f} vs {b[0][0]:.3f}+-{b[0][1]:.3f} "
                  f"air={a[1][0]:.2f}+-{a[1][1]:.2f} vs {b[1][0]:.2f}+-{b[1][1]:.2f} "
                  f"air_ratio={a[1][0] / b[1][0]:.2f} win={win}")
n2 = wins >= 8
print(f"N2 wins={wins}/16 needed=8 holds={n2}")
print("N5 " + " ".join(f"{READINGS[m]}={by_reading[m]}/4" for m in MODES))

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
    print(f"N3 p={p:g} not_clearly_worse " + " ".join(f"n{n}={counts[n]}/16" for n in NS) + f" serves_all={serves}")
n3 = not serves_all
print(f"N3 holds={n3}")
print(f"GATE_C3 N2={n2} N3={n3} passes={n2 and n3} sanity_N0={n0} N1={same}")

for scint in SCINTS:
    for mode in MODES:
        for g in GAINS:
            for n in NS:
                key = ("confirm", scint, mode, g, n, LOCK[scint], 1.0)
                parts = []
                for name, table in (("c1", c1), ("c2", c2), ("c3", c3)):
                    if key in table:
                        dv, _, interf, _ = table[key]
                        parts.append(f"delivered_{name}={dv[0]:.3f}+-{dv[1]:.3f} interf_{name}={interf:.3f}")
                    else:
                        parts.append(f"{name}_missing")
                print(f"N4 scint={scint:g} {READINGS[mode]} gain={g:g} n={n} " + " ".join(parts))
