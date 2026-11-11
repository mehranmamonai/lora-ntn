"""Stage 5: test the bandit against criteria ML0-ML3 fixed before the run.
Usage: summarize.py runs.txt c1_runs c1_runs c2_runs c3_runs stage4_revision_runs stage4_oracle_runs"""
import math
import statistics as st
import sys
from collections import defaultdict

T_95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262}
LOCK = {7.69: -2.0, 0.0: 0.0}
READINGS = {1: "R1", 5: "R2", 2: "R3", 3: "R4"}
HOLE_MODES = (1, 5, 3)
SEEDS = set(range(21, 31))


def rows(path, default_collision="1"):
    out = []
    with open(path) as f:
        for line in f:
            if line.startswith("RUN "):
                d = dict(kv.split("=", 1) for kv in line.split()[1:])
                d.setdefault("collision", default_collision)
                out.append(d)
    return out


def cell(r):
    return (int(r["collision"]), int(r["dopplerLimits"]), float(r["scintDb"]), float(r["gain"]), int(r["n"]))


def group(rs):
    g = defaultdict(dict)
    for r in rs:
        g[cell(r)][int(r["seed"])] = r
    return g


def delivered(r):
    return float(r["received"]) / (float(r["n"]) * float(r["passes"]))


def stat(runs):
    v = [delivered(r) for r in runs.values()]
    return st.mean(v), (T_95[len(v) - 1] * st.stdev(v) / len(v) ** 0.5 if len(v) > 1 else 0.0)


def clearly_below(a, b):
    return a[0] + a[1] < b[0] - b[1]


def is_link_baseline(r):
    return (r["policy"] == "link_only" and float(r["txProb"]) == 1.0 and int(r["seed"]) in SEEDS
            and float(r["marginDb"]) == LOCK[float(r["scintDb"])] and r.get("part") != "regress")


new = rows(sys.argv[1])
parents = [r for p in sys.argv[2:4] for r in rows(p, "1")] + rows(sys.argv[4], "2") + rows(sys.argv[5], "3")
rev = rows(sys.argv[6])
oracle_rows = rows(sys.argv[7])
link = group([r for r in parents + [x for x in rev if x["part"] == "base"] if is_link_baseline(r)])
stage4 = group([r for r in rev if r["part"] == "test" and int(r["seed"]) in SEEDS])
oracle = group([r for r in oracle_rows if r["part"] == "oracle"])
bandit = group([r for r in new if r["part"] == "test"])

# ML0
z = defaultdict(dict)
for r in new:
    if r["part"] == "z0":
        z[(r["collision"], r["n"])][r["policy"]] = r
fields = ["sent", "received", "airtimeS", "rejDoppler", "interfered", "underSens", "noDemod"]
bad = [k for k, pair in z.items() if len(pair) != 2 or any(pair["link_only"][f] != pair["controlled"][f] for f in fields)]
ml0 = len(z) == 6 and not bad
print(f"ML0 pairs={len(z)} mismatches={len(bad)} holds={ml0}")

missing = [k for k in bandit if k not in link or k not in stage4 or len(link[k]) != 10 or len(stage4[k]) != 10]
print(f"COMPARATORS cells={len(bandit)} missing_or_incomplete={len(missing)} {missing[:3]}")

# ML1
ml1_cells = [k for k in bandit if k[2] == 7.69 and k[3] == 5.0 and k[1] in HOLE_MODES]
ml1_wins = 0
for k in sorted(ml1_cells):
    a, b = stat(bandit[k]), stat(stage4[k])
    win = clearly_below(b, a)
    ml1_wins += win
    o = stat(oracle[k])[0] if k in oracle else float("nan")
    print(f"ML1 C{k[0]} {READINGS[k[1]]} n={k[4]} bandit={a[0]:.3f}+-{a[1]:.3f} stage4={b[0]:.3f}+-{b[1]:.3f} "
          f"oracle={o:.3f} win={win}")
ml1 = len(ml1_cells) == 36 and ml1_wins >= 27
print(f"ML1 cells={len(ml1_cells)} wins={ml1_wins} needed=27 holds={ml1}")

# ML2
harm = [k for k in bandit if k in link and clearly_below(stat(bandit[k]), stat(link[k]))]
for k in harm:
    print(f"ML2 harm C{k[0]} {READINGS[k[1]]} scint={k[2]:g} gain={k[3]:g} n={k[4]} "
          f"bandit={stat(bandit[k])[0]:.3f} link={stat(link[k])[0]:.3f}")
ml2 = len(bandit) == 192 and not harm and not missing
print(f"ML2 cells={len(bandit)} harmed={len(harm)} holds={ml2}")

# ML3
r3 = [k for k in bandit if k[1] == 2]
r3_worse = [k for k in r3 if k in stage4 and clearly_below(stat(bandit[k]), stat(stage4[k]))]
ml3 = len(r3) == 48 and not r3_worse
print(f"ML3 cells={len(r3)} below_stage4={len(r3_worse)} holds={ml3}")
print(f"GATE ML0={ml0} ML1={ml1} ML2={ml2} ML3={ml3} passes={ml0 and ml1 and ml2 and ml3}")

# Report: share of the Stage 4-to-oracle gap closed (seeds 21-25 means), ML1 cells.
closed = []
for k in ml1_cells:
    if k in oracle:
        s5 = st.mean(delivered(r) for s, r in bandit[k].items() if s <= 25)
        s4 = st.mean(delivered(r) for s, r in stage4[k].items() if s <= 25)
        o = stat(oracle[k])[0]
        if o - s4 > 1e-9:
            closed.append((s5 - s4) / (o - s4))
if closed:
    print(f"REPORT gap_closed median={st.median(closed):.2f} min={min(closed):.2f} max={max(closed):.2f} cells={len(closed)}")
ratios = [stat(bandit[k])[0] / stat(link[k])[0] for k in bandit if k in link and stat(link[k])[0] > 0]
print(f"REPORT bandit/link delivery median={st.median(ratios):.3f} min={min(ratios):.3f} max={max(ratios):.3f}")
for k in sorted(bandit):
    a = stat(bandit[k])
    print(f"RESULT C{k[0]} {READINGS[k[1]]} scint={k[2]:g} gain={k[3]:g} n={k[4]} bandit={a[0]:.3f}+-{a[1]:.3f} "
          f"stage4={stat(stage4[k])[0] if k in stage4 else float('nan'):.3f} "
          f"link={stat(link[k])[0] if k in link else float('nan'):.3f}")
