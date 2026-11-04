"""Test whether baseline results depend on transmit timing, and recheck the policy comparison."""
import statistics as st
import sys
from collections import defaultdict

T_95_DF4 = 2.776
TX_POWER_W = 0.145  # Assumed SX127x transmit draw at 14 dBm. Airtime only.

# Delivered per device per pass with fixed timing, from run 2ed8428f.
PARENT = {
    (5.0, 100, "fixed_sf12"): 0.125, (5.0, 100, "link_only"): 0.210,
    (5.0, 100, "elevation_aware"): 0.539, (5.0, 100, "elevation_aware_ldro10"): 0.539,
    (5.0, 500, "fixed_sf12"): 0.040, (5.0, 500, "link_only"): 0.127,
    (5.0, 500, "elevation_aware"): 0.422, (5.0, 500, "elevation_aware_ldro10"): 0.422,
    (10.0, 100, "fixed_sf12"): 0.725, (10.0, 100, "link_only"): 2.133,
    (10.0, 100, "elevation_aware"): 2.487, (10.0, 100, "elevation_aware_ldro10"): 2.560,
    (10.0, 500, "fixed_sf12"): 0.189, (10.0, 500, "link_only"): 1.130,
    (10.0, 500, "elevation_aware"): 1.234, (10.0, 500, "elevation_aware_ldro10"): 1.461,
}

groups = defaultdict(list)
with open(sys.argv[1]) as f:
    for line in f:
        if line.startswith("RUN "):
            d = dict(kv.split("=") for kv in line.split()[1:])
            key = (float(d["gain"]), int(d["n"]), d["policy"], int(d["randomPhase"]))
            groups[key].append({k: (v if k == "policy" else float(v)) for k, v in d.items()})


def ci(values):
    return st.mean(values), T_95_DF4 * st.stdev(values) / len(values) ** 0.5


results = {}
for key, runs in sorted(groups.items()):
    gain, n, policy, phase = key
    denom = [r["n"] * r["passes"] for r in runs]
    mean, half = ci([r["received"] / x for r, x in zip(runs, denom)])
    results[key] = (mean, half)
    sent = sum(r["sent"] for r in runs)
    received = sum(r["received"] for r in runs)
    airtime = sum(r["airtimeS"] for r in runs)
    print(
        f"RESULT gain={gain:g} n={n} policy={policy} randomPhase={phase} "
        f"delivered={mean:.3f}+-{half:.3f} sent_per_dev_pass={sent / sum(denom):.3f} "
        f"pdr={received / sent if sent else 0:.3f} "
        f"usable_s={st.mean(r['usable'] * 60 / x for r, x in zip(runs, denom)):.1f} "
        f"mJ={1000 * TX_POWER_W * airtime / received if received else float('nan'):.0f} "
        f"lost_doppler={sum(r['rejDoppler'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_sens={sum(r['underSens'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_interf={sum(r['interfered'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_demod={sum(r['noDemod'] for r in runs) / sent if sent else 0:.3f} "
        f"dr_nonzero_at_end={st.mean(r['finalDrNonzero'] / r['n'] for r in runs):.3f}"
    )


def beats(a, b):
    return a[0] - a[1] > b[0] + b[1]


diff = max(abs(results[(g, n, p, 0)][0] - v) for (g, n, p), v in PARENT.items())
print(f"A1 parent_max_abs_diff={diff:.4f} holds={diff <= 0.0015}")

a2 = all(beats(results[(g, 100, "fixed_sf12", 1)], results[(g, 100, "fixed_sf12", 0)]) for g in (5.0, 10.0))
print(f"A2 artifact_real holds={a2} "
      + " ".join(f"gain{g:g}_fixed={results[(g, 100, 'fixed_sf12', 0)][0]:.3f}_random={results[(g, 100, 'fixed_sf12', 1)][0]:.3f}"
                 for g in (5.0, 10.0)))

ratios = {g: results[(g, 100, "elevation_aware", 1)][0] / results[(g, 100, "fixed_sf12", 1)][0] for g in (5.0, 10.0)}
print(f"A3 gains_stay_large holds={all(r >= 2 for r in ratios.values())} ratios={ {g: round(r, 2) for g, r in ratios.items()} }")

configs = sorted({(k[0], k[1]) for k in results if k[3] == 1})
for g, n in configs:
    print(f"RATIO gain={g:g} n={n} rule_vs_sf12="
          f"{results[(g, n, 'elevation_aware', 1)][0] / results[(g, n, 'fixed_sf12', 1)][0]:.2f} "
          f"rule_vs_link={results[(g, n, 'elevation_aware', 1)][0] / results[(g, n, 'link_only', 1)][0]:.2f} "
          f"rule_vs_adr={results[(g, n, 'elevation_aware', 1)][0] / results[(g, n, 'stock_adr', 1)][0]:.2f} "
          f"ldro_vs_rule={results[(g, n, 'elevation_aware_ldro10', 1)][0] / results[(g, n, 'elevation_aware', 1)][0]:.2f}")

tests = {
    "H1_vs_link_only": ("elevation_aware", "link_only"),
    "H2_vs_fixed_sf12": ("elevation_aware", "fixed_sf12"),
    "H2_vs_stock_adr": ("elevation_aware", "stock_adr"),
    "H3_ldro10_vs_elevation_aware": ("elevation_aware_ldro10", "elevation_aware"),
}
for name, (a, b) in tests.items():
    outcome = [(g, n, beats(results[(g, n, a, 1)], results[(g, n, b, 1)])) for g, n in configs]
    wins = sum(x[2] for x in outcome)
    print(f"HYPOTHESIS {name} wins={wins}/{len(outcome)} not_won={[(g, n) for g, n, ok in outcome if not ok]}")
