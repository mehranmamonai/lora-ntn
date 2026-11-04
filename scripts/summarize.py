"""Select the locked margin and test the baseline-lock rules fixed before the experiment."""
import statistics as st
import sys
from collections import defaultdict

T_95_DF4 = 2.776
MARGINS = [-2.0, -1.0, 0.0, 1.0, 2.0, 3.0]
RULE = "elevation_aware"
LDRO = "elevation_aware_ldro10"

# Varied geometry, N=100, 3 dB margin, seeds 6-10, from run d0518038.
PARENT = {
    (5.0, "fixed_sf12"): 0.365, (5.0, "link_only"): 0.182, (5.0, RULE): 0.276, (5.0, LDRO): 0.276,
    (10.0, "fixed_sf12"): 0.753, (10.0, "link_only"): 1.659, (10.0, RULE): 2.003, (10.0, LDRO): 2.170,
}

groups = defaultdict(list)
with open(sys.argv[1]) as f:
    for line in f:
        if line.startswith("RUN "):
            d = dict(kv.split("=") for kv in line.split()[1:])
            key = (d["part"], float(d["gain"]), int(d["n"]), d["policy"], float(d["marginDb"]),
                   float(d["channelMode"]))
            groups[key].append({k: (v if k in ("policy", "part") else float(v)) for k, v in d.items()})


def ci(values):
    return st.mean(values), T_95_DF4 * st.stdev(values) / len(values) ** 0.5


def beats(a, b):
    return a[0] - a[1] > b[0] + b[1]


results = {}
for key, runs in sorted(groups.items()):
    part, gain, n, policy, margin, k = key
    denom = [r["n"] * r["passes"] for r in runs]
    mean, half = ci([r["received"] / x for r, x in zip(runs, denom)])
    results[key] = (mean, half)
    sent = sum(r["sent"] for r in runs)
    received = sum(r["received"] for r in runs)
    airtime = sum(r["airtimeS"] for r in runs)
    print(
        f"RESULT part={part} gain={gain:g} n={n} policy={policy} margin={margin:g} channel={k:g} "
        f"delivered={mean:.3f}+-{half:.3f} sent_per_dev_pass={sent / sum(denom):.3f} "
        f"pdr={received / sent if sent else 0:.3f} "
        f"airtime_per_delivered_s={airtime / received if received else float('nan'):.2f} "
        f"lost_doppler={sum(r['rejDoppler'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_sens={sum(r['underSens'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_interf={sum(r['interfered'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_demod={sum(r['noDemod'] for r in runs) / sent if sent else 0:.3f} "
        f"dr_nonzero_at_end={st.mean(r['finalDrNonzero'] / r['n'] for r in runs):.3f}"
    )

diff = max(abs(results[("regress", g, 100, p, 3.0, 0.0)][0] - v) for (g, p), v in PARENT.items())
print(f"L1 parent_max_abs_diff={diff:.4f} holds={diff <= 0.0015}")


def scores(k, policy=RULE):
    per_margin = defaultdict(list)
    for g in (5.0, 10.0):
        for n in (100, 2000):
            values = {m: results[("sweep", g, n, policy, m, k)][0] for m in MARGINS}
            best = max(values.values())
            for m, v in values.items():
                per_margin[m].append(v / best)
    return {m: st.mean(v) for m, v in per_margin.items()}


for k in (0.0, 1.0, 2.0):
    for policy in (RULE, LDRO):
        s = scores(k, policy)
        print(f"SCORE channel={k:g} policy={policy} " + " ".join(f"m{m:g}={v:.3f}" for m, v in s.items())
              + f" best={max(s, key=s.get):g}")

main = scores(1.0)
locked = max(main, key=main.get)
gap = main[locked] - main[0.0]
print(f"L2 locked_margin={locked:g} score={main[locked]:.3f} zero_db_score={main[0.0]:.3f} "
      f"zero_db_confirmed={gap <= 0.02}")
harsh = scores(2.0)
print(f"RAYTRACE_K4 best_margin={max(harsh, key=harsh.get):g} locked_score={harsh[locked]:.3f} "
      f"zero_db_score={harsh[0.0]:.3f}")

K = 1.0
l3 = []
for g in (5.0, 10.0):
    for n in (100, 2000, 5000):
        part = "large" if n == 5000 else "sweep"
        key = (part, g, n, RULE, locked, K)
        if key in results:
            rule = results[key]
            sf12 = results[("sf12", g, n, "fixed_sf12", 3.0, K)]
            win = beats(rule, sf12)
            l3.append(win)
            print(f"L3 gain={g:g} n={n} rule={rule[0]:.3f}+-{rule[1]:.3f} sf12={sf12[0]:.3f}+-{sf12[1]:.3f} "
                  f"ratio={rule[0] / sf12[0]:.2f} win={win}")
print(f"L3 wins={sum(l3)}/{len(l3)} holds={all(l3) if l3 else 'not_run'}")

l4 = []
for n in (100, 2000):
    key = ("sweep", 5.0, n, "link_only", locked, K)
    if key in results:
        rule = results[("sweep", 5.0, n, RULE, locked, K)]
        link = results[key]
        win = beats(rule, link)
        l4.append(win)
        print(f"L4 n={n} rule={rule[0]:.3f}+-{rule[1]:.3f} link={link[0]:.3f}+-{link[1]:.3f} win={win}")
print(f"L4 holds={all(l4) if l4 else 'not_run_at_locked_margin'}")

l5 = []
for g in (5.0, 10.0):
    for n in (100, 500):
        key = ("long", g, n, RULE, locked, K)
        adr = results[("long", g, n, "stock_adr", 3.0, K)]
        moved = st.mean(r["finalDrNonzero"] / r["n"] for r in groups[("long", g, n, "stock_adr", 3.0, K)])
        if key in results:
            rule = results[key]
            win = beats(rule, adr)
            if g == 10.0:
                l5.append(win)
            print(f"L5 gain={g:g} n={n} rule={rule[0]:.3f}+-{rule[1]:.3f} adr={adr[0]:.3f}+-{adr[1]:.3f} "
                  f"adr_moved={moved:.3f} win={win}")
print(f"L5 holds={all(l5) if l5 else 'not_run_at_locked_margin'}")

for g in (5.0, 10.0):
    for n in (100, 2000):
        for k in (0.0, 1.0, 2.0):
            rule = results[("sweep", g, n, RULE, locked, k)]
            ldro = results[("sweep", g, n, LDRO, locked, k)]
            sf12 = results[("sf12", g, n, "fixed_sf12", 3.0, k)]
            print(f"LOCKED gain={g:g} n={n} channel={k:g} rule={rule[0]:.3f}+-{rule[1]:.3f} "
                  f"ldro={ldro[0]:.3f}+-{ldro[1]:.3f} sf12={sf12[0]:.3f}+-{sf12[1]:.3f} "
                  f"ldro_beats_rule={beats(ldro, rule)} rule_beats_sf12={beats(rule, sf12)}")
