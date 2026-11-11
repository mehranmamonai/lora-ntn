"""Per-pass controller for leo_policies --controller. Reads one observation per line on stdin and
answers with the settings for the next pass: transmit probability p, link margin and SF12
elevation cut-off theta.

Modes: 'constant' returns fixed values; 'scripted' changes them from a given pass (Stage 3);
'adaptive' applies the Stage 4 rules, using only gateway-observable fields."""
import argparse
import json
import sys

OBSERVABLE = {"pass", "received", "received_by_sf", "devices_heard", "rssi_mean_dbm", "rssi_min_dbm",
              "near_sensitivity", "sf11_by_elevation", "sf12_by_elevation", "devices_heard_total"}

parser = argparse.ArgumentParser()
parser.add_argument("--p", type=float, required=True)
parser.add_argument("--margin", type=float, required=True)
parser.add_argument("--p-from", default="", help="PASS:VALUE, new p for every pass from PASS on")
parser.add_argument("--margin-from", default="", help="PASS:VALUE, new margin for every pass from PASS on")
parser.add_argument("--mode", choices=["constant", "scripted", "adaptive"], default="")
parser.add_argument("--k", type=float, default=0, help="adaptive: p = min(1, k / estimated devices); 0 = off")
parser.add_argument("--adapt-margin", type=int, default=0)
parser.add_argument("--h", type=float, default=0,
                    help="adaptive two-level load rule: p = 1/2 once distinct devices heard so far exceed H; 0 = off")
args = parser.parse_args()
mode = args.mode or ("scripted" if args.p_from or args.margin_from else "constant")


def change(spec):
    if not spec:
        return None
    at, value = spec.split(":")
    return int(at), float(value)


p_change, margin_change = change(args.p_from), change(args.margin_from)
p, margin, theta = args.p, args.margin, 90.0
sf11 = [0] * 7
sf12 = [0] * 7


def learn_theta():
    """Lowest 10-degree bin above 40 deg whose SF12 share of SF11+SF12 receptions falls below half
    of the share at 20-40 deg, given at least 5 such packets; 90 if none."""
    ref_total = sum(sf11[:2]) + sum(sf12[:2])
    if ref_total < 5:
        return 90.0
    ref = sum(sf12[:2]) / ref_total
    for b in range(2, 7):
        total = sf11[b] + sf12[b]
        if total >= 5 and sf12[b] / total < 0.5 * ref:
            return 20.0 + 10 * b
    return 90.0


# readline, not iteration: iterating over a pipe waits for a full buffer, which deadlocks the loop.
while True:
    line = sys.stdin.readline()
    if not line:
        break
    obs = json.loads(line)
    unexpected = set(obs) - OBSERVABLE
    if unexpected:
        sys.exit(f"controller: unobservable fields received: {sorted(unexpected)}")
    next_pass = obs["pass"] + 1
    if mode == "scripted":
        p, margin = args.p, args.margin
        if p_change and next_pass >= p_change[0]:
            p = p_change[1]
        if margin_change and next_pass >= margin_change[0]:
            margin = margin_change[1]
    elif mode == "adaptive":
        for b in range(7):
            sf11[b] += obs.get("sf11_by_elevation", [0] * 7)[b]
            sf12[b] += obs.get("sf12_by_elevation", [0] * 7)[b]
        theta = learn_theta()
        if args.adapt_margin and obs["received"] > 0:
            near = obs.get("near_sensitivity", 0) / obs["received"]
            if near > 0.5:
                margin = min(3.0, margin + 1)
            elif near < 0.2:
                margin = max(-4.0, margin - 1)
        if args.k > 0:
            estimated = obs["devices_heard"] / max(p, 0.0625)
            p = 1.0 if estimated <= 0 else min(1.0, args.k / estimated)
        if args.h > 0:
            p = 0.5 if obs.get("devices_heard_total", 0) > args.h else 1.0
    print(json.dumps({"p": p, "margin_db": margin, "theta_deg": theta}), flush=True)
