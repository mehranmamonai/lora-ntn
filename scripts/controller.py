"""Per-pass controller for leo_policies --controller. Reads one observation per line on stdin and
answers with the settings for the next pass: transmit probability p, link margin and SF12
elevation cut-off theta.

Modes: 'constant' returns fixed values; 'scripted' changes them from a given pass (Stage 3);
'adaptive' applies the Stage 4 rules, using only gateway-observable fields; 'abtest' starts from the
adaptive cut-off and then compares neighbouring cut-offs within each pass, odd against even device
addresses, by received packets."""
import argparse
import json
import sys

OBSERVABLE = {"pass", "received", "received_by_sf", "devices_heard", "rssi_mean_dbm", "rssi_min_dbm",
              "near_sensitivity", "sf11_by_elevation", "sf12_by_elevation", "devices_heard_total",
              "received_odd"}

parser = argparse.ArgumentParser()
parser.add_argument("--p", type=float, required=True)
parser.add_argument("--margin", type=float, required=True)
parser.add_argument("--p-from", default="", help="PASS:VALUE, new p for every pass from PASS on")
parser.add_argument("--margin-from", default="", help="PASS:VALUE, new margin for every pass from PASS on")
parser.add_argument("--mode", choices=["constant", "scripted", "adaptive", "abtest"], default="")
parser.add_argument("--k", type=float, default=0, help="adaptive: p = min(1, k / estimated devices); 0 = off")
parser.add_argument("--adapt-margin", type=int, default=0)
parser.add_argument("--h", type=float, default=0,
                    help="adaptive two-level load rule: p = 1/2 once distinct devices heard so far exceed H; 0 = off")
parser.add_argument("--share-frac", type=float, default=0.5,
                    help="adaptive: cut-off at the first bin whose SF12 share falls below this fraction of the reference")
parser.add_argument("--min-bin", type=int, default=2,
                    help="adaptive: lowest bin that can set the cut-off; bins below it form the reference band")
parser.add_argument("--ab-start", type=int, default=4, help="abtest: first pass with an A/B comparison")
parser.add_argument("--ab-end", type=int, default=15, help="abtest: last pass with an A/B comparison")
parser.add_argument("--ab-len", type=int, default=2, help="abtest: passes per comparison (even; groups swap each pass)")
parser.add_argument("--ab-delta", type=float, default=0.0,
                    help="abtest: accept the challenger if its extra packets exceed this share of all packets received in the comparison")
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
    lo = args.min_bin
    ref_total = sum(sf11[:lo]) + sum(sf12[:lo])
    if ref_total < 5:
        return 90.0
    ref = sum(sf12[:lo]) / ref_total
    for b in range(lo, 7):
        total = sf11[b] + sf12[b]
        if total >= 5 and sf12[b] / total < args.share_frac * ref:
            return 20.0 + 10 * b
    return 90.0


class AbTest:
    """Hill climb over cut-offs in 10-degree steps. Each comparison runs ab_len passes; the challenger
    goes to the odd group on even-numbered passes of the comparison and to the even group otherwise,
    so device placement cancels. The challenger wins if it collects more packets by the margin.
    Until a challenger has won, the incumbent follows the share rule's current cut-off, so the
    controller never ends on a cut-off the share rule would not also have used."""

    def __init__(self):
        self.incumbent = None
        self.accepted = False
        self.direction = -10
        self.tried_other = False
        self.done = False
        self.challenger = None
        self.step = 0
        self.diff = 0
        self.total = 0
        self.odd_is_challenger = False

    def next_challenger(self):
        for _ in range(2):
            c = self.incumbent + self.direction
            if 20 <= c <= 90:
                return c
            if self.tried_other:
                return None
            self.direction, self.tried_other = -self.direction, True
        return None

    def settle(self, obs):
        odd = obs["received_odd"]
        even = obs["received"] - odd
        self.diff += (odd - even) if self.odd_is_challenger else (even - odd)
        self.total += obs["received"]

    def reply(self, finished_pass, obs, share_theta):
        next_pass = finished_pass + 1
        if self.challenger is not None:
            self.settle(obs)
            self.step += 1
            if self.step == args.ab_len:
                if self.diff > args.ab_delta * self.total:
                    self.incumbent = self.challenger  # keep climbing the same way
                    self.accepted = True
                    self.tried_other = True
                elif self.tried_other:
                    self.done = True
                else:
                    self.direction, self.tried_other = -self.direction, True
                self.challenger = None
        if self.incumbent is None and next_pass >= args.ab_start:
            self.incumbent = share_theta
        if self.incumbent is None:
            return share_theta, -1
        if self.challenger is None and not self.accepted:
            self.incumbent = share_theta
        if self.challenger is None and not self.done and args.ab_start <= next_pass <= args.ab_end - args.ab_len + 1:
            self.challenger = self.next_challenger()
            if self.challenger is None:
                self.done = True
            self.step, self.diff, self.total = 0, 0, 0
        if self.challenger is None:
            return self.incumbent, -1
        self.odd_is_challenger = self.step % 2 == 0
        if self.odd_is_challenger:
            return self.incumbent, self.challenger
        return self.challenger, self.incumbent


ab = AbTest()
theta_odd = -1

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
    elif mode in ("adaptive", "abtest"):
        for b in range(7):
            sf11[b] += obs.get("sf11_by_elevation", [0] * 7)[b]
            sf12[b] += obs.get("sf12_by_elevation", [0] * 7)[b]
        theta = learn_theta()
        if mode == "abtest":
            theta, theta_odd = ab.reply(obs["pass"], obs, theta)
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
    reply = {"p": p, "margin_db": margin, "theta_deg": theta}
    if theta_odd >= 0:
        reply["theta_odd_deg"] = theta_odd
    print(json.dumps(reply), flush=True)
