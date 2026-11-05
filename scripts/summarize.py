"""Test the sensitivity to unmeasured Doppler limits against the criteria fixed before the experiment."""
import statistics as st
import sys
from collections import defaultdict

T_95_DF4 = 2.776
TX_POWER_W = 0.1485  # SX1262 datasheet Table 3-6, p. 17: 45 mA at +14 dBm, 3.3 V. Transmit only.
MARGINS = [-4.0, -3.0, -2.0, -1.0, 0.0]
RULE = "elevation_aware"
LINK = "link_only"
SF12 = "fixed_sf12"
NS = (100, 2000, 5000)
MODE_GAINS = {1: (5.0, 10.0), 2: (5.0, 10.0), 3: (10.0,)}
MODE_NAMES = {1: "sf12_144HzPerS", 2: "sf12_0.33ppmPerS", 3: "sf12_144HzPerS_sf10_free"}
# Parent experiment 85386008, primary scenario, seeds 21-25: (policy, margin, gain, n) -> delivered.
PARENT = {
    (RULE, -2.0, 5.0, 100): 0.102, (RULE, -2.0, 5.0, 2000): 0.059, (RULE, -2.0, 5.0, 5000): 0.029,
    (RULE, -2.0, 10.0, 100): 0.605, (RULE, -2.0, 10.0, 2000): 0.181, (RULE, -2.0, 10.0, 5000): 0.063,
    (LINK, -2.0, 5.0, 100): 0.075, (LINK, -2.0, 5.0, 2000): 0.041, (LINK, -2.0, 5.0, 5000): 0.022,
    (LINK, -2.0, 10.0, 100): 0.380, (LINK, -2.0, 10.0, 2000): 0.176, (LINK, -2.0, 10.0, 5000): 0.075,
    (SF12, 3.0, 5.0, 100): 0.040, (SF12, 3.0, 5.0, 2000): 0.007, (SF12, 3.0, 5.0, 5000): 0.001,
    (SF12, 3.0, 10.0, 100): 0.327, (SF12, 3.0, 10.0, 2000): 0.039, (SF12, 3.0, 10.0, 5000): 0.009,
}

groups = defaultdict(list)
with open(sys.argv[1]) as f:
    for line in f:
        if line.startswith("RUN "):
            d = dict(kv.split("=") for kv in line.split()[1:])
            key = (d["part"], int(d["dopplerLimits"]), float(d["gain"]), int(d["n"]), d["policy"], float(d["marginDb"]))
            groups[key].append({k: (v if k in ("policy", "part") else float(v)) for k, v in d.items()})


def ci(values):
    return st.mean(values), T_95_DF4 * st.stdev(values) / len(values) ** 0.5


def beats(a, b):
    return a[0] - a[1] > b[0] + b[1]


results = {}
for key, runs in sorted(groups.items()):
    part, mode, gain, n, policy, margin = key
    denom = [r["n"] * r["passes"] for r in runs]
    mean, half = ci([r["received"] / x for r, x in zip(runs, denom)])
    results[key] = (mean, half)
    sent = sum(r["sent"] for r in runs)
    received = sum(r["received"] for r in runs)
    airtime = sum(r["airtimeS"] for r in runs)
    print(
        f"RESULT part={part} mode={mode} gain={gain:g} n={n} policy={policy} margin={margin:g} runs={len(runs)} "
        f"delivered={mean:.3f}+-{half:.3f} sent_per_dev_pass={sent / sum(denom):.3f} "
        f"pdr={received / sent if sent else 0:.3f} "
        f"airtime_per_delivered_s={airtime / received if received else float('nan'):.2f} "
        f"tx_mJ_per_delivered={1000 * TX_POWER_W * airtime / received if received else float('nan'):.0f} "
        f"lost_doppler={sum(r['rejDoppler'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_sens={sum(r['underSens'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_interf={sum(r['interfered'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_demod={sum(r['noDemod'] for r in runs) / sent if sent else 0:.3f} "
        f"sf12_share={sum(r['sentSf12'] for r in runs) / sent if sent else 0:.3f} "
        f"sf10_share={sum(r['sentSf10'] for r in runs) / sent if sent else 0:.3f}"
    )


def R(part, mode, g, n, p, m):
    return results[(part, mode, g, n, p, m)]


worst = max(abs(R("confirm", 1, k[2], k[3], k[0], k[1])[0] - v) for k, v in PARENT.items())
print(f"H1 parent_max_abs_diff={worst:.4f} holds={worst <= 0.0015}")


def lock(mode, policy):
    per_margin = defaultdict(list)
    for g in MODE_GAINS[mode]:
        for n in (100, 2000):
            values = {m: R("search", mode, g, n, policy, m)[0] for m in MARGINS}
            best = max(values.values())
            for m, v in values.items():
                per_margin[m].append(v / best if best else 0)
    scores = {m: st.mean(v) for m, v in per_margin.items()}
    chosen = max(scores, key=scores.get)
    print(f"H2 mode={mode} ({MODE_NAMES[mode]}) policy={policy} " + " ".join(f"m{m:g}={v:.3f}" for m, v in scores.items())
          + f" locked={chosen:g} at_sweep_edge={chosen == MARGINS[0]}")
    return chosen


def compare(mode, label, a, b, g, n):
    win = beats(a, b)
    ratio = a[0] / b[0] if b[0] else float("nan")
    print(f"M{mode} gain={g:g} n={n} rule={a[0]:.3f}+-{a[1]:.3f} {label}={b[0]:.3f}+-{b[1]:.3f} ratio={ratio:.2f} win={win}")
    return win


for mode, tag, test_gain in ((1, "H3", 5.0), (2, "H4", 5.0), (3, "H5", 10.0)):
    rule_m, link_m = lock(mode, RULE), lock(mode, LINK)
    tested = []
    for g in MODE_GAINS[mode]:
        for n in NS:
            win = compare(mode, "link", R("confirm", mode, g, n, RULE, rule_m), R("confirm", mode, g, n, LINK, link_m), g, n)
            if g == test_gain and n in (100, 2000):
                tested.append(win)
            compare(mode, "sf12", R("confirm", mode, g, n, RULE, rule_m), R("confirm", mode, g, n, SF12, 3.0), g, n)
    print(f"{tag} mode={mode} rule_margin={rule_m:g} link_margin={link_m:g} gain={test_gain:g} "
          f"wins={sum(tested)}/{len(tested)} holds={all(tested)}")

same = []
for g in (5.0, 10.0):
    a, b = R("check", 4, g, 100, RULE, -2.0), R("check", 4, g, 100, LINK, -2.0)
    same.append(a == b)
    print(f"H6 gain={g:g} rule={a[0]:.3f}+-{a[1]:.3f} link={b[0]:.3f}+-{b[1]:.3f} identical={a == b}")
print(f"H6 holds={all(same)}")
