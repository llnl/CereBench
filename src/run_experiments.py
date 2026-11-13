#!/usr/bin/env python3


import argparse
import csv
import json
import os
import platform
import shlex
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    plt = None

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
BUILD_ROOT = REPO_ROOT / "build"

WSE_SERVER_DEFAULT = "http://localhost:8080"




CG_DOTPROD_SCRIPT = SRC / "run_compare_CG-dotprod.py"
ALLREDUCE_SCRIPT = SRC / "run_compare_allreduce.py"

CG_BENCHMARKS = {
    "chain": {"label": "Chain", "category": "cg_dotprod"},
    "two_phase": {"label": "XY Two-Phase", "category": "cg_dotprod"},
    "partial_fusion_chain": {"label": "Chain", "category": "cg_dotprod_fused"},
    "partial_fusion_two_phase": {"label": "XY Two-Phase", "category": "cg_dotprod_fused"},
}

CATEGORY_LABELS = {
    "allreduce": "AllReduce",
    "cg_dotprod": "CG Dot Product",
    "cg_dotprod_fused": "CG Dot Product (Fused)",
}
TOPOLOGY_COLORS = {"Chain": "#4472C4", "XY Two-Phase": "#ED7D31"}


def parse_int_list(text, label):
    values = []
    for item in text.replace(",", " ").split():
        try:
            value = int(item)
        except ValueError:
            raise SystemExit(f"invalid {label} value: {item}")
        if value <= 0:
            raise SystemExit(f"{label} values must be positive")
        values.append(value)
    if not values:
        raise SystemExit(f"at least one {label} value is required")
    return values


def teardown_bundle(server, job):
    print()
    print(f"tearing down wafer allocation {job}")
    subprocess.run(
        ["env", f"CSRTSERV={server}", "csclient", "bundle", "-bn", job, "--cancel"],
        cwd=str(REPO_ROOT),
    )


def _read_csv(path):
    with path.open(newline="") as file:
        return list(csv.DictReader(file))


def plot_vs_b(args, reference_k, b_values, allreduce_out, cg_out_by_k, output_root):
    if plt is None:
        return None

    allreduce_rows = _read_csv(allreduce_out / "summary.csv")
    cg_rows = [r for r in _read_csv(cg_out_by_k[reference_k] / "summary.csv") if r["metric"] == "total"]

    figure, axes = plt.subplots(1, 3, figsize=(18, 5.5))

    # allreduce panel
    for bench_key, label in (("chain", "Chain"), ("two_phase", "XY Two-Phase")):
        rows = sorted((r for r in allreduce_rows if r["benchmark"] == bench_key), key=lambda r: int(r["B"]))
        xs = [int(r["B"]) for r in rows]
        ys = [float(r["mean_microseconds"]) for r in rows]
        axes[0].plot(xs, ys, marker="o", linewidth=2, color=TOPOLOGY_COLORS[label], label=label)

    # cg dotprod / cg dotprod fused panels, both read from the same reference-K summary
    for axis, category in ((axes[1], "cg_dotprod"), (axes[2], "cg_dotprod_fused")):
        for bench_key, bench in CG_BENCHMARKS.items():
            if bench["category"] != category:
                continue
            rows = sorted((r for r in cg_rows if r["benchmark"] == bench_key), key=lambda r: int(r["B"]))
            xs = [int(r["B"]) for r in rows]
            ys = [float(r["mean_microseconds"]) for r in rows]
            axis.plot(xs, ys, marker="o", linewidth=2, color=TOPOLOGY_COLORS[bench["label"]], label=bench["label"])

    for axis, category in zip(axes, ("allreduce", "cg_dotprod", "cg_dotprod_fused")):
        axis.set_xscale("log", base=2)
        axis.set_xlabel("B, partial answer per PE")
        axis.set_ylabel("Mean total latency, microseconds")
        axis.set_title(f"{CATEGORY_LABELS[category]} (K={reference_k})" if category != "allreduce" else CATEGORY_LABELS[category])
        axis.grid(alpha=0.3)
        axis.legend(fontsize=8)

    figure.suptitle(f"Timing vs partial answer per PE (B), W={args.w}, H={args.h}")
    figure.tight_layout(rect=(0, 0, 1, 0.94))

    png_path = output_root / "timing_vs_b.png"
    pdf_path = output_root / "timing_vs_b.pdf"
    figure.savefig(png_path, dpi=180)
    figure.savefig(pdf_path)
    plt.close(figure)
    return png_path, pdf_path


def plot_vs_k(args, k_values, reference_b, allreduce_out, cg_out_by_k, output_root):
    if plt is None:
        return None

    allreduce_rows = _read_csv(allreduce_out / "summary.csv")

    figure, axes = plt.subplots(1, 3, figsize=(18, 5.5))

    # allreduce has no K -- its only size knob is B, shown here in bytes
    # (B*4) so it at least sits on a comparable "payload size" axis
    for bench_key, label in (("chain", "Chain"), ("two_phase", "XY Two-Phase")):
        rows = sorted((r for r in allreduce_rows if r["benchmark"] == bench_key), key=lambda r: int(r["B"]))
        xs = [int(r["B"]) * 4 for r in rows]
        ys = [float(r["mean_microseconds"]) for r in rows]
        axes[0].plot(xs, ys, marker="o", linewidth=2, color=TOPOLOGY_COLORS[label], label=label)
    axes[0].set_xlabel("payload size, bytes (B*4)")

    for axis, category in ((axes[1], "cg_dotprod"), (axes[2], "cg_dotprod_fused")):
        for bench_key, bench in CG_BENCHMARKS.items():
            if bench["category"] != category:
                continue

            xs, ys = [], []
            for k_value in k_values:
                rows = [
                    r for r in _read_csv(cg_out_by_k[k_value] / "summary.csv")
                    if r["metric"] == "total" and r["benchmark"] == bench_key and int(r["B"]) == reference_b
                ]
                if not rows:
                    continue
                xs.append(args.w * args.h * k_value)
                ys.append(float(rows[0]["mean_microseconds"]))

            axis.plot(xs, ys, marker="o", linewidth=2, color=TOPOLOGY_COLORS[bench["label"]], label=bench["label"])
        axis.set_xlabel("nominal vector size, N = W*H*K")

    for axis, category in zip(axes, ("allreduce", "cg_dotprod", "cg_dotprod_fused")):
        axis.set_xscale("log", base=2)
        axis.set_ylabel("Mean total latency, microseconds")
        axis.set_title(f"{CATEGORY_LABELS[category]} (B={reference_b})" if category != "allreduce" else CATEGORY_LABELS[category])
        axis.grid(alpha=0.3)
        axis.legend(fontsize=8)

    figure.suptitle(f"Timing vs vector size, W={args.w}, H={args.h}")
    figure.tight_layout(rect=(0, 0, 1, 0.94))

    png_path = output_root / "timing_vs_k.png"
    pdf_path = output_root / "timing_vs_k.pdf"
    figure.savefig(png_path, dpi=180)
    figure.savefig(pdf_path)
    plt.close(figure)
    return png_path, pdf_path


def run_sweep(args):
    k_values = parse_int_list(args.k_values, "K")
    b_values = parse_int_list(args.b_values, "B")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path(args.results_dir) if args.results_dir else REPO_ROOT / "results" / f"full_sweep_{timestamp}"
    if not output_root.is_absolute():
        output_root = REPO_ROOT / output_root
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    print(f"Output directory: {output_root}")
    print(f"K values: {k_values}")
    print(f"B values: {b_values}")
    print(f"Total CG-dotprod trials: {len(k_values) * len(b_values) * 4 * args.runs}")
    print(f"Total AllReduce trials: {len(b_values) * 2 * args.runs}")

    if args.dry_run:
        print(
            "\n--dry-run: sweep mode has no syntax-check-only path (it drives "
            "run_compare_allreduce.py / run_compare_CG-dotprod.py directly, "
            "neither of which support --dry-run) -- stopping before touching "
            "any hardware. Use --smoke-test --dry-run to syntax-check scripts instead."
        )
        return

    # leg 1: AllReduce, one bundle for its whole B sweep
    allreduce_job = f"allreduce-sweep-{timestamp}"
    allreduce_out = output_root / "allreduce"
    allreduce_cmd = [
        sys.executable, str(ALLREDUCE_SCRIPT),
        "--w", str(args.w), "--h", str(args.h),
        "--b-values", args.b_values,
        "--sx", str(args.sx), "--sy", str(args.sy),
        "--wait-alpha", str(args.wait_alpha),
        "--arch", args.arch,
        "--input-mode", args.input_mode,
        "--input-seed", str(args.input_seed),
        "--clock-mhz", str(args.clock_mhz),
        "--server", args.server,
        "--job", allreduce_job,
        "--lifetime", str(args.lifetime),
        "--runs", str(args.runs),
        "--results-dir", str(allreduce_out),
    ]
    try:
        subprocess.run(allreduce_cmd, check=True)
    finally:
        teardown_bundle(args.server, allreduce_job)

    # leg 2: CG dot product, all 4 variants, one bundle for the whole
    # K x B grid -- exactly src/run_CG_k_sweep.sh's own methodology
    cg_job = f"cg-k-sweep-{timestamp}"
    cg_out_by_k = {}

    try:
        for index, k_value in enumerate(k_values):
            n_value = args.w * args.h * k_value
            cg_out = output_root / "cg_dotprod" / f"K_{k_value}_N_{n_value}"
            cg_out_by_k[k_value] = cg_out

            cmd = [
                sys.executable, str(CG_DOTPROD_SCRIPT),
                "--w", str(args.w), "--h", str(args.h),
                "--k", str(k_value),
                "--runs", str(args.runs),
                "--b-values", args.b_values,
                "--sx", str(args.sx), "--sy", str(args.sy),
                "--wait-alpha", str(args.wait_alpha),
                "--arch", args.arch,
                "--input-mode", args.input_mode,
                "--input-seed", str(args.input_seed),
                "--clock-mhz", str(args.clock_mhz),
                "--server", args.server,
                "--job", cg_job,
                "--lifetime", str(args.lifetime),
                "--results-dir", str(cg_out),
            ]
            if index > 0:
                cmd.append("--skip-queue")

            subprocess.run(cmd, check=True)
    finally:
        teardown_bundle(args.server, cg_job)

    reference_k = k_values[0]
    reference_b = min(b_values, key=lambda b: abs(b - 256))

    vs_b = plot_vs_b(args, reference_k, b_values, allreduce_out, cg_out_by_k, output_root)
    vs_k = plot_vs_k(args, k_values, reference_b, allreduce_out, cg_out_by_k, output_root)

    print()
    print("Created:")
    for pair in (vs_b, vs_k):
        if pair:
            for path in pair:
                print(f"  {path}")


# ==========================================================================
# smoke-test mode (--smoke-test) -- quick/full pass-or-fail across every
# registered experiment, no sweep, no plots
# ==========================================================================

# generated build artifacts never get written into src/<experiment>/
# each experiment gets synced into build/<experiment>/ once per run and
# every command runs there, so src/ stays clean and build/ is disposable
_GENERATED_MARKERS = (
    ".gemv-backup-20260730_093918",  # pre-existing backup dir, not a source file
)


def sync_sources(experiment_dir):

    destination = BUILD_ROOT / experiment_dir.name
    destination.mkdir(parents=True, exist_ok=True)

    for item in experiment_dir.iterdir():
        if item.name in _GENERATED_MARKERS:
            continue

        target = destination / item.name

        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)

    return destination


# experiment registry
#
# each entry is a dict:
#   name         short id used on the command line and in results/
#   dir          experiment directory, relative to src/
#   family       "tungsten" or "csl" (see module docstring)
#   sim          {"quick": [cmds], "full": [cmds]} shell commands, run in
#                sequence inside `dir`, that exercise the simulator
#   hardware     same shape for real wafer hardware, or None if the
#                experiment has no hardware path at all
#   artifacts    result files/globs (relative to `dir`) to copy into the
#                standardized results/ tree on success, best-effort
#
# {server} / {job} / {cmaddr} placeholders are filled in per run

def _tungsten_gemv_family(name, dirname, quick, full, runs_quick=1, runs_full=5):
    """CG-dotprod-*/GEMV-*-allreduce all share one Makefile template:
    `make test MODE=sim ...` and `make wse-queue ... && ./run_5_timings.sh`
    for hardware."""

    def sim_cmds(p):
        return [
            "make clean",
            "make test MODE=sim ARCH=sdr "
            f"W={p['W']} H={p['H']} M={p['M']} N={p['N']} "
            f"SX={p['SX']} SY={p['SY']} WAIT_ALPHA=1 INPUT_MODE=pattern",
        ]

    def hardware_cmds(p, runs):
        return [
            "make clean",
            'export JOB="{job}"',
            "make build-run ARCH=sdr "
            f"W={p['W']} H={p['H']} M={p['M']} N={p['N']} "
            f"SX={p['SX']} SY={p['SY']} WAIT_ALPHA=1 INPUT_MODE=pattern",
            "make wse-queue WSE_JOB=\"$JOB\" WSE_SERVER={server} "
            f"WSE_WIDTH={p['W']} WSE_HEIGHT={p['H']} WSE_LIFETIME=500",
            "JOB=\"$JOB\" WSE_SERVER={server} "
            f"W={p['W']} H={p['H']} B={p['M']} RUNS={runs} ./run_5_timings.sh",
        ]

    return {
        "name": name,
        "dir": dirname,
        "family": "tungsten",
        "sim": {"quick": sim_cmds(quick), "full": sim_cmds(full)},
        "hardware": {
            "quick": hardware_cmds(quick, runs_quick),
            "full": hardware_cmds(full, runs_full),
        },
        "artifacts": [
            "results-sim.csv",
            "timings-sim.csv",
            "timings-sim-per-pe.csv",
            "out_hw/timing_5runs/results.csv",
        ],
    }


CG_QUICK = {"W": 16, "H": 16, "M": 256, "N": 256, "SX": 4, "SY": 4}
CG_FULL = {"W": 512, "H": 512, "M": 32, "N": 512, "SX": 23, "SY": 23}

EXPERIMENTS = [
    _tungsten_gemv_family("cg-dotprod-chain", "CG-dotprod-chain", CG_QUICK, CG_FULL),
    _tungsten_gemv_family("cg-dotprod-xy2phase", "CG-dotprod-xy2phase", CG_QUICK, CG_FULL),
    _tungsten_gemv_family(
        "cg-dotprod-partial-fusion-chain",
        "CG-dotprod-partial-fusion-chain",
        CG_QUICK,
        CG_FULL,
    ),
    _tungsten_gemv_family(
        "cg-dotprod-partial-fusion-xy2phase",
        "CG-dotprod-partial-fusion-xy2phase",
        CG_QUICK,
        CG_FULL,
    ),
    {
        "name": "ping-pong-tung",
        "dir": "ping-pong-tung",
        "family": "tungsten",
        "sim": {
            "quick": ["make clean", "make test MODE=sim tensor_size=1 DIST=0 NUM_MSGS=1"],
            "full": ["make clean", "make test MODE=sim tensor_size=64 DIST=0 NUM_MSGS=8"],
        },
        "hardware": {
            "quick": [
                "make clean",
                'export WSE_JOB="{job}"',
                "make test MODE=wse tensor_size=1 DIST=0 NUM_MSGS=1 "
                'WSE_JOB="$WSE_JOB" WSE_SERVER={server}',
            ],
            "full": [
                "make clean",
                'export WSE_JOB="{job}"',
                "make test MODE=wse tensor_size=64 DIST=0 NUM_MSGS=8 "
                'WSE_JOB="$WSE_JOB" WSE_SERVER={server}',
            ],
        },
        "artifacts": ["out-sim.bin", "out-wse.bin"],
    },
    {
        "name": "latency-heatmap",
        "dir": "latency-heatmap",
        "family": "tungsten",
        "sim": {
            "quick": [
                "make force-rebuild",
                "make test MODE=sim W=10 H=10 CX=5 CY=5 NPROBE=16",
                "make csv",
            ],
            "full": [
                "make force-rebuild",
                "make test MODE=sim W=100 H=100 CX=50 CY=50 NPROBE=16",
                "make csv",
            ],
        },
        "hardware": {
            "quick": [
                "make force-rebuild",
                'export WSE_JOB="{job}"',
                "make test MODE=wse W=10 H=10 CX=5 CY=5 NPROBE=16 "
                'WSE_JOB="$WSE_JOB" WSE_SERVER={server}',
                'make csv-wse WSE_JOB="$WSE_JOB" WSE_SERVER={server}',
            ],
            "full": [
                "make force-rebuild",
                'export WSE_JOB="{job}"',
                "make test MODE=wse W=100 H=100 CX=50 CY=50 NPROBE=16 "
                'WSE_JOB="$WSE_JOB" WSE_SERVER={server}',
                'make csv-wse WSE_JOB="$WSE_JOB" WSE_SERVER={server}',
            ],
        },
        "artifacts": ["rtt.csv"],
    },
]


EXPERIMENTS_BY_NAME = {experiment["name"]: experiment for experiment in EXPERIMENTS}


def build_script(experiment, target, size, server, cmaddr, job=""):

    commands = experiment[target]
    if commands is None:
        raise ValueError(f"{experiment['name']} has no {target} path")

    return " ; ".join(commands[size]).format(server=server, cmaddr=cmaddr or "", job=job)


def check_script_syntax(script):

    result = subprocess.run(
        ["bash", "-n", "-c", script],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, result.stderr


def run_in_cerebras_env(script, cwd):

    inner = f"set -euo pipefail; cd {shlex.quote(str(cwd))}; {script}"
    command = ["bash", "-c", inner]

    started = time.time()
    result = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    duration = time.time() - started
    return result.returncode, result.stdout + result.stderr, duration


def copy_artifacts(experiment_dir, patterns, dest):
    dest.mkdir(parents=True, exist_ok=True)
    copied = []

    for pattern in patterns:
        for match in experiment_dir.glob(pattern):
            if not match.is_file():
                continue

            target = dest / match.relative_to(experiment_dir).as_posix().replace("/", "__")
            target.write_bytes(match.read_bytes())
            copied.append(target.name)

    return copied


def run_experiment(experiment, target, size, server, cmaddr, results_dir, dry_run=False):
    name = experiment["name"]
    exp_dir = sync_sources(SRC / experiment["dir"])
    out_dir = results_dir / name
    out_dir.mkdir(parents=True, exist_ok=True)

    job = f"{name}-{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    record = {
        "name": name,
        "family": experiment["family"],
        "target": target,
        "size": size,
        "status": None,
        "duration_s": None,
        "log": str(out_dir / f"{target}-{size}.log"),
    }

    try:
        script = build_script(experiment, target, size, server, cmaddr, job=job)
    except ValueError as error:
        record["status"] = "UNSUPPORTED"
        record["reason"] = str(error)
        Path(record["log"]).write_text(record["reason"] + "\n")
        return record

    syntax_ok, syntax_error = check_script_syntax(script)
    if not syntax_ok:
        record["status"] = "BAD_SCRIPT"
        record["reason"] = f"generated script fails `bash -n`: {syntax_error.strip()}"
        Path(record["log"]).write_text(script + "\n\n" + syntax_error)
        return record

    if dry_run:
        record["status"] = "DRY_RUN_OK"
        record["reason"] = "syntax-checked only; not executed (--dry-run)"
        Path(record["log"]).write_text(script + "\n")
        return record

    returncode, log, duration = run_in_cerebras_env(script, exp_dir)

    record["duration_s"] = round(duration, 1)
    record["status"] = "PASS" if returncode == 0 else "FAIL"

    if target == "hardware":
        teardown_script = (
            f"CSRTSERV={shlex.quote(server)} csclient bundle -bn {shlex.quote(job)} --cancel"
        )
        teardown_rc, teardown_log, teardown_duration = run_in_cerebras_env(teardown_script, exp_dir)
        record["teardown"] = "OK" if teardown_rc == 0 else "FAILED"
        record["teardown_duration_s"] = round(teardown_duration, 1)
        record["lifecycle_duration_s"] = round(duration + teardown_duration, 1)
        log += f"\n\n=== teardown ({record['teardown']}, {teardown_duration:.1f}s) ===\n{teardown_log}"
        if teardown_rc != 0:
            print(f"  warning: teardown failed for job {job}, bundle may still be allocated")

    Path(record["log"]).write_text(log)

    artifacts_dir = out_dir / "artifacts"
    copied = copy_artifacts(exp_dir, experiment.get("artifacts", []), artifacts_dir)
    if copied:
        record["artifacts"] = copied

    return record


def prune_old_results(keep, current_dir):

    results_root = REPO_ROOT / "results"
    if not results_root.is_dir():
        return

    run_dirs = sorted(
        (
            path
            for path in results_root.iterdir()
            if path.is_dir() and path != current_dir
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    for stale in run_dirs[keep:]:
        shutil.rmtree(stale, ignore_errors=True)


def write_summary(records, results_dir):
    summary_json = results_dir / "summary.json"
    summary_json.write_text(json.dumps(records, indent=2) + "\n")

    summary_csv = results_dir / "summary.csv"
    with summary_csv.open("w", newline="") as file:
        fieldnames = [
            "name", "family", "target", "size", "status", "duration_s",
            "teardown", "teardown_duration_s", "lifecycle_duration_s", "reason", "log",
        ]
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(record)

    return summary_json, summary_csv


def print_table(records):
    print()
    print(f"{'name':<36} {'target':<9} {'size':<6} {'status':<10} {'seconds':>8}")
    print("-" * 74)
    for record in records:
        print(
            f"{record['name']:<36} {record['target']:<9} {record['size']:<6} "
            f"{record['status']:<10} {str(record.get('duration_s') or ''):>8}"
        )


def run_smoke_test(args):
    if args.list:
        print(f"{'name':<36} {'family':<10} {'hardware?':<10} dir")
        for experiment in EXPERIMENTS:
            hw = "yes" if experiment["hardware"] else "no"
            print(f"{experiment['name']:<36} {experiment['family']:<10} {hw:<10} {experiment['dir']}")
        return

    selected = EXPERIMENTS
    if args.only:
        names = [name.strip() for name in args.only.split(",")]
        missing = [name for name in names if name not in EXPERIMENTS_BY_NAME]
        if missing:
            raise SystemExit(f"Unknown experiment(s): {', '.join(missing)} (see --list)")
        selected = [EXPERIMENTS_BY_NAME[name] for name in names]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = (
        Path(args.results_dir) if args.results_dir else REPO_ROOT / "results" / timestamp
    )
    results_dir.mkdir(parents=True, exist_ok=True)

    (results_dir / "run_config.json").write_text(
        json.dumps(
            {
                "target": args.target,
                "size": args.size,
                "server": args.server,
                "dry_run": args.dry_run,
                "host": platform.node(),
                "experiments": [experiment["name"] for experiment in selected],
            },
            indent=2,
        )
        + "\n"
    )

    print(f"Running {len(selected)} experiment(s), target={args.target}, size={args.size}")
    print(f"Results: {results_dir}")

    records = []
    for experiment in selected:
        print(f"\n=== {experiment['name']} ===")
        record = run_experiment(
            experiment,
            args.target,
            args.size,
            args.server,
            None,
            results_dir,
            dry_run=args.dry_run,
        )
        print(f"  {record['status']}" + (f": {record['reason']}" if record.get("reason") else ""))
        records.append(record)

    summary_json, summary_csv = write_summary(records, results_dir)
    print_table(records)

    if args.keep_runs > 0 and not args.results_dir:
        prune_old_results(args.keep_runs, results_dir)

    print()
    print(f"Summary: {summary_json}")
    print(f"         {summary_csv}")

    if any(record["status"] == "FAIL" for record in records):
        sys.exit(1)


# ==========================================================================
# entry point
# ==========================================================================

def parse_arguments():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="run the lightweight quick/full pass-or-fail check instead of the K/N sweep",
    )
    parser.add_argument("--list", action="store_true", help="list experiments/benchmarks and exit")
    parser.add_argument(
        "--server",
        default=WSE_SERVER_DEFAULT,
        help=f"kingfisher WSE_SERVER (default: {WSE_SERVER_DEFAULT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print/syntax-check commands without executing them",
    )
    parser.add_argument("--results-dir", help="override the default results output location")

    # sweep-mode args
    parser.add_argument("--k-values", default="1,2,4,8,16")
    parser.add_argument("--b-values", default="1,4,16,64,256,1024")
    parser.add_argument("--w", type=int, default=512)
    parser.add_argument("--h", type=int, default=512)
    parser.add_argument("--sx", type=int, default=23)
    parser.add_argument("--sy", type=int, default=23)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--wait-alpha", type=int, default=1)
    parser.add_argument("--arch", default="sdr")
    parser.add_argument("--input-mode", default="pattern")
    parser.add_argument("--input-seed", type=int, default=1)
    parser.add_argument("--clock-mhz", type=float, default=850)
    parser.add_argument("--lifetime", type=int, default=40000)
    parser.add_argument("--job", help="sweep-mode wafer job name (default: auto-generated)")

    # smoke-test-mode args
    parser.add_argument(
        "--target",
        choices=("sim", "hardware"),
        default="sim",
        help="smoke-test: run in the local simulator, or on real wafer hardware (default: sim)",
    )
    parser.add_argument(
        "--size",
        choices=("quick", "full"),
        default="quick",
        help="smoke-test: small smoke config, or the large sweep config (default: quick)",
    )
    parser.add_argument(
        "--only",
        help="smoke-test: comma-separated experiment names to run (default: all); see --list",
    )
    parser.add_argument(
        "--keep-runs",
        type=int,
        default=20,
        help="smoke-test: keep only the N most recent results/<timestamp>/ dirs (default: 20; 0 disables)",
    )

    return parser.parse_args()


def main():
    args = parse_arguments()

    if args.smoke_test:
        run_smoke_test(args)
        return

    if args.list:
        print("allreduce   -- chain, two_phase          (src/chain-allreduce, src/xy2phase-allreduce)")
        for key, bench in CG_BENCHMARKS.items():
            print(f"{bench['category']:<12} -- {key:<24} (via {CG_DOTPROD_SCRIPT.name})")
        return

    run_sweep(args)


if __name__ == "__main__":
    main()
