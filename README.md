# LLM coding-agent sandbox storage study

Code and data for the paper *Characterizing and Optimizing File-System I/O of LLM Coding-Agent Workloads: Implications for AI Agent Sandbox Infrastructure* by Ameerul Ali Shah Pattan. The paper replays 16,219 recorded tool calls of an LLM coding agent under system-call tracing to measure how agent sandboxes use storage, then measures storage optimizations for them.

## What is here

| Path | Contents |
|---|---|
| `tools/extract_meta.py` | Reads the SWE-bench evaluation logs of a run and extracts each task's base commit |
| `tools/instances.py` | Builds the replay table: repository, base commit, SWE-bench version, interpreter, environment |
| `tools/replay.py` | Rebuilds a task sandbox in private mount and PID namespaces and replays every recorded tool call; modes `trace`, `untraced`, `nopyc`, `precompiled` (traced), `overlay`, `overlay_precompiled` (real overlayfs upper layer), `untraced_nopyc`, `untraced_precompiled` (timing), `resident` (page-cache scan), `stack` (O1–O3 combined), `remote` (emulated remote image layer) |
| `tools/run_all.py` | Runs all replays with N workers |
| `tools/run_subset.py` | Runs a list of tasks in one worker under several modes |
| `tools/run_timing.py` | Untraced timing of default, disabled and precompiled bytecode, interleaved per task |
| `tools/provision_bench.py` | Provisioning benchmark: full copy, local clone, worktree and overlay mount, five trials per repository |
| `tools/setup_bench.py` | Setup at each task's commit: clone + checkout, warm overlay mount, per-version base image + checkout delta (random order) |
| `tools/git_attr_bench.py` | Read-only git calls replayed with default attribute lookup and with `attr.tree=HEAD`: operation counts, time, output identity |
| `tools/run_resident.py` | Cold-cache untraced replays with a `mincore` scan of image files (`replay.py --mode resident`) |
| `tools/run_timing2.py` | Bytecode timing with the three variants in random order per task and repetition |
| `tools/run_stack.py` | O1–O3 combined: replays the overlay subset with `replay.py --mode stack` |
| `tools/remotefs.py` | Read-only FUSE passthrough that emulates a remote image layer: per-request delay and three client-caching regimes (none, short, long) |
| `tools/run_remote.py` | O5 on the emulated remote layer: local baseline and three caching regimes, with and without added delay, in random order per task |
| `tools/git_remote_bench.py` | O3 on the emulated remote layer: the slowest history searches with and without `attr.tree=HEAD` |
| `tools/latency_image.py` | O5 trace-driven bounds restricted to the image layers |
| `tools/git_reach.py` | Size of git objects reachable from a task's base commit versus the full clone |
| `tools/git_attr_distinct.sh` | Total versus distinct failed `.gitattributes` lookups of a history search |
| `tools/make_manifest.py` | Writes everything in `reproducibility/` |
| `tools/fidelity.py` | Main findings over all calls, matching calls and tasks whose test calls all match |
| `tools/sharing.py` | Measured page-cache footprints and the co-location scenario |
| `tools/gitattr_trace.py` | Share of failed lookups and metadata operations that are `.gitattributes` probes |
| `tools/revision_numbers.py` | Numbers and tables for the analyses above (run by `paper_numbers.py`) |
| `tools/command_stats.py` | Command classifier (static, no replay) |
| `tools/analyze.py` | Aggregates replay outputs into per-task, per-call and model tables |
| `tools/paper_numbers.py` | Produces every number and table used in the paper |
| `tools/figures.py` | Produces every figure |
| `results/` | Derived datasets: `instances.csv` (per task), `commands.csv` (per tool call), `snapshot_steps.csv`, `ws_growth.csv`, `latency_model.csv`, `fleet_sharing*.csv`, `ablation.csv`, `ablation_overlay.csv`, `bytecode_timing.csv`, `provisioning.csv`, `provisioning_raw.json`, `untraced_timing.csv`, `key_numbers.json`, `extra_numbers.json`; revision analyses: `fidelity.*`, `setup_bench.csv`, `setup_base_*`, `git_attr_bench.csv`, `gitattr_trace.json`, `git_attr_distinct.json`, `git_reach.csv`, `resident_tasks.csv`, `sharing_measured.*`, `latency_image.*`, `bytecode_timing_random_r*.csv`, `stack.csv`, `remote_bench.csv`, `git_remote_bench.csv` |
| `reproducibility/` | Proof that the experiments ran as described: `logs/` (run logs with timestamps), `ENVIRONMENT.md` (machine and tool versions), `envs.tar.gz` (package list of every replay environment) and `MANIFEST.sha256` (SHA-256 checksum of every released file and archive) |
| `data/` | Task table (`instances.json`), base commits (`meta_v242.json`), ablation, timing, page-cache and remote-layer task lists |
| `runs*/` | Per-task replay outputs (`summary.json`, `commands.jsonl`, `files.jsonl.gz` with per-file operation counts), archived with this code on Zenodo (DOI in the paper's data-availability statement) as `runs_traced.tar.xz.part-*`, `runs_untraced.tar.xz`, `runs_revision1.tar.xz` (page-cache, combined-stack and counterbalanced timing runs) and `runs_remote.tar.xz` (emulated remote layer). Unpack with `cat runs_traced.tar.xz.part-* \| tar -xJf -` and `tar -xJf <archive>` |

## Inputs

The input trajectories and evaluation logs are published by the SWE-bench project:

- `https://github.com/SWE-bench/20260901_mini-v2.4.2_gemini-3-5-flash` (replayed)
- `https://github.com/SWE-bench/20260902_mini-v2.4.6_gemini-3-5-flash` (command analysis only)

## Reproduce

Requirements: Linux with `unshare` and bind mounts (root or user namespaces), `strace` 6.x with `--seccomp-bpf`, `git`, CPython 3.9 and 3.11, and the `swebench` Python package (v4.1.0) for environment specifications; the remote-layer runs also need FUSE 3, `pyfuse3` and `trio`. Edit `ROOT` at the top of each script.

```bash
git clone --depth 1 https://github.com/SWE-bench/20260901_mini-v2.4.2_gemini-3-5-flash data/20260901_mini-v2.4.2_gemini-3-5-flash
python tools/extract_meta.py data/20260901_mini-v2.4.2_gemini-3-5-flash data/meta_v242.json
for r in django/django sympy/sympy sphinx-doc/sphinx pytest-dev/pytest psf/requests; do git clone https://github.com/$r repos_full/$(basename $r); done
python tools/instances.py
python tools/run_all.py 2                      # traced replay
python tools/run_all.py 2 untraced             # timing pass
python tools/run_all.py 2 nopyc data/ablation_subset.txt
python tools/run_all.py 2 precompiled data/ablation_subset.txt
python tools/run_subset.py overlay data/ablation_subset.txt 3 overlay_precompiled   # O2 on real overlayfs
for r in 0 1 2; do python tools/run_timing2.py $r; done   # O2 timing, counterbalanced over 3 repetitions
unshare -m python tools/setup_bench.py         # O1 (SETUP_N=160 for the sampled run)
unshare -m python tools/git_attr_bench.py 40   # O3
python tools/run_resident.py data/resident_set.txt && python tools/sharing.py   # page-cache footprint, O6
python tools/run_stack.py                      # O1-O3 combined
unshare -m python tools/run_remote.py          # O5 on the emulated remote layer (needs FUSE 3 and pyfuse3)
unshare -m python tools/git_remote_bench.py    # O3 on the emulated remote layer
python tools/fidelity.py && python tools/gitattr_trace.py
python tools/analyze.py && python tools/paper_numbers.py && python tools/figures.py
```

Tracing inflates execution time but not operation counts or bytes; all timings in the paper come from the recorded trajectories or the untraced pass.

## Provenance

Everything that shows the experiments ran as described is in `reproducibility/`. To check that no file has changed since release, run `sha256sum -c reproducibility/MANIFEST.sha256` from the repository root; the `archive/` lines check once the Zenodo archives are downloaded into `archive/`.

## License

Code: MIT (`LICENSE`). Derived data: CC BY 4.0. The input trajectories keep their original licenses.
