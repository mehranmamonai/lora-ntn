"""Test window-aware timing against the criteria fixed before the experiment."""
import statistics as st
import sys
from collections import defaultdict

T_95_DF4 = 2.776
TX_POWER_W = 0.145  # Assumed SX127x transmit draw at 14 dBm. Airtime only.

# Fixed timing at N=100, from run 2ed8428f.
PARENT_FIXED = {
    (5.0, "fixed_sf12"): 0.125, (5.0, "link_only"): 0.210,
    (5.0, "elevation_aware"): 0.539, (5.0, "elevation_aware_ldro10"): 0.539,
    (10.0, "fixed_sf12"): 0.725, (10.0, "link_only"): 2.133,
    (10.0, "elevation_aware"): 2.487, (10.0, "elevation_aware_ldro10"): 2.560,
}
# Elevation-aware with random timing at 5 dBi, N=100, from run 2a8d8e32.
RANDOM_RULE_5DBI_N100 = (0.314, 0.016)

groups = defaultdict(list)
with open(sys.argv[1]) as f:
    for line in f:
        if line.startswith("RUN "):
            d = dict(kv.split("=") for kv in line.split()[1:])
            key = (float(d["gain"]), int(d["n"]), d["policy"], int(d["windowPhase"]), float(d["errorKm"]))
            groups[key].append({k: (v if k == "policy" else float(v)) for k, v in d.items()})


def ci(values):
    return st.mean(values), T_95_DF4 * st.stdev(values) / len(values) ** 0.5


results = {}
for key, runs in sorted(groups.items()):
    gain, n, policy, window, err = key
    denom = [r["n"] * r["passes"] for r in runs]
    mean, half = ci([r["received"] / x for r, x in zip(runs, denom)])
    results[key] = (mean, half)
    sent = sum(r["sent"] for r in runs)
    received = sum(r["received"] for r in runs)
    airtime = sum(r["airtimeS"] for r in runs)
    print(
        f"RESULT gain={gain:g} n={n} policy={policy} window={window} errorKm={err:g} "
        f"delivered={mean:.3f}+-{half:.3f} sent_per_dev_pass={sent / sum(denom):.3f} "
        f"pdr={received / sent if sent else 0:.3f} "
        f"mJ={1000 * TX_POWER_W * airtime / received if received else float('nan'):.0f} "
        f"lost_doppler={sum(r['rejDoppler'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_sens={sum(r['underSens'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_interf={sum(r['interfered'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_demod={sum(r['noDemod'] for r in runs) / sent if sent else 0:.3f} "
        f"dr_nonzero_at_end={st.mean(r['finalDrNonzero'] / r['n'] for r in runs):.3f}"
    )


def beats(a, b):
    return a[0] - a[1] > b[0] + b[1]


W = lambda g, n, p, e=0.0: results[(g, n, p, 1, e)]
diff = max(abs(results[(g, 100, p, 0, 0.0)][0] - v) for (g, p), v in PARENT_FIXED.items())
print(f"W1 parent_max_abs_diff={diff:.4f} holds={diff <= 0.0015}")

rule = W(5.0, 100, "elevation_aware")
print(f"W2 holds={beats(rule, RANDOM_RULE_5DBI_N100)} rule_window={rule[0]:.3f}+-{rule[1]:.3f} "
      f"rule_random={RANDOM_RULE_5DBI_N100[0]}+-{RANDOM_RULE_5DBI_N100[1]} rule_fixed=0.539+-0.038")

configs = sorted({(k[0], k[1]) for k in results if k[3] == 1 and k[4] == 0.0})
w3 = [(g, n, beats(W(g, n, "elevation_aware"), W(g, n, "fixed_sf12"))) for g, n in configs]
print(f"W3 wins={sum(x[2] for x in w3)}/{len(w3)} holds={all(x[2] for x in w3)} "
      f"not_won={[(g, n) for g, n, ok in w3 if not ok]}")
w4 = [(g, n, beats(W(g, n, "elevation_aware"), W(g, n, "sf12_window"))) for g, n in configs]
print(f"W4 wins={sum(x[2] for x in w4)}/{len(w4)} not_won={[(g, n) for g, n, ok in w4 if not ok]}")

w5 = True
for g, n in sorted({(k[0], k[1]) for k in results if k[3] == 1 and k[4] == 30.0}):
    kept = {e: W(g, n, "elevation_aware", e)[0] / W(g, n, "elevation_aware")[0] for e in (30.0, 100.0)}
    win = beats(W(g, n, "elevation_aware", 30.0), W(g, n, "fixed_sf12", 30.0))
    w5 &= kept[30.0] >= 0.9 and win
    print(f"STALE gain={g:g} n={n} kept_30km={kept[30.0]:.3f} kept_100km={kept[100.0]:.3f} beats_sf12_at_30km={win}")
print(f"W5 holds={w5}")

for g, n in configs:
    rule_mean = W(g, n, "elevation_aware")[0]
    print(f"RATIO gain={g:g} n={n} rule_vs_sf12={rule_mean / W(g, n, 'fixed_sf12')[0]:.2f} "
          f"rule_vs_sf12window={rule_mean / W(g, n, 'sf12_window')[0]:.2f} "
          f"rule_vs_link={rule_mean / W(g, n, 'link_only')[0]:.2f} "
          f"rule_vs_adr={rule_mean / W(g, n, 'stock_adr')[0]:.2f} "
          f"ldro_vs_rule={W(g, n, 'elevation_aware_ldro10')[0] / rule_mean:.2f}")

tests = {
    "H1_vs_link_only": ("elevation_aware", "link_only"),
    "H2_vs_stock_adr": ("elevation_aware", "stock_adr"),
    "H3_ldro10_vs_elevation_aware": ("elevation_aware_ldro10", "elevation_aware"),
}
for name, (a, b) in tests.items():
    outcome = [(g, n, beats(W(g, n, a), W(g, n, b))) for g, n in configs]
    print(f"HYPOTHESIS {name} wins={sum(x[2] for x in outcome)}/{len(outcome)} "
          f"not_won={[(g, n) for g, n, ok in outcome if not ok]}")
