"""Test the measured SF12 Doppler limit against the criteria fixed before the experiment."""
import statistics as st
import sys
from collections import defaultdict

T_95_DF4 = 2.776
TX_POWER_W = 0.1485  # SX1262 datasheet Table 3-6, p. 17: 45 mA at +14 dBm, 3.3 V. Transmit only.
MARGINS = [-2.0, -1.0, 0.0, 1.0, 3.0]
RULE = "elevation_aware"
LINK = "link_only"
SF12 = "fixed_sf12"
GAINS = (5.0, 10.0)
NS = (100, 2000, 5000)
SCENARIOS = [(1, 7.69), (1, 0.0), (2, 7.69), (2, 0.0)]
PRIMARY = (1, 7.69)
# Parent experiment 02e77a36, seeds 16-20, N=100, summary.txt: (policy, margin, gain) -> delivered.
PARENT = {
    (RULE, -1.0, 5.0): 0.057, (RULE, -1.0, 10.0): 0.641,
    (LINK, 0.0, 5.0): 0.000, (LINK, 0.0, 10.0): 0.430,
    (SF12, 3.0, 5.0): 0.018, (SF12, 3.0, 10.0): 0.169,
}

groups = defaultdict(list)
with open(sys.argv[1]) as f:
    for line in f:
        if line.startswith("RUN "):
            d = dict(kv.split("=") for kv in line.split()[1:])
            key = (d["part"], int(d["rxSet"]), float(d["scintDb"]), float(d["gain"]), int(d["n"]),
                   d["policy"], float(d["marginDb"]))
            groups[key].append({k: (v if k in ("policy", "part") else float(v)) for k, v in d.items()})


def ci(values):
    return st.mean(values), T_95_DF4 * st.stdev(values) / len(values) ** 0.5


def beats(a, b):
    return a[0] - a[1] > b[0] + b[1]


results = {}
for key, runs in sorted(groups.items()):
    part, rx, scint, gain, n, policy, margin = key
    denom = [r["n"] * r["passes"] for r in runs]
    mean, half = ci([r["received"] / x for r, x in zip(runs, denom)])
    results[key] = (mean, half)
    sent = sum(r["sent"] for r in runs)
    received = sum(r["received"] for r in runs)
    airtime = sum(r["airtimeS"] for r in runs)
    limits = {r["dopplerLimits"] for r in runs}
    print(
        f"RESULT part={part} rx={rx} scint={scint:g} gain={gain:g} n={n} policy={policy} margin={margin:g} "
        f"limits={sorted(limits)} runs={len(runs)} delivered={mean:.3f}+-{half:.3f} "
        f"sent_per_dev_pass={sent / sum(denom):.3f} pdr={received / sent if sent else 0:.3f} "
        f"airtime_per_delivered_s={airtime / received if received else float('nan'):.2f} "
        f"tx_mJ_per_delivered={1000 * TX_POWER_W * airtime / received if received else float('nan'):.0f} "
        f"lost_doppler={sum(r['rejDoppler'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_sens={sum(r['underSens'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_interf={sum(r['interfered'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_demod={sum(r['noDemod'] for r in runs) / sent if sent else 0:.3f} "
        f"sf12_share={sum(r['sentSf12'] for r in runs) / sent if sent else 0:.3f}"
    )


def R(part, scen, g, n, p, m):
    return results[(part, scen[0], scen[1], g, n, p, m)]


diffs = [abs(R("regress", PRIMARY, k[2], 100, k[0], k[1])[0] - v) for k, v in PARENT.items()]
print(f"G1 parent_max_abs_diff={max(diffs):.4f} holds={max(diffs) <= 0.0015}")


def lock(scen, policy):
    per_margin = defaultdict(list)
    for g in GAINS:
        for n in (100, 2000):
            values = {m: R("search", scen, g, n, policy, m)[0] for m in MARGINS}
            best = max(values.values())
            for m, v in values.items():
                per_margin[m].append(v / best if best else 0)
    scores = {m: st.mean(v) for m, v in per_margin.items()}
    chosen = max(scores, key=scores.get)
    print(f"G2 rx={scen[0]} scint={scen[1]:g} policy={policy} " + " ".join(f"m{m:g}={v:.3f}" for m, v in scores.items())
          + f" locked={chosen:g} at_sweep_edge={chosen == MARGINS[0]}")
    return chosen


def compare(tag, label_b, a, b, g, n):
    win = beats(a, b)
    print(f"{tag} gain={g:g} n={n} rule={a[0]:.3f}+-{a[1]:.3f} {label_b}={b[0]:.3f}+-{b[1]:.3f} "
          f"ratio={a[0] / b[0] if b[0] else float('nan'):.2f} win={win}")
    return win


for scen in SCENARIOS:
    label = "PRIMARY" if scen == PRIMARY else "OTHER"
    rule_m, link_m = lock(scen, RULE), lock(scen, LINK)
    print(f"--- {label} rx={scen[0]} scint={scen[1]:g} rule_margin={rule_m:g} link_margin={link_m:g}")
    wins = [compare("G3", "sf12", R("confirm", scen, g, n, RULE, rule_m), R("confirm", scen, g, n, SF12, 3.0), g, n)
            for g in GAINS for n in NS]
    print(f"G3 {label} wins={sum(wins)}/{len(wins)} holds={all(wins)}")
    for tag, m_link in (("G4", rule_m), ("G5", link_m)):
        tested = []
        for g in GAINS:
            for n in NS:
                win = compare(tag, "link", R("confirm", scen, g, n, RULE, rule_m), R("confirm", scen, g, n, LINK, m_link), g, n)
                if g == 5.0 and n in (100, 2000):
                    tested.append(win)
        print(f"{tag} {label} rule_margin={rule_m:g} link_margin={m_link:g} wins={sum(tested)}/{len(tested)} holds={all(tested)}")
