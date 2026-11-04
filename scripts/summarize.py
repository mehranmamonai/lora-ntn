"""Test varied pass geometry, link margin and the long ADR run against the fixed criteria."""
import statistics as st
import sys
from collections import defaultdict

T_95_DF4 = 2.776
TX_POWER_W = 0.145  # Assumed SX127x transmit draw at 14 dBm. Airtime only.
MARGINS = [0.0, 1.0, 2.0, 3.0, 5.0]

# Window-aware timing at N=100, from run d40fe091.
PARENT = {
    (5.0, "fixed_sf12"): 0.552, (5.0, "link_only"): 0.373, (5.0, "elevation_aware"): 0.550,
    (5.0, "elevation_aware_ldro10"): 0.550, (5.0, "sf12_window"): 0.423,
    (10.0, "fixed_sf12"): 0.904, (10.0, "link_only"): 2.414, (10.0, "elevation_aware"): 2.826,
    (10.0, "elevation_aware_ldro10"): 3.121, (10.0, "sf12_window"): 1.245,
}

groups = defaultdict(list)
with open(sys.argv[1]) as f:
    for line in f:
        if line.startswith("RUN "):
            d = dict(kv.split("=") for kv in line.split()[1:])
            key = (d["part"], float(d["gain"]), int(d["n"]), d["policy"], float(d["marginDb"]))
            groups[key].append({k: (v if k in ("policy", "part") else float(v)) for k, v in d.items()})


def ci(values):
    return st.mean(values), T_95_DF4 * st.stdev(values) / len(values) ** 0.5


def beats(a, b):
    return a[0] - a[1] > b[0] + b[1]


results = {}
late = {}
changed = {}
for key, runs in sorted(groups.items()):
    part, gain, n, policy, margin = key
    denom = [r["n"] * r["passes"] for r in runs]
    mean, half = ci([r["received"] / x for r, x in zip(runs, denom)])
    late_mean, late_half = ci([r["recvLast5"] / (r["n"] * 5) for r in runs])
    results[key] = (mean, half)
    late[key] = (late_mean, late_half)
    changed[key] = st.mean(r["finalDrNonzero"] / r["n"] for r in runs)
    sent = sum(r["sent"] for r in runs)
    received = sum(r["received"] for r in runs)
    airtime = sum(r["airtimeS"] for r in runs)
    print(
        f"RESULT part={part} gain={gain:g} n={n} policy={policy} margin={margin:g} "
        f"delivered={mean:.3f}+-{half:.3f} last5={late_mean:.3f}+-{late_half:.3f} "
        f"sent_per_dev_pass={sent / sum(denom):.3f} pdr={received / sent if sent else 0:.3f} "
        f"mJ={1000 * TX_POWER_W * airtime / received if received else float('nan'):.0f} "
        f"usable_s={st.mean(r['usable'] * 60 / x for r, x in zip(runs, denom)):.1f} "
        f"lost_doppler={sum(r['rejDoppler'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_sens={sum(r['underSens'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_interf={sum(r['interfered'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_demod={sum(r['noDemod'] for r in runs) / sent if sent else 0:.3f} "
        f"dr_nonzero_at_end={changed[key]:.3f}"
    )

diff = max(abs(results[("regress", g, 100, p, 3.0)][0] - v) for (g, p), v in PARENT.items())
print(f"G1 parent_max_abs_diff={diff:.4f} holds={diff <= 0.0015}")

C = lambda g, n, p: results[("compare", g, n, p, 3.0)]
configs = sorted({(k[1], k[2]) for k in results if k[0] == "compare"})
g2 = [(g, n, beats(C(g, n, "elevation_aware"), C(g, n, "fixed_sf12"))) for g, n in configs]
print(f"G2 wins={sum(x[2] for x in g2)}/{len(g2)} holds={all(x[2] for x in g2)} "
      f"not_won={[(g, n) for g, n, ok in g2 if not ok]}")
g3 = [(n, beats(C(5.0, n, "elevation_aware"), C(5.0, n, "link_only"))) for g, n in configs if g == 5.0]
print(f"G3 wins={sum(x[1] for x in g3)}/{len(g3)} holds={all(x[1] for x in g3)} "
      f"not_won={[n for n, ok in g3 if not ok]}")

for g, n in sorted({(k[1], k[2]) for k in results if k[0] == "margin"}):
    for policy in ("link_only", "elevation_aware", "elevation_aware_ldro10"):
        values = {m: results[("margin", g, n, policy, m)] for m in MARGINS}
        best = max(values, key=lambda m: values[m][0])
        better = beats(values[best], values[3.0]) if best != 3.0 else False
        print(f"G4 gain={g:g} n={n} policy={policy} best_margin={best:g} "
              f"beats_3dB={better} values={ {m: round(v[0], 3) for m, v in values.items()} }")

g5 = []
for g, n in sorted({(k[1], k[2]) for k in results if k[0] == "long"}):
    rule = late[("long", g, n, "elevation_aware", 3.0)]
    adr = late[("long", g, n, "stock_adr", 3.0)]
    sf12 = late[("long", g, n, "fixed_sf12", 3.0)]
    win = beats(rule, adr)
    g5.append(win)
    print(f"LONG gain={g:g} n={n} rule_last5={rule[0]:.3f} adr_last5={adr[0]:.3f} sf12_last5={sf12[0]:.3f} "
          f"adr_moved={changed[('long', g, n, 'stock_adr', 3.0)]:.3f} rule_beats_adr={win}")
print(f"G5 holds={all(g5)}")

for g, n in configs:
    rule = C(g, n, "elevation_aware")[0]
    print(f"RATIO gain={g:g} n={n} rule_vs_sf12={rule / C(g, n, 'fixed_sf12')[0]:.2f} "
          f"rule_vs_sf12window={rule / C(g, n, 'sf12_window')[0]:.2f} "
          f"rule_vs_link={rule / C(g, n, 'link_only')[0]:.2f} "
          f"ldro_vs_rule={C(g, n, 'elevation_aware_ldro10')[0] / rule:.2f}")

tests = {
    "H1_vs_link_only": ("elevation_aware", "link_only"),
    "W4_vs_sf12_window": ("elevation_aware", "sf12_window"),
    "H3_ldro10_vs_elevation_aware": ("elevation_aware_ldro10", "elevation_aware"),
}
for name, (a, b) in tests.items():
    outcome = [(g, n, beats(C(g, n, a), C(g, n, b))) for g, n in configs]
    print(f"HYPOTHESIS {name} wins={sum(x[2] for x in outcome)}/{len(outcome)} "
          f"not_won={[(g, n) for g, n, ok in outcome if not ok]}")
