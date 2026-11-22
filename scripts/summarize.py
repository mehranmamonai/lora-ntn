"""Review revision: hindsight-optimal fixed SF12 cut-off, exploration ablation and 10-seed oracle.
Usage: summarize.py <experiments dir> <new runs.txt>

Criteria fixed before the run (24 unique scenarios: low latitude, 5 dBi, C1-C3, R1/R2, N=100-5000;
R4 equals R1 in this setting). C = Stage 4 controller (ae2d1534, eps 0.1), H = best fixed theta per
scenario chosen on the test seeds themselves (an optimistic bound for any single threshold),
O = oracle, all on seeds 21-30, delivery in packets per device per pass.
  F0  fixed theta = 90 reproduces link-only exactly on all check pairs.
  F1  attribution of the gap to the oracle, from the median of H/O over scenarios:
      <= 0.80: the single-threshold class is the limit (paper's diagnosis supported);
      >= 0.90: the learning rule is the limit (diagnosis rejected);
      otherwise both contribute; report the share of the C-to-O gap that H closes.
  F2  learning rule against the hindsight threshold: paired 95% CI of C - H per scenario; count
      scenarios where C is clearly below H.
  F3  exploration cost: paired 95% CI of (eps 0) - (eps 0.1) per scenario, and the share of the
      C-to-O gap it closes.
"""
import math
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

T = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262}
READ = {1: "R1", 5: "R2"}
SEEDS = set(range(21, 31))
E = Path(sys.argv[1])


def rows(path, default_collision="1"):
    out = []
    for line in open(path):
        if line.startswith("RUN "):
            d = dict(kv.split("=", 1) for kv in line.split()[1:])
            d.setdefault("collision", default_collision)
            out.append(d)
    return out


def in_scope(r):
    return (float(r["scintDb"]) == 7.69 and float(r["gain"]) == 5 and int(r["dopplerLimits"]) in READ
            and int(r["seed"]) in SEEDS)


def key(r):
    return (int(r["collision"]), int(r["dopplerLimits"]), int(r["n"]))


def deliv(r):
    return float(r["received"]) / (float(r["n"]) * float(r["passes"]))


def ci(d):
    m = st.mean(d)
    h = T[len(d) - 1] * st.stdev(d) / math.sqrt(len(d)) if len(d) > 1 else 0.0
    return m, h


def name(k):
    return f"C{k[0]} {READ[k[1]]} N={k[2]}"


new = rows(sys.argv[2])
rev = rows(E / "stage4-revision/data/runs.txt")
old_oracle = [r for r in rows(E / "stage4-controller/data/runs.txt") if r["part"] == "oracle"]
base_rows = (rows(E / "efficiency-bound/data/runs.txt", "1") + rows(E / "load-control-bound/data/runs.txt", "1")
             + rows(E / "collision-model-gate/data/runs.txt", "2") + rows(E / "collision-locking-gate/data/runs.txt", "3")
             + [r for r in rev if r["part"] == "base"])

link, ctrl, oracle, eps0 = (defaultdict(dict) for _ in range(4))
fixed = defaultdict(lambda: defaultdict(dict))
for r in base_rows:
    if (r["policy"] == "link_only" and float(r["txProb"]) == 1.0 and float(r["marginDb"]) == -2.0
            and r.get("part") != "regress" and in_scope(r)):
        link[key(r)][int(r["seed"])] = r
for r in rev:
    if r["part"] == "test" and in_scope(r):
        ctrl[key(r)][int(r["seed"])] = r
for r in old_oracle + [x for x in new if x["part"] == "oracle"]:
    if in_scope(r):
        oracle[key(r)][int(r["seed"])] = r
for r in new:
    if r["part"] == "eps0" and in_scope(r):
        eps0[key(r)][int(r["seed"])] = r
    if r["part"] == "fixed" and in_scope(r):
        fixed[key(r)][int(float(r["thetaFixedDeg"]))][int(r["seed"])] = r

# F0
chk = defaultdict(dict)
for r in new:
    if r["part"] == "check":
        chk[(r["collision"], r["n"])][r["policy"]] = r
fields = ["sent", "received", "airtimeS", "rejDoppler", "interfered", "underSens", "noDemod"]
bad = [k for k, p in chk.items() if len(p) != 2 or any(p["link_only"][f] != p["controlled"][f] for f in fields)]
f0 = len(chk) == 4 and not bad
print(f"F0 pairs={len(chk)} mismatches={len(bad)} holds={f0}")

keys = sorted(ctrl)
complete = [k for k in keys if all(len(d[k]) == 10 for d in (link, ctrl, oracle, eps0))
            and len(fixed[k]) == 7 and all(len(v) == 10 for v in fixed[k].values())]
print(f"SCENARIOS in_scope={len(keys)} complete={len(complete)} missing={[name(k) for k in keys if k not in complete]}")


def m(d):
    return st.mean(deliv(r) for r in d.values())


def paired(a, b):
    return ci([deliv(a[s]) - deliv(b[s]) for s in sorted(SEEDS)])


print("\nPER SCENARIO (delivery, packets/device/pass, mean of seeds 21-30)")
print(f"{'scenario':14s} {'link':>6s} {'ctrl':>6s} {'eps0':>6s} {'best':>6s} {'th*':>4s} {'oracle':>6s} "
      f"{'C/O':>5s} {'H/O':>5s} {'gapH':>6s} {'C-H paired CI':>18s} {'eps0-C paired CI':>18s} {'gapE':>6s}  delivery by theta 20..80")
ho, co, gap_h, gap_e, c_below, e_above, e_below, best_thetas = [], [], [], [], 0, 0, 0, []
for k in complete:
    L, C, O, Z = m(link[k]), m(ctrl[k]), m(oracle[k]), m(eps0[k])
    by_theta = {t: m(fixed[k][t]) for t in sorted(fixed[k])}
    th = max(by_theta, key=by_theta.get)
    H = by_theta[th]
    best_thetas.append(th)
    dch = paired(ctrl[k], fixed[k][th])
    dze = paired(eps0[k], ctrl[k])
    gh = (H - C) / (O - C) if O != C else float("nan")
    ge = (Z - C) / (O - C) if O != C else float("nan")
    ho.append(H / O)
    co.append(C / O)
    gap_h.append(gh)
    gap_e.append(ge)
    c_below += dch[0] + dch[1] < 0
    e_above += dze[0] - dze[1] > 0
    e_below += dze[0] + dze[1] < 0
    print(f"{name(k):14s} {L:6.4f} {C:6.4f} {Z:6.4f} {H:6.4f} {th:4d} {O:6.4f} {C / O:5.3f} {H / O:5.3f} {gh:6.2f} "
          f"{dch[0]:+.4f}+-{dch[1]:.4f} {dze[0]:+.4f}+-{dze[1]:.4f} {ge:6.2f}  "
          + " ".join(f"{v:.4f}" for v in by_theta.values()))

med_ho = st.median(ho)
reading = ("single-threshold class is the limit" if med_ho <= 0.80 else
           "learning rule is the limit" if med_ho >= 0.90 else "both contribute")
print(f"\nF1 median C/O={st.median(co):.3f} (range {min(co):.3f}-{max(co):.3f}) median H/O={med_ho:.3f} "
      f"(range {min(ho):.3f}-{max(ho):.3f}) median_gap_closed_by_H={st.median(gap_h):.2f} "
      f"(range {min(gap_h):.2f}-{max(gap_h):.2f}) reading='{reading}'")
print(f"F2 scenarios={len(complete)} controller_clearly_below_hindsight={c_below}")
print(f"F3 eps0_clearly_above={e_above} clearly_below={e_below} median_gap_closed_by_eps0={st.median(gap_e):.2f} "
      f"(range {min(gap_e):.2f}-{max(gap_e):.2f})")
print(f"F1 best theta per scenario: " + ", ".join(f"{name(k)}:{t}" for k, t in zip(complete, best_thetas)))
glob = {t: st.mean(m(fixed[k][t]) / m(oracle[k]) for k in complete) for t in range(20, 90, 10)}
print("F1 single global theta, mean fixed/oracle: " + " ".join(f"{t}:{v:.3f}" for t, v in glob.items()))
