#!/usr/bin/env python3

import argparse
import csv
import json
import os
import shlex
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    plt = None


ROOT = Path(__file__).resolve().parent

BENCHMARKS = {
    "chain": {
        "label": "Chain",
        "directory": ROOT / "chain-allreduce",
        "map": "xy-two-phase-allreduce.map",
        "image": "xy-two-phase-allreduce-run.img",
    },
    "two_phase": {
        "label": "XY Two-Phase",
        "directory": ROOT / "xy2phase-allreduce",
        "map": "xy-two-phase-allreduce.map",
        "image": "xy-two-phase-allreduce-run.img",
    },
}

METRIC = "global_cycles"


def run_command(command, cwd, env=None):
    print()
    print(f"[{cwd}]")
    print("+", " ".join(shlex.quote(str(item)) for item in command))
    sys.stdout.flush()

    subprocess.run([str(item) for item in command], cwd=str(cwd), env=env, check=True)


def parse_b_values(text):
    values = []

    for item in text.replace(",", " ").split():
        try:
            value = int(item)
        except ValueError:
            raise SystemExit(f"invalid B value: {item}")

        if value <= 0:
            raise SystemExit("B values must be positive")

        if value in values:
            raise SystemExit(f"duplicate B value: {value}")

        values.append(value)

    if not values:
        raise SystemExit("at least one B value is required")

    return values


def make_variables(args, b_value):
    return [
        f"ARCH={args.arch}",
        f"W={args.w}",
        f"H={args.h}",
        f"B={b_value}",
        f"SX={args.sx}",
        f"SY={args.sy}",
        f"WAIT_ALPHA={args.wait_alpha}",
        f"INPUT_MODE={args.input_mode}",
        f"INPUT_SEED={args.input_seed}",
        "CONTAINER_BIN=",
    ]


def build_benchmark(args, benchmark_name, b_value):
    benchmark = BENCHMARKS[benchmark_name]

    if args.skip_build:
        print(f"Skipping build for {benchmark['label']}, B={b_value}")

        for filename in (benchmark["map"], benchmark["image"]):
            path = benchmark["directory"] / filename
            if not path.is_file():
                raise SystemExit(f"--skip-build was used, but {path} does not exist")

        return

    command = ["make", "build-run", *make_variables(args, b_value)]
    run_command(command, benchmark["directory"])


def queue_hardware(args, job, benchmark_name, b_value):
    benchmark = BENCHMARKS[benchmark_name]

    command = [
        "make", "wse-queue",
        *make_variables(args, b_value),
        f"WSE_JOB={job}",
        f"WSE_SERVER={args.server}",
        f"WSE_LIFETIME={args.lifetime}",
        f"WSE_WIDTH={args.w}",
        f"WSE_HEIGHT={args.h}",
    ]

    if args.wafer:
        command.append(f"WSE_WAFER={args.wafer}")

    run_command(command, benchmark["directory"])


def parse_results(path, benchmark_name, b_value):
    rows = []

    with path.open(newline="") as file:
        reader = csv.DictReader(file)

        for index, source in enumerate(reader, start=1):
            if not source:
                continue

            value = source.get(METRIC)
            if value in (None, ""):
                raise SystemExit(f"{path}: missing column {METRIC}")

            rows.append({
                "benchmark": benchmark_name,
                "b": b_value,
                "trial": int(source.get("trial") or index),
                "cycles": int(float(value)),
            })

    if not rows:
        raise SystemExit(f"No timing rows found in {path}")

    return rows


def run_trials(args, benchmark_name, b_value, job, output_root):
    benchmark = BENCHMARKS[benchmark_name]

    timing_output = (output_root / benchmark_name / f"B_{b_value}" / "hardware_runs").resolve()

    environment = os.environ.copy()
    environment.update({
        "JOB": job,
        "WSE_SERVER": args.server,
        "MAP": benchmark["map"],
        "IMAGE": benchmark["image"],
        "W": str(args.w),
        "H": str(args.h),
        "B": str(b_value),
        "SX": str(args.sx),
        "SY": str(args.sy),
        "RUNS": str(args.runs),
        "CLOCK_MHZ": str(args.clock_mhz),
        "OUT": str(timing_output),
    })

    run_command(["bash", "run_5_timings.sh"], benchmark["directory"], env=environment)

    results_path = timing_output / "results.csv"
    if not results_path.is_file():
        raise SystemExit(f"Timing script did not create {results_path}")

    rows = parse_results(results_path, benchmark_name, b_value)

    if len(rows) != args.runs:
        raise SystemExit(f"{results_path}: expected {args.runs} runs, found {len(rows)}")

    return rows


def metric_statistics(rows, benchmark_name, b_value):
    values = [
        row["cycles"] for row in rows
        if row["benchmark"] == benchmark_name and row["b"] == b_value
    ]

    if not values:
        raise SystemExit(f"No values for {benchmark_name}, B={b_value}")

    return {
        "runs": len(values),
        "mean": statistics.mean(values),
        "stddev": statistics.pstdev(values) if len(values) > 1 else 0.0,
        "minimum": min(values),
        "maximum": max(values),
    }


def write_reports(args, rows, b_values, output_root):
    all_runs_path = output_root / "all_runs.csv"

    with all_runs_path.open("w", newline="") as file:
        writer = csv.DictWriter(
            file, fieldnames=["benchmark", "label", "B", "trial", "cycles", "microseconds"]
        )
        writer.writeheader()

        for row in rows:
            writer.writerow({
                "benchmark": row["benchmark"],
                "label": BENCHMARKS[row["benchmark"]]["label"],
                "B": row["b"],
                "trial": row["trial"],
                "cycles": row["cycles"],
                "microseconds": row["cycles"] / args.clock_mhz,
            })

    summary = {}
    for benchmark_name in BENCHMARKS:
        for b_value in b_values:
            summary[(benchmark_name, b_value)] = metric_statistics(rows, benchmark_name, b_value)

    summary_path = output_root / "summary.csv"
    with summary_path.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([
            "benchmark", "label", "B", "runs",
            "mean_cycles", "stddev_cycles", "min_cycles", "max_cycles", "mean_microseconds",
        ])

        for benchmark_name, benchmark in BENCHMARKS.items():
            for b_value in b_values:
                values = summary[(benchmark_name, b_value)]
                writer.writerow([
                    benchmark_name, benchmark["label"], b_value, values["runs"],
                    f"{values['mean']:.6f}", f"{values['stddev']:.6f}",
                    values["minimum"], values["maximum"],
                    f"{values['mean'] / args.clock_mhz:.9f}",
                ])

    return summary, all_runs_path, summary_path


def plot_results(args, b_values, summary, output_root):
    if plt is None:
        print("matplotlib is unavailable, skipping PNG and PDF plots.")
        return ()

    colors = {"chain": "#4472C4", "two_phase": "#ED7D31"}

    figure, axis = plt.subplots(figsize=(8, 6))
    x_positions = list(range(len(b_values)))

    for benchmark_name, benchmark in BENCHMARKS.items():
        means = [summary[(benchmark_name, b)]["mean"] / args.clock_mhz for b in b_values]
        errors = [summary[(benchmark_name, b)]["stddev"] / args.clock_mhz for b in b_values]

        axis.errorbar(
            x_positions, means, yerr=errors,
            marker="o", linewidth=2, capsize=4,
            color=colors[benchmark_name], label=benchmark["label"],
        )

    axis.set_xticks(x_positions)
    axis.set_xticklabels([str(value) for value in b_values])
    axis.set_xlabel("B, partial answer per PE")
    axis.set_ylabel("Mean latency, microseconds")
    axis.set_title(f"AllReduce, W={args.w}, H={args.h}")
    axis.grid(alpha=0.3)
    axis.legend()

    figure.tight_layout()

    png_path = output_root / "allreduce_comparison.png"
    pdf_path = output_root / "allreduce_comparison.pdf"
    figure.savefig(png_path, dpi=180)
    figure.savefig(pdf_path)
    plt.close(figure)

    return png_path, pdf_path


def parse_arguments():
    parser = argparse.ArgumentParser(description="Sweep B for the plain chain/xy-two-phase AllReduce benchmarks.")
    parser.add_argument("--w", type=int, default=512)
    parser.add_argument("--h", type=int, default=512)
    parser.add_argument("--b-values", default="1,4,16,64,256,1024")
    parser.add_argument("--sx", type=int, default=23)
    parser.add_argument("--sy", type=int, default=23)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--wait-alpha", type=int, default=1)
    parser.add_argument("--arch", default="sdr")
    parser.add_argument("--input-mode", default="pattern")
    parser.add_argument("--input-seed", type=int, default=1)
    parser.add_argument("--clock-mhz", type=float, default=850)
    parser.add_argument("--server", default="http://localhost:8080")
    parser.add_argument("--wafer")
    parser.add_argument("--lifetime", type=int, default=40000)
    parser.add_argument("--job")
    parser.add_argument("--results-dir")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-queue", action="store_true")
    return parser.parse_args()


def main():
    args = parse_arguments()
    b_values = parse_b_values(args.b_values)

    if args.w < 2 or args.h < 2:
        raise SystemExit("W and H must be at least 2")
    if args.runs <= 0:
        raise SystemExit("runs must be positive")
    if args.skip_queue and not args.job:
        raise SystemExit("--skip-queue requires --job with an active job name")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    job = args.job or f"allreduce-compare-{timestamp}"

    output_root = Path(args.results_dir) if args.results_dir else ROOT / f"allreduce_comparison_{timestamp}"
    if not output_root.is_absolute():
        output_root = ROOT / output_root
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    configuration = {
        "job": job, "W": args.w, "H": args.h, "B_values": b_values,
        "SX": args.sx, "SY": args.sy, "runs": args.runs,
        "clock_mhz": args.clock_mhz, "server": args.server, "lifetime": args.lifetime,
    }
    (output_root / "configuration.json").write_text(json.dumps(configuration, indent=2) + "\n")
    print("AllReduce comparison configuration")
    print(json.dumps(configuration, indent=2))
    print(f"Output directory: {output_root}")

    rows = []
    queue_created = args.skip_queue

    if args.skip_queue:
        print(f"Using existing hardware job: {job}")

    for b_value in b_values:
        print()
        print("=" * 72)
        print(f"B={b_value}")
        print("=" * 72)

        for benchmark_name, benchmark in BENCHMARKS.items():
            print()
            print(f"Running {benchmark['label']} with B={b_value}")

            build_benchmark(args, benchmark_name, b_value)

            if not queue_created:
                queue_hardware(args, job, benchmark_name, b_value)
                queue_created = True

            rows.extend(run_trials(args, benchmark_name, b_value, job, output_root))

    summary, all_runs_path, summary_path = write_reports(args, rows, b_values, output_root)
    plot_paths = plot_results(args, b_values, summary, output_root)

    print()
    print("Created:")
    print(f"  {output_root / 'configuration.json'}")
    print(f"  {all_runs_path}")
    print(f"  {summary_path}")
    for path in plot_paths:
        print(f"  {path}")


if __name__ == "__main__":
    main()
