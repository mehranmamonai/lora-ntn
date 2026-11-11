"""Shared by controller.py and train_bandit.py, so both compute the bandit context the same way.

Context, from gateway-observable data only:
- rate context: highest Doppler-rate bin (edges 0, 60, 93, 144, 200, 286 Hz/s) holding at least 3 SF12
  receptions so far; 0 when none qualify yet, 1-6 for the bins.
- load context: distinct devices heard so far, <500 -> 0, 500-2000 -> 1, >2000 -> 2.
Arms: SF12 Doppler-rate thresholds in Hz/s; None means no threshold."""

ARMS = [60.0, 93.0, 144.0, 200.0, 286.0, None]


def rate_context(sf12_by_rate_cumulative):
    best = 0
    for b, count in enumerate(sf12_by_rate_cumulative):
        if count >= 3:
            best = b + 1
    return best


def load_context(devices_heard_total):
    if devices_heard_total < 500:
        return 0
    return 1 if devices_heard_total <= 2000 else 2


def context_key(sf12_by_rate_cumulative, devices_heard_total):
    return f"{rate_context(sf12_by_rate_cumulative)},{load_context(devices_heard_total)}"


def arm_key(arm):
    return "none" if arm is None else f"{arm:g}"
