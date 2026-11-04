"""Aggregate the stale-prediction runs and test the criteria fixed before the experiment."""
import statistics as st
import sys
from collections import defaultdict

T_95_DF4 = 2.776
TX_POWER_W = 0.145  # Assumed SX127x transmit draw at 14 dBm. Airtime only.
GNSS_ENERGY_J = (0.0, 0.1, 1.0)  # Assumed energy per device per pass to keep a prediction usable.
ERRORS = [0.0, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0]

# Delivered per device per pass from parent run 2ed8428f at zero error.
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
            key = (float(d["gain"]), int(d["n"]), d["policy"], float(d["errorKm"]))
            groups[key].append({k: (v if k == "policy" else float(v)) for k, v in d.items()})


def ci(values):
    return st.mean(values), T_95_DF4 * st.stdev(values) / len(values) ** 0.5


results = {}
for key, runs in sorted(groups.items()):
    gain, n, policy, err = key
    denom = [r["n"] * r["passes"] for r in runs]
    mean, half = ci([r["received"] / x for r, x in zip(runs, denom)])
    results[key] = (mean, half)
    sent = sum(r["sent"] for r in runs)
    received = sum(r["received"] for r in runs)
    airtime = sum(r["airtimeS"] for r in runs)
    energies = []
    for e_fix in GNSS_ENERGY_J:
        cost = 0.0 if policy == "ungated_sf12" else e_fix * sum(denom)
        energies.append(1000 * (TX_POWER_W * airtime + cost) / received if received else float("nan"))
    print(
        f"RESULT gain={gain:g} n={n} policy={policy} errorKm={err:g} "
        f"delivered={mean:.3f}+-{half:.3f} sent_per_dev_pass={sent / sum(denom):.3f} "
        f"pdr={received / sent if sent else 0:.3f} "
        f"usable_s={st.mean(r['usable'] * 60 / x for r, x in zip(runs, denom)):.1f} "
        f"mJ_gnss0={energies[0]:.0f} mJ_gnss0p1J={energies[1]:.0f} mJ_gnss1J={energies[2]:.0f} "
        f"lost_doppler={sum(r['rejDoppler'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_sens={sum(r['underSens'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_interf={sum(r['interfered'] for r in runs) / sent if sent else 0:.3f}"
    )


def beats(a, b):
    return a[0] - a[1] > b[0] + b[1]


configs = sorted({(k[0], k[1]) for k in results})

diffs = [abs(results[(g, n, p, 0.0)][0] - v) for (g, n, p), v in PARENT.items()]
c1 = max(diffs) <= 0.0015
print(f"C1 parent_max_abs_diff={max(diffs):.4f} holds={c1}")

c2 = True
c3 = True
for g, n in configs:
    zero = results[(g, n, "elevation_aware", 0.0)][0]
    kept = {e: results[(g, n, "elevation_aware", e)][0] / zero for e in ERRORS}
    largest = max((e for e in ERRORS if all(kept[x] >= 0.9 for x in ERRORS if x <= e)), default=None)
    c2 &= kept[30.0] >= 0.9
    ungated = results[(g, n, "ungated_sf12", 0.0)]
    beat_gated = {e: beats(results[(g, n, "elevation_aware", e)], results[(g, n, "fixed_sf12", e)])
                  for e in ERRORS}
    beat_ungated = {e: beats(results[(g, n, "elevation_aware", e)], ungated) for e in ERRORS}
    beat_link = {e: beats(results[(g, n, "elevation_aware", e)], results[(g, n, "link_only", e)])
                 for e in ERRORS}
    c3 &= all(beat_gated[e] and beat_ungated[e] for e in ERRORS if e <= 30)
    print(f"ROBUST gain={g:g} n={n} kept={ {e: round(v, 3) for e, v in kept.items()} } "
          f"largest_error_keeping_90pct={largest} "
          f"beats_gated_sf12={[e for e in ERRORS if beat_gated[e]]} "
          f"beats_ungated_sf12={[e for e in ERRORS if beat_ungated[e]]} "
          f"beats_link_only={[e for e in ERRORS if beat_link[e]]}")
print(f"C2 keep_90pct_at_30km holds={c2}")
print(f"C3 beats_gated_and_ungated_sf12_up_to_30km holds={c3}")
