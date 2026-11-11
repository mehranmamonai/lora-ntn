"""Does beacon reach limit the Stage 4 controller? Tests B1-B3 fixed before the run.
Usage: summarize.py runs.txt stage4_revision_runs.txt stage4_oracle_runs.txt"""
import statistics as st
import sys
from collections import defaultdict

T_95 = {4: 2.776, 9: 2.262}
READINGS = {1: "R1", 5: "R2", 2: "R3", 3: "R4"}
HOLE_MODES = (1, 5, 3)


def rows(path):
    out = []
    with open(path) as f:
        for line in f:
            if line.startswith("RUN "):
                out.append(dict(kv.split("=", 1) for kv in line.split()[1:]))
    return out


def key(r):
    return (int(r["collision"]), int(r["dopplerLimits"]), float(r["gain"]), int(r["n"]))


def group(rs):
    g = defaultdict(dict)
    for r in rs:
        g[key(r)][int(r["seed"])] = r
    return g


def stat(runs):
    v = [float(r["received"]) / (float(r["n"]) * float(r["passes"])) for r in runs.values()]
    return st.mean(v), T_95[len(v) - 1] * st.stdev(v) / len(v) ** 0.5


def clearly_above(a, b):
    return a[0] - a[1] > b[0] + b[1]


instant = group(rows(sys.argv[1]))
low = lambda r: float(r["scintDb"]) == 7.69
beacon = group([r for r in rows(sys.argv[2]) if r["part"] == "test" and low(r)])
oracle = group([r for r in rows(sys.argv[3]) if r["part"] == "oracle" and low(r)])
missing = [k for k in instant if k not in beacon or len(beacon[k]) != 10 or len(instant[k]) != 10]
print(f"CELLS instant={len(instant)} missing_or_incomplete={len(missing)} {missing[:3]}")

b1_cells = sorted(k for k in instant if k[2] == 5.0 and k[1] in HOLE_MODES)
wins, closed = 0, []
for k in b1_cells:
    a, b = stat(instant[k]), stat(beacon[k])
    win = clearly_above(a, b)
    wins += win
    o = stat(oracle[k])[0] if k in oracle else float("nan")
    b25 = st.mean(float(r["received"]) / (float(r["n"]) * float(r["passes"])) for s, r in beacon[k].items() if s <= 25)
    i25 = st.mean(float(r["received"]) / (float(r["n"]) * float(r["passes"])) for s, r in instant[k].items() if s <= 25)
    if k in oracle and o - b25 > 1e-9:
        closed.append((i25 - b25) / (o - b25))
    print(f"B1 C{k[0]} {READINGS[k[1]]} n={k[3]} instant={a[0]:.3f}+-{a[1]:.3f} beacon={b[0]:.3f}+-{b[1]:.3f} "
          f"oracle={o:.3f} win={win}")
b1 = len(b1_cells) == 36 and wins >= 27
print(f"B1 cells={len(b1_cells)} wins={wins} needed=27 beacon_reach_is_significant_limit={b1}")
if closed:
    print(f"B2 gap_to_oracle_closed median={st.median(closed):.2f} min={min(closed):.2f} max={max(closed):.2f}")
b3_cells = [k for k in instant if k[2] == 10.0]
b3_diff = [k for k in b3_cells if clearly_above(stat(instant[k]), stat(beacon[k])) or clearly_above(stat(beacon[k]), stat(instant[k]))]
print(f"B3 cells={len(b3_cells)} clearly_different={len(b3_diff)} holds={len(b3_diff) == 0}")
for k in sorted(instant):
    print(f"RESULT C{k[0]} {READINGS[k[1]]} gain={k[2]:g} n={k[3]} instant={stat(instant[k])[0]:.3f} "
          f"beacon={stat(beacon[k])[0] if k in beacon else float('nan'):.3f}")
