"""Test the upper bound on load control against the criteria fixed before the experiment."""
import statistics as st
import sys
from collections import defaultdict

T_95_DF4 = 2.776
TX_POWER_W = 0.1485  # SX1262 datasheet Table 3-6, p. 17: 45 mA at +14 dBm, 3.3 V. Transmit only.
PS = [1.0, 0.5, 0.25, 0.125, 0.0625]
RULE = "elevation_aware"
LINK = "link_only"
GAINS = (5.0, 10.0)
NS = (2000, 5000)
SCINTS = (7.69, 0.0)
READINGS = {1: "R1", 5: "R2", 2: "R3", 3: "R4"}
# Experiment 85386008, set 1, seeds 21-25: (policy, scint, gain, n) -> delivered at its locked margin.
PARENT = {
    (RULE, 7.69, 5.0, 2000): 0.059, (RULE, 7.69, 5.0, 5000): 0.029,
    (RULE, 7.69, 10.0, 2000): 0.181, (RULE, 7.69, 10.0, 5000): 0.063,
    (LINK, 7.69, 5.0, 2000): 0.041, (LINK, 7.69, 5.0, 5000): 0.022,
    (LINK, 7.69, 10.0, 2000): 0.176, (LINK, 7.69, 10.0, 5000): 0.075,
    (RULE, 0.0, 5.0, 2000): 0.338, (RULE, 0.0, 5.0, 5000): 0.137,
    (RULE, 0.0, 10.0, 2000): 1.175, (RULE, 0.0, 10.0, 5000): 0.619,
    (LINK, 0.0, 5.0, 2000): 0.348, (LINK, 0.0, 5.0, 5000): 0.129,
    (LINK, 0.0, 10.0, 2000): 1.111, (LINK, 0.0, 10.0, 5000): 0.579,
}

groups = defaultdict(list)
with open(sys.argv[1]) as f:
    for line in f:
        if line.startswith("RUN "):
            d = dict(kv.split("=") for kv in line.split()[1:])
            key = (d["part"], float(d["scintDb"]), int(d["dopplerLimits"]), float(d["gain"]), int(d["n"]),
                   d["policy"], float(d["txProb"]))
            groups[key].append({k: (v if k in ("policy", "part") else float(v)) for k, v in d.items()})


def ci(values):
    return st.mean(values), T_95_DF4 * st.stdev(values) / len(values) ** 0.5


def beats(a, b):
    return a[0] - a[1] > b[0] + b[1]


results = {}
extras = {}
for key, runs in sorted(groups.items()):
    part, scint, mode, gain, n, policy, p = key
    denom = [r["n"] * r["passes"] for r in runs]
    results[key] = ci([r["received"] / x for r, x in zip(runs, denom)])
    sent = sum(r["sent"] for r in runs)
    received = sum(r["received"] for r in runs)
    airtime = sum(r["airtimeS"] for r in runs)
    jain = st.mean(r["jain"] for r in runs)
    served = st.mean(r["served"] / r["n"] for r in runs)
    air_per = airtime / received if received else float("nan")
    extras[key] = (jain, served, air_per)
    print(
        f"RESULT part={part} scint={scint:g} reading={READINGS[mode]} gain={gain:g} n={n} policy={policy} p={p:g} "
        f"runs={len(runs)} delivered={results[key][0]:.3f}+-{results[key][1]:.3f} "
        f"sent_per_dev_pass={sent / sum(denom):.3f} pdr={received / sent if sent else 0:.3f} "
        f"airtime_per_delivered_s={air_per:.2f} tx_mJ_per_delivered={1000 * TX_POWER_W * air_per:.0f} "
        f"jain={jain:.3f} served={served:.3f} "
        f"lost_doppler={sum(r['rejDoppler'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_sens={sum(r['underSens'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_interf={sum(r['interfered'] for r in runs) / sent if sent else 0:.3f} "
        f"lost_demod={sum(r['noDemod'] for r in runs) / sent if sent else 0:.3f}"
    )


def R(part, scint, mode, g, n, policy, p):
    return results[(part, scint, mode, g, n, policy, p)]


worst = max(abs(R("confirm", k[1], 1, k[2], k[3], k[0], 1.0)[0] - v) for k, v in PARENT.items())
print(f"J1 parent_max_abs_diff={worst:.4f} holds={worst <= 0.0015}")


def analyse(policy, modes, tag):
    wins = 0
    cells = 0
    chosen_count = defaultdict(int)
    for scint in SCINTS:
        for mode in modes:
            for g in GAINS:
                for n in NS:
                    cells += 1
                    search = {p: R("search", scint, mode, g, n, policy, p)[0] for p in PS}
                    chosen = max(PS, key=lambda p: search[p])
                    chosen_count[chosen] += 1
                    a = R("confirm", scint, mode, g, n, policy, chosen)
                    b = R("confirm", scint, mode, g, n, policy, 1.0)
                    win = chosen != 1.0 and beats(a, b)
                    wins += win
                    ja, sa, aa = extras[("confirm", scint, mode, g, n, policy, chosen)]
                    jb, sb, ab = extras[("confirm", scint, mode, g, n, policy, 1.0)]
                    ratio = a[0] / b[0] if b[0] else float("nan")
                    print(f"{tag} scint={scint:g} {READINGS[mode]} gain={g:g} n={n} chosen_p={chosen:g} "
                          f"best={a[0]:.3f}+-{a[1]:.3f} p1={b[0]:.3f}+-{b[1]:.3f} ratio={ratio:.2f} win={win} "
                          f"jain={ja:.3f}/{jb:.3f} served={sa:.3f}/{sb:.3f} air_per_delivered={aa:.2f}/{ab:.2f}")
    print(f"{tag} policy={policy} wins={wins}/{cells} chosen_p_counts=" +
          ",".join(f"{p:g}:{chosen_count[p]}" for p in PS))
    return wins, cells


wins, cells = analyse(LINK, (1, 5, 2, 3), "J2")
print(f"J2 gate wins={wins}/{cells} needed=16 holds={wins >= 16}")
analyse(RULE, (1, 5), "J4")
