"""Per-pass controller for leo_policies --controller. Reads one observation per line on stdin and
answers with the transmit probability and link margin for the next pass.

Stage 3 has no intelligence: 'constant' returns fixed values; 'scripted' changes them from a given
pass. It refuses any observation field a satellite gateway could not observe."""
import argparse
import json
import sys

OBSERVABLE = {"pass", "received", "received_by_sf", "devices_heard", "rssi_mean_dbm", "rssi_min_dbm"}

parser = argparse.ArgumentParser()
parser.add_argument("--p", type=float, required=True)
parser.add_argument("--margin", type=float, required=True)
parser.add_argument("--p-from", default="", help="PASS:VALUE, new p for every pass from PASS on")
parser.add_argument("--margin-from", default="", help="PASS:VALUE, new margin for every pass from PASS on")
args = parser.parse_args()


def change(spec):
    if not spec:
        return None
    at, value = spec.split(":")
    return int(at), float(value)


p_change, margin_change = change(args.p_from), change(args.margin_from)
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
    p, margin = args.p, args.margin
    if p_change and next_pass >= p_change[0]:
        p = p_change[1]
    if margin_change and next_pass >= margin_change[0]:
        margin = margin_change[1]
    print(json.dumps({"p": p, "margin_db": margin}), flush=True)
