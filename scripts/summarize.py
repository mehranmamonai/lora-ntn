"""Test sourced receiver sensitivity and latitude against the criteria fixed before the experiment."""
import statistics as st
import sys
from collections import defaultdict

T_95_DF4 = 2.776
TX_POWER_W = 0.1485  # SX1262 datasheet Table 3-6, p. 17: 45 mA at +14 dBm, 3.3 V. Transmit only.
MARGINS = [-1.0, 0.0, 1.0, 2.0, 3.0]
RULE = "elevation_aware"
LINK = "link_only"
SF12 = "fixed_sf12"
PARENT = {5.0: 0.700, 10.0: 1.727}  # Run c88d8775, N=100, margin 0, TR 38.811 channel.
SCENARIOS = [(1, 7.69), (1, 0.0), (2, 7.69), (2, 0.0)]

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
    print(
        f"RESULT rx={rx} scint={scint:g} gain={gain:g} n={n} policy={policy} margin={margin:g} part={part} "
        f"delivered={mean:.3f}+-{half:.3f} sent_per_dev_pass={sent / sum(denom):.3f} "
        f"pdr={received / sent if sent else 0:.3f} "
        f"airtime_per_delivered_s={airtime / received if received else float('nan'):.2f} "
        f"tx_mJ_per_delivered={1000 * TX_POWER_W * airtime / received if received else float('nan'):.0f} "
        f"lost_doppler={sum(r['rejDoppler'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_sens={sum(r['underSens'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_interf={sum(r['interfered'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_demod={sum(r['noDemod'] for r in runs) / sent if sent else 0:.3f}"
    )

diff = max(abs(results[("regress", 0, 7.69, g, 100, RULE, 0.0)][0] - v) for g, v in PARENT.items())
print(f"M1 parent_max_abs_diff={diff:.4f} holds={diff <= 0.0015}")


def R(rx, scint, g, n, p, m):
    return results[("main", rx, scint, g, n, p, m)]


locked = {}
for rx, scint in SCENARIOS:
    per_margin = defaultdict(list)
    for g in (5.0, 10.0):
        for n in (100, 2000):
            values = {m: R(rx, scint, g, n, RULE, m)[0] for m in MARGINS}
            best = max(values.values())
            for m, v in values.items():
                per_margin[m].append(v / best if best else 0)
    scores = {m: st.mean(v) for m, v in per_margin.items()}
    locked[(rx, scint)] = max(scores, key=scores.get)
    print(f"M2 rx={rx} scint={scint:g} " + " ".join(f"m{m:g}={v:.3f}" for m, v in scores.items())
          + f" locked={locked[(rx, scint)]:g}")

for rx, scint in SCENARIOS:
    m = locked[(rx, scint)]
    label = "PRIMARY" if (rx, scint) == (1, 7.69) else "OTHER"
    wins = []
    for g in (5.0, 10.0):
        for n in (100, 2000, 5000):
            key = ("main", rx, scint, g, n, RULE, m)
            if key in results:
                a = results[key]
                b = R(rx, scint, g, n, SF12, 3.0)
                win = beats(a, b)
                wins.append(win)
                print(f"M3 {label} rx={rx} scint={scint:g} margin={m:g} gain={g:g} n={n} "
                      f"rule={a[0]:.3f}+-{a[1]:.3f} sf12={b[0]:.3f}+-{b[1]:.3f} "
                      f"ratio={a[0] / b[0] if b[0] else float('nan'):.2f} win={win}")
    print(f"M3 {label} rx={rx} scint={scint:g} wins={sum(wins)}/{len(wins)} holds={all(wins) if wins else 'not_run'}")
    m4 = []
    for g in (5.0, 10.0):
        for n in (100, 2000):
            key = ("main", rx, scint, g, n, LINK, m)
            if key in results:
                a = R(rx, scint, g, n, RULE, m)
                b = results[key]
                win = beats(a, b)
                if g == 5.0:
                    m4.append(win)
                print(f"M4 {label} rx={rx} scint={scint:g} margin={m:g} gain={g:g} n={n} "
                      f"rule={a[0]:.3f}+-{a[1]:.3f} link={b[0]:.3f}+-{b[1]:.3f} win={win}")
    print(f"M4 {label} rx={rx} scint={scint:g} holds={all(m4) if m4 else 'not_run_at_locked_margin'}")
