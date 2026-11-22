"""Re-review (Rev 1): static cut-off safety (N-0), cross-validated fixed cut-off (N-1), share signal (N-3).
Usage: summarize.py <experiments dir> <new runs.txt>

Criteria and readings fixed before the run; paired per-seed 95% t-intervals on seeds 21-30.
  K0  fixed 90 deg reproduces link-only exactly on the check pairs.
  K1  For static 40 and 50 deg: count scenarios of 192 significantly below link-only, by group
      (low-latitude 5 dBi with SF12 Doppler loss: R1 R2 R4; low-latitude 5 dBi R3; low-latitude 10 dBi;
      mid-latitude). Reading: if static 40 deg is significantly below link-only in at least one
      scenario outside the Doppler-loss group, a static cut-off is not safe under an unknown limit and
      the controller (0 of 192 below link-only) is the safe choice; if in none, a static 40 deg cut-off
      is harmless in this model and the paper is reframed around the attribution study.
      Also reported: static 40 deg against the controller, paired, per group.
  K2  Cross-validated fixed cut-off: per scenario, the cut-off with the highest mean delivery on
      seeds 16-20, evaluated on 21-30. Median CV/oracle over the 24 distinct scenarios, read with the
      same thresholds as before (<= 0.80 threshold class is the limit, >= 0.90 the learning rule).
  K3  Link-only, C3, low latitude 5 dBi, N=500 and 2000, seeds 21-25: SF12 sent, Doppler-lost and
      received per elevation bin under R1 and R3 (what the share rule sees).
"""
import math
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

T = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262}
READ = {1: "R1", 5: "R2", 2: "R3", 3: "R4"}
LOCK = {7.69: -2.0, 0.0: 0.0}
TEST = range(21, 31)
E = Path(sys.argv[1])


def rows(path, dc="1"):
    out = []
    for line in open(path):
        if line.startswith("RUN "):
            d = dict(kv.split("=", 1) for kv in line.split()[1:])
            d.setdefault("collision", dc)
            out.append(d)
    return out


def key(r):
    return (int(r["collision"]), int(r["dopplerLimits"]), float(r["scintDb"]), float(r["gain"]), int(r["n"]))


def deliv(r):
    return float(r["received"]) / (float(r["n"]) * float(r["passes"]))


def ci(d):
    return st.mean(d), (T[len(d) - 1] * st.stdev(d) / math.sqrt(len(d)) if len(d) > 1 else 0.0)


def paired(a, b):
    return ci([deliv(a[s]) - deliv(b[s]) for s in TEST])


def m(d, seeds=TEST):
    return st.mean(deliv(d[s]) for s in seeds)


def group(k):
    if k[2] == 7.69 and k[3] == 5:
        return "doppler" if k[1] in (1, 5, 3) else "lowlat5_R3"
    return "lowlat10" if k[2] == 7.69 else "midlat"


new = rows(sys.argv[2])
rev = rows(E / "stage4-revision/data/runs.txt")
hind = rows(E / "hindsight-threshold/data/runs.txt")
base_rows = (rows(E / "efficiency-bound/data/runs.txt", "1") + rows(E / "load-control-bound/data/runs.txt", "1")
             + rows(E / "collision-model-gate/data/runs.txt", "2") + rows(E / "collision-locking-gate/data/runs.txt", "3")
             + [r for r in rev if r["part"] == "base"])
link, ctrl, orc = (defaultdict(dict) for _ in range(3))
fixed = defaultdict(lambda: defaultdict(dict))
tune = defaultdict(lambda: defaultdict(dict))
for r in base_rows:
    if (r["policy"] == "link_only" and float(r["txProb"]) == 1.0 and int(r["seed"]) in TEST
            and float(r["marginDb"]) == LOCK[float(r["scintDb"])] and r.get("part") != "regress"):
        link[key(r)][int(r["seed"])] = r
for r in rev:
    if r["part"] == "test":
        ctrl[key(r)][int(r["seed"])] = r
for r in [x for x in rows(E / "stage4-controller/data/runs.txt") if x["part"] == "oracle"] + \
         [x for x in hind if x["part"] == "oracle"]:
    if int(r["seed"]) in TEST:
        orc[key(r)][int(r["seed"])] = r
for r in hind + new:
    if r["part"] == "fixed":
        fixed[key(r)][int(float(r["thetaFixedDeg"]))][int(r["seed"])] = r
for r in new:
    if r["part"] == "cvtune":
        tune[key(r)][int(float(r["thetaFixedDeg"]))][int(r["seed"])] = r

# K0
chk = defaultdict(dict)
for r in new:
    if r["part"] == "check":
        chk[(r["collision"], r["n"])][r["policy"]] = r
fields = ["sent", "received", "airtimeS", "rejDoppler", "interfered", "underSens", "noDemod"]
bad = [k for k, p in chk.items() if len(p) != 2 or any(p["link_only"][f] != p["controlled"][f] for f in fields)]
print(f"K0 pairs={len(chk)} mismatches={len(bad)} holds={len(chk) == 4 and not bad}")

# K1
keys = sorted(ctrl)
print(f"K1 scenarios={len(keys)}")
groups = ("doppler", "lowlat5_R3", "lowlat10", "midlat")
outside_harm40 = 0
for th in (40, 50):
    for g in groups:
        ks = [k for k in keys if group(k) == g]
        below = above = vs_ctrl_below = vs_ctrl_above = 0
        ratios = []
        missing = [k for k in ks if len(fixed[k].get(th, {})) != 10 or len(link[k]) != 10]
        for k in ks:
            if k in missing:
                continue
            d = paired(fixed[k][th], link[k])
            below += d[0] + d[1] < 0
            above += d[0] - d[1] > 0
            c = paired(fixed[k][th], ctrl[k])
            vs_ctrl_below += c[0] + c[1] < 0
            vs_ctrl_above += c[0] - c[1] > 0
            ratios.append(m(fixed[k][th]) / m(link[k]))
            if d[0] + d[1] < 0:
                print(f"K1 harm theta={th} {group(k)} C{k[0]} {READ[k[1]]} {'low' if k[2] == 7.69 else 'mid'} "
                      f"{k[3]:g}dBi N={k[4]} ratio={m(fixed[k][th]) / m(link[k]):.3f} diff={d[0]:+.4f}+-{d[1]:.4f}")
        if th == 40 and g != "doppler":
            outside_harm40 += below
        print(f"K1 theta={th} group={g} scenarios={len(ks)} missing={len(missing)} below_link={below} above_link={above} "
              f"ratio_to_link median={st.median(ratios) if ratios else float('nan'):.3f} "
              f"min={min(ratios) if ratios else float('nan'):.3f} below_controller={vs_ctrl_below} above_controller={vs_ctrl_above}")
print(f"K1 static40_harm_outside_doppler_group={outside_harm40} reading="
      f"{'static cut-off NOT safe; controller is the safe choice' if outside_harm40 else 'static 40 deg harmless in this model; reframe'}")

# K2
cv_o, cv_c, out = [], [], []
for k in sorted(tune):
    if k[1] not in (1, 5):
        continue
    th = max(tune[k], key=lambda t: m(tune[k][t], range(16, 21)))
    cv = m(fixed[k][th])
    best = max(m(v) for v in fixed[k].values() if len(v) == 10)
    o = m(orc[k])
    cv_o.append(cv / o)
    cv_c.append(cv / m(ctrl[k]))
    out.append(f"K2 C{k[0]} {READ[k[1]]} N={k[4]} cv_theta={th} cv={cv:.4f} hindsight={best:.4f} oracle={o:.4f} "
               f"cv/oracle={cv / o:.3f} cv/controller={cv / m(ctrl[k]):.3f}")
print("\n".join(out))
med = st.median(cv_o)
reading = "threshold class is the limit" if med <= 0.80 else "learning rule is the limit" if med >= 0.90 else "both contribute"
print(f"K2 scenarios={len(cv_o)} median cv/oracle={med:.3f} range={min(cv_o):.3f}-{max(cv_o):.3f} "
      f"median cv/controller={st.median(cv_c):.3f} reading='{reading}'")

# K3
acc = defaultdict(lambda: [[0] * 7, [0] * 7, [0] * 7])
for r in new:
    if r["part"] == "truth":
        a = acc[(READ[int(r["dopplerLimits"])], int(r["n"]))]
        for i, f in enumerate(("sf12SentBin", "sf12DopplerBin", "sf12RecvBin")):
            for b, v in enumerate(r[f].split(",")):
                a[i][b] += int(v)
for (rd, n), (sent, dop, recv) in sorted(acc.items()):
    cells = " ".join(f"{20 + 10 * b}-{30 + 10 * b}:{recv[b]}/{sent[b]}({dop[b]}dop)" for b in range(7))
    print(f"K3 {rd} N={n} SF12 received/sent (Doppler-lost) by bin: {cells}")
