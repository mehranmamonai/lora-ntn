"""Aggregate SF policy runs and test the hypotheses fixed before the experiment."""
import statistics as st
import sys
from collections import defaultdict

T_95_DF4 = 2.776
TX_POWER_W = 0.145  # Assumed SX127x transmit draw at 14 dBm, about 44 mA at 3.3 V. Airtime only.
POLICIES = ["fixed_sf12", "stock_adr", "link_only", "elevation_aware", "elevation_aware_ldro10"]

groups = defaultdict(list)
with open(sys.argv[1]) as f:
    for line in f:
        if not line.startswith("RUN "):
            continue
        d = dict(kv.split("=") for kv in line.split()[1:])
        key = (float(d["gain"]), int(d["n"]), d["policy"])
        groups[key].append({k: (v if k == "policy" else float(v)) for k, v in d.items()})


def ci(values):
    mean = st.mean(values)
    half = T_95_DF4 * st.stdev(values) / len(values) ** 0.5 if len(values) > 1 else float("nan")
    return mean, half


results = {}
for (gain, n, policy), runs in sorted(groups.items()):
    denom = [r["n"] * r["passes"] for r in runs]
    delivered, delivered_ci = ci([r["received"] / x for r, x in zip(runs, denom)])
    usable_s = st.mean(r["usable"] * 60 / x for r, x in zip(runs, denom))
    sent = sum(r["sent"] for r in runs)
    received = sum(r["received"] for r in runs)
    airtime = sum(r["airtimeS"] for r in runs)
    sent_sf = [sum(r[f"sentSf{sf}"] for r in runs) for sf in range(7, 13)]
    recv_sf = [sum(r[f"recvSf{sf}"] for r in runs) for sf in range(7, 13)]
    results[(gain, n, policy)] = (delivered, delivered_ci)
    late = sum(r["recvLast5"] for r in runs) / sum(r["n"] * 5 for r in runs)
    print(
        f"RESULT gain={gain:g} n={n} policy={policy} seeds={len(runs)} "
        f"delivered_per_dev_pass={delivered:.3f}+-{delivered_ci:.3f} "
        f"delivered_last5={late:.3f} sent_per_dev_pass={sent / sum(denom):.3f} "
        f"pdr={received / sent if sent else 0:.3f} usable_s_per_dev_pass={usable_s:.1f} "
        f"airtime_per_delivered_s={airtime / received if received else float('nan'):.3f} "
        f"energy_per_delivered_mJ={1000 * TX_POWER_W * airtime / received if received else float('nan'):.1f} "
        f"lost_doppler={sum(r['rejDoppler'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_sens={sum(r['underSens'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_interf={sum(r['interfered'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_demod={sum(r['noDemod'] for r in runs) / sent if sent else 0:.3f} "
        f"adr_changed={st.mean(r['finalDrNonzero'] / r['n'] for r in runs):.3f} "
        f"sent_sf7_12={[round(x / sent, 3) if sent else 0 for x in sent_sf]} "
        f"recv_sf7_12={[int(x) for x in recv_sf]}"
    )


def beats(a, b):
    """True if a's 95% CI lies entirely above b's."""
    return a[0] - a[1] > b[0] + b[1]


configs = sorted({(g, n) for g, n, _ in results})
tests = {
    "H1_vs_link_only": ("elevation_aware", "link_only"),
    "H2_vs_fixed_sf12": ("elevation_aware", "fixed_sf12"),
    "H2_vs_stock_adr": ("elevation_aware", "stock_adr"),
    "H3_ldro10_vs_elevation_aware": ("elevation_aware_ldro10", "elevation_aware"),
}
for name, (a, b) in tests.items():
    outcome = [(g, n, beats(results[(g, n, a)], results[(g, n, b)]))
               for g, n in configs if (g, n, a) in results and (g, n, b) in results]
    wins = sum(x[2] for x in outcome)
    fails = [(g, n) for g, n, ok in outcome if not ok]
    print(f"HYPOTHESIS {name} wins={wins}/{len(outcome)} holds={wins == len(outcome)} not_won={fails}")
