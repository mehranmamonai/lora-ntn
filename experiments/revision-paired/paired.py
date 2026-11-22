"""Paired per-seed reanalysis of the Stage 4 controller against link-only (review items DA-C1, M1-1, M1-3).

Link-only and the controller run on the same seeds 21-30, so each scenario gives ten paired differences.
Reports, for every scenario, the mean paired difference in delivery (packets/device/pass) with a 95% t-interval,
a paired t-test, Holm and Benjamini-Hochberg corrections across the active scenarios, a sign test across
scenarios, and Doppler-lost packets per device per pass (a count, so withholding attempts cannot shrink a
denominator). Usage: paired.py <experiments dir> > paired.txt
"""
import math
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

from scipy import stats

E = Path(sys.argv[1])
LOCK = {7.69: -2.0, 0.0: 0.0}
READ = {1: "R1", 5: "R2", 2: "R3", 3: "R4"}
SEEDS = set(range(21, 31))


def rows(path, default_collision):
    out = []
    for line in open(path):
        if line.startswith("RUN "):
            d = dict(kv.split("=", 1) for kv in line.split()[1:])
            d.setdefault("collision", default_collision)
            out.append(d)
    return out


def key(r):
    return (int(r["collision"]), int(r["dopplerLimits"]), float(r["scintDb"]), float(r["gain"]), int(r["n"]))


def is_base(r):
    return (r["policy"] == "link_only" and float(r["txProb"]) == 1.0 and int(r["seed"]) in SEEDS
            and float(r["marginDb"]) == LOCK[float(r["scintDb"])] and r.get("part") != "regress")


def deliv(r):
    return float(r["received"]) / (float(r["n"]) * float(r["passes"]))


def dop(r):
    return float(r["rejDoppler"]) / (float(r["n"]) * float(r["passes"]))


def share(r):
    return float(r["rejDoppler"]) / float(r["sent"]) if float(r["sent"]) else 0.0


rev = rows(E / "stage4-revision/data/runs.txt", "1")
base_rows = (rows(E / "efficiency-bound/data/runs.txt", "1") + rows(E / "load-control-bound/data/runs.txt", "1")
             + rows(E / "collision-model-gate/data/runs.txt", "2") + rows(E / "collision-locking-gate/data/runs.txt", "3")
             + [r for r in rev if r["part"] == "base"])
base, ctrl = defaultdict(dict), defaultdict(dict)
for r in base_rows:
    if is_base(r):
        base[key(r)][int(r["seed"])] = r
for r in rev:
    if r["part"] == "test":
        ctrl[key(r)][int(r["seed"])] = r


def withheld(c, b):
    """SF12 attempts the controller withheld = extra skipped attempts relative to link-only on the same seed."""
    return int(c["skipped"]) - int(b["skipped"])


def label(k):
    lat = "low" if k[2] == 7.69 else "mid"
    return f"C{k[0]} {READ[k[1]]} {lat} {k[3]:g}dBi N={k[4]}"


def tci(d):
    m = st.mean(d)
    if len(d) < 2 or st.stdev(d) == 0:
        return m, 0.0, (1.0 if m == 0 else 0.0)
    h = stats.t.ppf(0.975, len(d) - 1) * st.stdev(d) / math.sqrt(len(d))
    return m, h, stats.ttest_1samp(d, 0.0).pvalue


identical = active = 0
recs = []
for k in sorted(ctrl):
    seeds = sorted(set(ctrl[k]) & set(base[k]))
    assert len(seeds) == 10, (k, seeds)
    pairs = [(ctrl[k][s], base[k][s]) for s in seeds]
    same = all(c["received"] == b["received"] and c["sent"] == b["sent"] and c["rejDoppler"] == b["rejDoppler"]
               for c, b in pairs)
    wh = [withheld(c, b) for c, b in pairs]
    if same:
        identical += 1
        continue
    active += 1
    dd = [deliv(c) - deliv(b) for c, b in pairs]
    dl = [dop(c) - dop(b) for c, b in pairs]
    m, h, p = tci(dd)
    ml, hl, pl = tci(dl)
    lb = st.mean(deliv(b) for _, b in pairs)
    recs.append(dict(k=k, m=m, h=h, p=p, link=lb, ctrl=st.mean(deliv(c) for c, _ in pairs),
                     pos=sum(x > 0 for x in dd), neg=sum(x < 0 for x in dd), ml=ml, hl=hl, pl=pl,
                     sh_l=st.mean(share(b) for _, b in pairs), sh_c=st.mean(share(c) for c, _ in pairs),
                     wh=st.mean(wh), sf12hi=None))

print(f"SCENARIOS total={len(ctrl)} identical_to_link_only={identical} active={active}")

# multiple-comparison corrections over the active scenarios
ps = [r["p"] for r in recs]
order = sorted(range(len(ps)), key=lambda i: ps[i])
holm = [1.0] * len(ps)
running = 0.0
for rank, i in enumerate(order):
    running = max(running, min(1.0, (len(ps) - rank) * ps[i]))
    holm[i] = running
bh = [1.0] * len(ps)
prev = 1.0
for rank in range(len(ps) - 1, -1, -1):
    i = order[rank]
    prev = min(prev, ps[i] * len(ps) / (rank + 1))
    bh[i] = prev
for r, hp, bp in zip(recs, holm, bh):
    r["holm"], r["bh"] = hp, bp

print("\nPAIRED delivery difference controller - link-only (packets/device/pass), 10 paired seeds")
print(f"{'scenario':34s} {'link':>6s} {'ctrl':>6s} {'diff':>8s} {'95% CI':>19s} {'ratio':>6s} {'+/-':>5s} "
      f"{'p':>7s} {'Holm':>6s} {'BH':>6s} | {'dopLost/dev/pass diff':>22s} | share link->ctrl | withheld/run")
for r in recs:
    lo, hi = r["m"] - r["h"], r["m"] + r["h"]
    print(f"{label(r['k']):34s} {r['link']:6.4f} {r['ctrl']:6.4f} {r['m']:+8.4f} [{lo:+.4f},{hi:+.4f}] "
          f"{r['ctrl'] / r['link']:6.3f} {r['pos']:2d}/{r['neg']:<2d} {r['p']:7.4f} {r['holm']:6.3f} {r['bh']:6.3f} | "
          f"{r['ml']:+.4f}+-{r['hl']:.4f} | {100 * r['sh_l']:5.1f}->{100 * r['sh_c']:5.1f}% | {r['wh']:7.1f}")

pos = sum(r["m"] > 0 for r in recs)
neg = sum(r["m"] < 0 for r in recs)
sign_p = stats.binomtest(pos, pos + neg, 0.5, alternative="two-sided").pvalue
ci_pos = sum(r["m"] - r["h"] > 0 for r in recs)
ci_neg = sum(r["m"] + r["h"] < 0 for r in recs)
print(f"\nSUMMARY active={len(recs)} mean_diff_positive={pos} negative={neg} sign_test_p={sign_p:.2e}")
print(f"SUMMARY paired_CI_above_zero={ci_pos} below_zero={ci_neg} "
      f"holm<0.05={sum(r['holm'] < 0.05 for r in recs)} bh<0.05={sum(r['bh'] < 0.05 for r in recs)}")
rat = [r["ctrl"] / r["link"] for r in recs]
print(f"SUMMARY delivery ratio ctrl/link median={st.median(rat):.3f} min={min(rat):.3f} max={max(rat):.3f}")
dl_lower = sum(r["ml"] + r["hl"] < 0 for r in recs)
print(f"SUMMARY doppler_lost_per_device_pass paired_CI_below_zero={dl_lower} of {len(recs)}")
for coll in (1, 2, 3):
    sub = [r for r in recs if r["k"][0] == coll]
    print(f"SUMMARY C{coll} active={len(sub)} CI_above_zero={sum(r['m'] - r['h'] > 0 for r in sub)} "
          f"holm<0.05={sum(r['holm'] < 0.05 for r in sub)}")

# The 36 scenarios with SF12 Doppler loss (R1, R2, R4 at low latitude, 5 dBi) and the 24 unique ones
# (R4 reproduces R1 exactly in this setting, checked below), with Holm re-applied within each family.
def family(sub, tag):
    ps = sorted(r["p"] for r in sub)
    holm_sig, running = 0, 0.0
    for rank, p in enumerate(ps):
        running = max(running, min(1.0, (len(ps) - rank) * p))
        holm_sig += running < 0.05
    pos = sum(r["m"] > 0 for r in sub)
    sp = stats.binomtest(pos, len(sub), 0.5).pvalue
    rat = [r["ctrl"] / r["link"] for r in sub]
    print(f"FAMILY {tag} n={len(sub)} CI_above_zero={sum(r['m'] - r['h'] > 0 for r in sub)} "
          f"CI_below_zero={sum(r['m'] + r['h'] < 0 for r in sub)} holm<0.05={holm_sig} mean_positive={pos} "
          f"sign_p={sp:.1e} ratio median={st.median(rat):.3f} range={min(rat):.3f}-{max(rat):.3f} "
          f"dopLost_CI_below={sum(r['ml'] + r['hl'] < 0 for r in sub)}")


dop36 = [r for r in recs if r["k"][1] in (1, 5, 3)]
r1 = {r["k"][:1] + r["k"][2:]: r for r in recs if r["k"][1] == 1}
r4 = {r["k"][:1] + r["k"][2:]: r for r in recs if r["k"][1] == 3}
print(f"CHECK R4 equals R1 in every low-latitude 5 dBi scenario: "
      f"{all(abs(r1[k]['m'] - r4[k]['m']) < 1e-12 and r1[k]['link'] == r4[k]['link'] for k in r1)}")
family(dop36, "doppler36")
family([r for r in recs if r["k"][1] in (1, 5)], "unique24")
family([r for r in recs if r["k"][1] == 2], "R3_false_cutoff")
for n in (100, 500, 2000, 5000):
    family([r for r in recs if r["k"][1] in (1, 5) and r["k"][4] == n], f"unique_N{n}")
