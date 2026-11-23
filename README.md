# Network-Side Doppler Mitigation for Direct-to-Satellite LoRaWAN

Code, simulation scenarios and raw results for the manuscript

> M. M. Mamonai, "Network-Side Doppler Mitigation for Direct-to-Satellite LoRaWAN Using Gateway
> Reception Statistics," manuscript submitted to IEEE Internet of Things Journal, 2026.

Author: Mehran M. Mamonai, Mehran University of Engineering and Technology, Jamshoro, Pakistan.
ORCID: [0009-0007-5426-5943](https://orcid.org/0009-0007-5426-5943)

The study asks whether a controller at the satellite gateway, using only reception counts the
network already has, can reduce the SF12 packet loss caused by the Doppler rate of a low Earth
orbit pass. Everything runs in ns-3 with the SIGNET LoRaWAN module; no satellite or radio hardware
is involved.

## Repository layout

| Path | Contents |
|---|---|
| `sim/` | ns-3 scenarios. `leo_policies.cc` is the main simulator (560 km orbit, 3GPP TR 38.811 channel, Doppler shift and rate filter, collision models C1-C3, per-pass controller hook, Class B beacons). `leo_doppler.h` holds the orbit and Doppler model. `run_matrix.sh` is the run matrix of the last experiment. |
| `scripts/run.sh` | Builds the pinned ns-3 and LoRaWAN module once, applies the patch, compiles `sim/`, then runs `sim/run_matrix.sh`. |
| `scripts/patch_lorawan.py` | Adds a receive filter to the gateway PHY of the LoRaWAN module so a scenario can drop packets (Doppler). Idempotent. |
| `scripts/controller.py` | The per-pass controller. Reads one JSON observation per pass on stdin and returns the next settings. Uses gateway-observable fields only. |
| `scripts/summarize.py` | Summary and pre-registered checks for the last experiment. |
| `experiments/<name>/` | For each experiment the paper uses: the exact `run_matrix.sh` that was run, and `data/` with the raw `runs.txt`, the `summary.txt` it produced, and `provenance.txt` (source commit, start time). |
| `figs/extract_data.py` | Rebuilds the figure tables in `figs/data/` from `experiments/`. |
| `figs/make_figures.py` | Draws the result figures from `figs/data/`. |
| `figs/fig_architecture.tex` | TikZ source of the system architecture figure. |
| `paper.tex` | Manuscript source (IEEEtran). Build with `pdflatex paper.tex` (twice). |

## Experiments behind the paper

Each experiment ran at the commit listed, which is also tagged `experiment/<folder>` (for example
`git checkout experiment/static-cutoff`). That commit holds the simulator and controller exactly as
they were; run `scripts/run.sh` to repeat the experiment.

| Folder | Commit | Used for |
|---|---|---|
| `efficiency-bound` | `f7ecea4` | Link-only baseline under C1 (seeds 21-25) |
| `load-control-bound` | `b34999c` | Link-only baseline under C1 at high load; load-control bound |
| `collision-model-gate` | `26c488b` | Link-only baseline under C2 |
| `collision-locking-gate` | `d9f6ec6` | Link-only baseline under C3 |
| `stage4-controller` | `436368e` | Elevation-aware oracle (headroom figure) |
| `stage4-revision` | `a903e7d` | Final controller, 192 scenarios, seeds 21-30 (Doppler-loss figure, results table, per-pass trajectory) |
| `beacon-reach` | `aed4dc4` | Beacon versus instant setting delivery (controller-limit figure) |
| `stage5-bandit` | `ad022a8` | Contextual bandit choosing a Doppler-rate threshold (Section VI-C). |
| `stage5-offline` | none | `elevation_vs_rate.py`: geometry check, no simulation, giving the 13.3% and 30.0% misclassification of a single elevation threshold (Section VI-C). Run with `python elevation_vs_rate.py`. |
| `revision-paired` | none | Paired per-seed reanalysis of `stage4-revision` against link-only (`paired.py`), and fairness and energy (`fairness_energy.py`). Run with `python paired.py ../` from that folder (needs `scipy`). |
| `hindsight-threshold` | `1fd9523` | Fixed SF12 cut-offs 20-80 deg (hindsight-best threshold), controller without exploration, oracle on seeds 26-30 (Table II, Fig. 4, Section VI-C). |
| `rule-revision` | `2bd2573` | Share rule with tuned share fraction and lowest bin; tuning kept the original rule (Section VI-C). |
| `ab-cutoff` | `b7a0f35` | Within-pass A/B search over cut-offs between odd and even device addresses (Section VI-C). |
| `static-cutoff` | `0c1cae7` | Static 40 and 50 deg cut-offs in all 192 scenarios, cut-off chosen on tuning seeds, and per-bin SF12 sent/Doppler-lost/received under link-only (Section VI-C). |

Seeds 16-20 were used only to choose settings; seeds 21-30 are test seeds.

## Reproducing the figures from the recorded data

Needs Python 3 with `matplotlib` and `numpy`.

```bash
python figs/extract_data.py experiments    # rewrites figs/data/*.csv
python figs/make_figures.py                # writes figs/fig_*.pdf and .svg
```

`extract_data.py` reproduces the committed `figs/data/*.csv` byte for byte.

## Re-running the simulations

Requirements: Linux, `git`, `g++` with C++20 support, `cmake`, `ninja` or `make`, `python3`, and
`flock`. `scripts/run.sh` clones ns-3 (`ns-3.48`) and the LoRaWAN module (commit `e45b4af`) into
`~/lora-ntn-sim/`, so the first build needs network access and a few GB of disk. The runs reported in
the paper used a Linux virtual machine with 4 GB of RAM.

```bash
git checkout a903e7d          # for example, the final controller experiment
bash scripts/run.sh           # results go to results/runs.txt and results/summary.txt
```

Runs use all but one CPU core. The full matrix of a single experiment takes several hours on a
small machine.

Some run scripts end by comparing against an earlier experiment and look for its `runs.txt` under
`~/lora-ntn-runs/<id>-<commit>/repo/results/`. Copy the matching `experiments/<name>/data/runs.txt`
there, or ignore that last step; the simulation results in `results/runs.txt` do not depend on it.

Each line of `runs.txt` starting with `RUN` is one simulated scenario, written as `key=value`
fields (policy, collision model, Doppler reading, gain, device count, seed, delivered and lost
packets by cause).

## License

GNU General Public License v2.0, the license of ns-3 and the LoRaWAN module that this code
extends. See `LICENSE`.
