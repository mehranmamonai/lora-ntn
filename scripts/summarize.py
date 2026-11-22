"""Revised SF12 cut-off rule: choose (share-frac, min-bin) on seeds 16-20, then test on seeds 21-30.
Usage: summarize.py choose runs.txt
       summarize.py final runs.txt <experiments dir>

Choice rule (fixed before the run): among combinations whose mean delivery is at least 0.98 of
link-only in every tuning scenario (R1, R2, R3 at low latitude 5 dBi, plus mid-latitude 5 dBi and
low-latitude 10 dBi under R1), take the highest median ratio to link-only over the R1 and R2
tuning scenarios; ties go to the old rule (0.5, 2), then to the lower share-frac. If no
combination is harmless, the old rule is kept.

Criteria (fixed before the run), seeds 21-30, paired per-seed 95% t-intervals:
  G0  the old rule (0.5, 2) reproduces ae2d1534 exactly on the two regression runs.
  G1  in the 36 scenarios with SF12 Doppler loss (low latitude, 5 dBi, R1 R2 R4), the new rule
      delivers significantly more than the old rule in at least 27, and its median delivery over
      the 24 distinct scenarios is at least 0.80 of the oracle.
  G2  the new rule is never significantly below link-only in any of the 192 scenarios.
  Reported, not gated: share of the gap to the hindsight-best fixed cut-off closed; active scenarios.
"""
import math
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

T = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262}
READ = {1: "R1", 5: "R2", 2: "R3", 3: "R4"}
LOCK = {7.69: -2.0, 0.0: 0.0}


def rows(path, default_collision="1"):
    out = []
    for line in open(path):
        if line.startswith("RUN "):
            d = dict(kv.split("=", 1) for kv in line.split()[1:])
            d.setdefault("collision", default_collision)
            out.append(d)
    return out


def deliv(r):
    return float(r["received"]) / (float(r["n"]) * float(r["passes"]))


def ci(d):
    m = st.mean(d)
    return m, (T[len(d) - 1] * st.stdev(d) / math.sqrt(len(d)) if len(d) > 1 else 0.0)


def key(r):
    return (int(r["collision"]), int(r["dopplerLimits"]), float(r["scintDb"]), float(r["gain"]), int(r["n"]))


def name(k):
    return f"C{k[0]} {READ[k[1]]} {'low' if k[2] == 7.69 else 'mid'} {k[3]:g}dBi N={k[4]}"


if sys.argv[1] == "choose":
    rs = [r for r in rows(sys.argv[2]) if r["part"] == "tune"]
    link = defaultdict(dict)
    combos = defaultdict(lambda: defaultdict(dict))
    for r in rs:
        k = key(r)
        if r["policy"] == "link_only":
            link[k][r["seed"]] = r
        else:
            combos[(float(r["frac"]), int(r["minbin"]))][k][r["seed"]] = r
    scored = []
    for c, by in sorted(combos.items()):
        ratios = {k: st.mean(deliv(x) for x in v.values()) / st.mean(deliv(x) for x in link[k].values()) for k, v in by.items()}
        target = [v for k, v in ratios.items() if k[1] in (1, 5) and k[2] == 7.69 and k[3] == 5]
        worst = min(ratios.values())
        obj = st.median(target)
        ok = worst >= 0.98
        tie = (c == (0.5, 2), -c[0])
        scored.append((ok, round(obj, 6), tie, c))
        print(f"TUNE frac={c[0]} minbin={c[1]} scenarios={len(ratios)} target_median={obj:.4f} worst={worst:.4f} "
              f"harmless={ok} worst_at={name(min(ratios, key=ratios.get))}")
    best = max(scored)
    if not best[0]:  # no harmless combination: keep the old rule
        best = next(x for x in scored if x[3] == (0.5, 2))
    print(f"CHOSEN frac={best[3][0]} minbin={best[3][1]} target_median={best[1]:.4f} harmless={best[0]}")
    sys.exit(0)

new = rows(sys.argv[2])
E = Path(sys.argv[3])
rev = rows(E / "stage4-revision/data/runs.txt")
hind = rows(E / "hindsight-threshold/data/runs.txt")
base_rows = (rows(E / "efficiency-bound/data/runs.txt", "1") + rows(E / "load-control-bound/data/runs.txt", "1")
             + rows(E / "collision-model-gate/data/runs.txt", "2") + rows(E / "collision-locking-gate/data/runs.txt", "3")
             + [r for r in rev if r["part"] == "base"])
SEEDS = set(range(21, 31))
link, old, ctl, orc = (defaultdict(dict) for _ in range(4))
best_fixed = defaultdict(lambda: defaultdict(dict))
for r in base_rows:
    if (r["policy"] == "link_only" and float(r["txProb"]) == 1.0 and int(r["seed"]) in SEEDS
            and float(r["marginDb"]) == LOCK[float(r["scintDb"])] and r.get("part") != "regress"):
        link[key(r)][int(r["seed"])] = r
for r in rev:
    if r["part"] == "test":
        old[key(r)][int(r["seed"])] = r
for r in [x for x in rows(E / "stage4-controller/data/runs.txt") if x["part"] == "oracle"] + \
         [x for x in hind if x["part"] == "oracle"]:
    if int(r["seed"]) in SEEDS:
        orc[key(r)][int(r["seed"])] = r
for r in hind:
    if r["part"] == "fixed":
        best_fixed[key(r)][int(float(r["thetaFixedDeg"]))][int(r["seed"])] = r
for r in new:
    if r["part"] == "test":
        ctl[key(r)][int(r["seed"])] = r
chosen = next(((r["frac"], r["minbin"]) for r in new if r["part"] == "test"), ("?", "?"))
print(f"CHOSEN frac={chosen[0]} minbin={chosen[1]}")

# G0
fields = ["sent", "received", "airtimeS", "rejDoppler", "interfered", "underSens", "noDemod"]
reg = [r for r in new if r["part"] == "regress"]
mism = [r["n"] for r in reg if any(r[f] != old[key(r)][21][f] for f in fields)]
g0 = len(reg) == 2 and not mism
print(f"G0 regress_runs={len(reg)} mismatches={len(mism)} holds={g0}")


def paired(a, b):
    return ci([deliv(a[s]) - deliv(b[s]) for s in sorted(SEEDS)])


def m(d):
    return st.mean(deliv(r) for r in d.values())


missing = [k for k in ctl if len(ctl[k]) != 10 or len(link[k]) != 10 or len(old[k]) != 10]
print(f"SCENARIOS tested={len(ctl)} incomplete={len(missing)} {[name(k) for k in missing[:3]]}")

# G2 and activity
harm, active = [], 0
for k in sorted(ctl):
    same = all(ctl[k][s]["received"] == link[k][s]["received"] and ctl[k][s]["sent"] == link[k][s]["sent"] for s in SEEDS)
    active += not same
    d = paired(ctl[k], link[k])
    if d[0] + d[1] < 0:
        harm.append((k, d))
for k, d in harm:
    print(f"G2 harm {name(k)} diff={d[0]:+.4f}+-{d[1]:.4f}")
g2 = not harm and len(ctl) == 192 and not missing
print(f"G2 scenarios={len(ctl)} significantly_below_link={len(harm)} active={active} holds={g2}")

# G1
dop36 = [k for k in sorted(ctl) if k[1] in (1, 5, 3) and k[2] == 7.69 and k[3] == 5]
better = 0
print("\nPER SCENARIO (Doppler-loss scenarios; delivery packets/device/pass)")
print(f"{'scenario':30s} {'link':>6s} {'old':>6s} {'new':>6s} {'hind':>6s} {'oracle':>6s} {'new/link':>8s} {'new-old paired':>18s} {'new/O':>6s} {'gapH':>6s}")
uniq_no, gap_h = [], []
for k in dop36:
    L, Oc, N = m(link[k]), m(old[k]), m(ctl[k])
    d = paired(ctl[k], old[k])
    better += d[0] - d[1] > 0
    kk = (k[0], 1 if k[1] == 3 else k[1], k[2], k[3], k[4])
    O = m(orc[kk]) if len(orc[kk]) == 10 else float("nan")
    H = max(m(v) for v in best_fixed[kk].values()) if best_fixed[kk] else float("nan")
    gh = (N - Oc) / (H - Oc) if H != Oc else float("nan")
    if k[1] in (1, 5):
        uniq_no.append(N / O)
        gap_h.append(gh)
    print(f"{name(k):30s} {L:6.4f} {Oc:6.4f} {N:6.4f} {H:6.4f} {O:6.4f} {N / L:8.3f} {d[0]:+.4f}+-{d[1]:.4f} {N / O:6.3f} {gh:6.2f}")
need = 27
med_o = st.median(uniq_no)
g1 = better >= need and med_o >= 0.80
print(f"\nG1 doppler_scenarios={len(dop36)} new_significantly_above_old={better} needed={need} "
      f"median_new_over_oracle={med_o:.3f} (range {min(uniq_no):.3f}-{max(uniq_no):.3f}) holds={g1}")
rat = [m(ctl[k]) / m(link[k]) for k in dop36]
up = sum(paired(ctl[k], link[k])[0] - paired(ctl[k], link[k])[1] > 0 for k in dop36)
print(f"REPORT new/link over 36: median={st.median(rat):.3f} range={min(rat):.3f}-{max(rat):.3f} significantly_above_link={up}")
print(f"REPORT share of old-to-hindsight gap closed (24 distinct): median={st.median(gap_h):.2f} range={min(gap_h):.2f}-{max(gap_h):.2f}")
print(f"GATE G0={g0} G1={g1} G2={g2} passes={g0 and g1 and g2}")
