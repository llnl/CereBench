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
    raise SystemExit(
        "matplotlib is required. Install it with:\n"
        "python3 -m pip install matplotlib"
    )


ROOT = Path(__file__).resolve().parent

BENCHMARKS = {
    "chain": {
        "label": "Chain",
        "directory": ROOT / "GEMV-chain-allreduce",
        "map": "chain-allreduce.map",
        "image": "chain-allreduce-run.img",
    },
    "two_phase": {
        "label": "Two-Phase",
        "directory": ROOT / "GEMV-xy2phase-allreduce",
        "map": "xy-two-phase-allreduce.map",
        "image": "xy-two-phase-allreduce-run.img",
    },
}

METRICS = ("start_spread", "local_gemv", "reduction", "global")

COLUMN_ALIASES = {
    "start_spread": (
        "spread_cycles",
        "start_spread",
        "start_spread",
    ),
    "local_gemv": (
        "local_gemv_cycles",
        "local_gemv",
    ),
    "reduction": (
        "reduction_cycles",
        "reduction",
    ),
    "global": (
        "global_cycles",
        "global",
    ),
}


def run_command(command, cwd, env=None):
    print()
    print(f"[{cwd}]")
    print("+", shlex.join(str(item) for item in command))
    sys.stdout.flush()

    subprocess.run(
        [str(item) for item in command],
        cwd=str(cwd),
        env=env,
        check=True,
    )


def make_variables(args, benchmark):
    variables = [
        f"W={args.w}",
        f"H={args.h}",
        f"M={args.m}",
        f"N={args.n}",
        f"WAIT_ALPHA={args.wait_alpha}",
        f"CLOCK_MHZ={args.clock_mhz}",
    ]

    if benchmark == "two_phase":
        variables.extend([
            f"SX={args.sx}",
            f"SY={args.sy}",
        ])

    return variables


def validate_sources():
    required = (
        "Makefile",
        "run_5_timings.sh",
        "collect_timings.py",
    )

    for benchmark in BENCHMARKS.values():
        directory = benchmark["directory"]

        if not directory.is_dir():
            raise SystemExit(
                f"Missing benchmark directory: {directory}"
            )

        for filename in required:
            path = directory / filename

            if not path.is_file():
                raise SystemExit(f"Missing file: {path}")


def build_benchmarks(args):
    if args.skip_build:
        print("Skipping benchmark builds.")

        for benchmark in BENCHMARKS.values():
            for filename in (
                benchmark["map"],
                benchmark["image"],
            ):
                path = benchmark["directory"] / filename

                if not path.is_file():
                    raise SystemExit(
                        f"--skip-build was used, but {path} "
                        "does not exist"
                    )

        return

    for name, benchmark in BENCHMARKS.items():
        command = [
            "make",
            "build-run",
            *make_variables(args, name),
        ]

        run_command(command, benchmark["directory"])


def queue_hardware(args, job):
    if args.skip_queue:
        print(f"Using existing hardware job: {job}")
        return

    benchmark = BENCHMARKS["chain"]

    command = [
        "make",
        "wse-queue",
        *make_variables(args, "chain"),
        f"WSE_JOB={job}",
        f"WSE_SERVER={args.server}",
        f"WSE_LIFETIME={args.lifetime}",
        f"WSE_WIDTH={args.w}",
        f"WSE_HEIGHT={args.h}",
    ]

    if args.wafer:
        command.append(f"WSE_WAFER={args.wafer}")

    run_command(command, benchmark["directory"])


def find_value(row, metric, path):
    for column in COLUMN_ALIASES[metric]:
        value = row.get(column)

        if value not in (None, ""):
            return int(float(value))

    expected = ", ".join(COLUMN_ALIASES[metric])

    raise SystemExit(
        f"{path}: timing results do not contain {metric}. "
        f"Expected one of: {expected}"
    )


def parse_results(path, benchmark_name):
    rows = []

    with path.open(newline="") as file:
        reader = csv.DictReader(file)

        for index, source in enumerate(reader, start=1):
            if not source:
                continue

            row = {
                "benchmark": benchmark_name,
                "trial": int(source.get("trial") or index),
            }

            for metric in METRICS:
                row[f"{metric}_cycles"] = find_value(
                    source, metric, path
                )

            rows.append(row)

    if not rows:
        raise SystemExit(f"No timing rows found in {path}")

    return rows


def run_trials(args, benchmark_name, job, output_root):
    benchmark = BENCHMARKS[benchmark_name]
    timing_output = (
        output_root / benchmark_name / "hardware_runs"
    ).resolve()

    environment = os.environ.copy()
    environment.update({
        "JOB": job,
        "WSE_SERVER": args.server,
        "MAP": benchmark["map"],
        "IMAGE": benchmark["image"],
        "W": str(args.w),
        "H": str(args.h),
        "RUNS": str(args.runs),
        "CLOCK_MHZ": str(args.clock_mhz),
        "FREQ": str(int(args.clock_mhz * 1_000_000)),
        "WAIT_ALPHA": str(args.wait_alpha),
        "TIMER_DIRECTION": args.timer_direction,
        "TRIGGER_HOP_CYCLES": str(
            args.trigger_hop_cycles
        ),
        "TRIGGER_BASE_CYCLES": str(
            args.trigger_base_cycles
        ),
        "OUT": str(timing_output),
    })

    run_command(
        ["bash", "run_5_timings.sh"],
        benchmark["directory"],
        env=environment,
    )

    results_path = timing_output / "results.csv"

    if not results_path.is_file():
        raise SystemExit(
            f"Timing script did not create {results_path}"
        )

    rows = parse_results(results_path, benchmark_name)

    if len(rows) != args.runs:
        raise SystemExit(
            f"{results_path}: expected {args.runs} runs, "
            f"found {len(rows)}"
        )

    return rows


def metric_statistics(rows, benchmark_name, metric):
    values = [
        row[f"{metric}_cycles"]
        for row in rows
        if row["benchmark"] == benchmark_name
    ]

    return {
        "runs": len(values),
        "mean": statistics.mean(values),
        "stddev": statistics.pstdev(values),
        "minimum": min(values),
        "maximum": max(values),
    }


def write_reports(args, rows, output_root):
    all_runs_path = output_root / "all_runs.csv"

    with all_runs_path.open("w", newline="") as file:
        fieldnames = [
            "benchmark",
            "trial",
            "spread_cycles",
            "local_gemv_cycles",
            "reduction_cycles",
            "global_cycles",
            "spread_us",
            "local_gemv_us",
            "reduction_us",
            "global_us",
        ]

        fieldnames = list(fieldnames)
        for name in ("start_spread_cycles", "start_spread_us"):
            if name not in fieldnames:
                fieldnames.append(name)
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            output = dict(row)

            for metric in METRICS:
                output[f"{metric}_us"] = (
                    row[f"{metric}_cycles"]
                    / args.clock_mhz
                )

            writer.writerow(output)

    summary = {}

    for benchmark_name in BENCHMARKS:
        for metric in METRICS:
            summary[(benchmark_name, metric)] = (
                metric_statistics(
                    rows, benchmark_name, metric
                )
            )

    summary_path = output_root / "summary.csv"

    with summary_path.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([
            "benchmark",
            "metric",
            "runs",
            "mean_cycles",
            "stddev_cycles",
            "min_cycles",
            "max_cycles",
            "mean_microseconds",
        ])

        for benchmark_name, benchmark in BENCHMARKS.items():
            for metric in METRICS:
                values = summary[
                    (benchmark_name, metric)
                ]

                writer.writerow([
                    benchmark["label"],
                    metric,
                    values["runs"],
                    f"{values['mean']:.6f}",
                    f"{values['stddev']:.6f}",
                    values["minimum"],
                    values["maximum"],
                    (
                        f"{values['mean'] / args.clock_mhz:.9f}"
                    ),
                ])

    comparison_path = output_root / "comparison.csv"

    with comparison_path.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([
            "metric",
            "chain_mean_cycles",
            "two_phase_mean_cycles",
            "chain_mean_microseconds",
            "two_phase_mean_microseconds",
            "chain_over_two_phase",
        ])

        for metric in METRICS:
            chain = summary[("chain", metric)]["mean"]
            two_phase = summary[
                ("two_phase", metric)
            ]["mean"]

            ratio = chain / two_phase if two_phase else 0.0

            writer.writerow([
                metric,
                f"{chain:.6f}",
                f"{two_phase:.6f}",
                f"{chain / args.clock_mhz:.9f}",
                f"{two_phase / args.clock_mhz:.9f}",
                f"{ratio:.6f}",
            ])

    return summary, all_runs_path, summary_path, comparison_path


def plot_results(args, rows, summary, output_root):
    colors = {
        "chain": "#4472C4",
        "two_phase": "#ED7D31",
    }

    figure, axes = plt.subplots(
        1, 3, figsize=(17, 5.5)
    )

    # mean phase latency
    bar_metrics = (
        "local_gemv",
        "reduction",
        "global",
    )
    bar_labels = (
        "Local GEMV",
        "Reduction",
        "Global",
    )

    x_positions = list(range(len(bar_metrics)))
    width = 0.36

    for index, benchmark_name in enumerate(BENCHMARKS):
        offset = -width / 2 if index == 0 else width / 2

        means = [
            summary[(benchmark_name, metric)]["mean"]
            / args.clock_mhz
            for metric in bar_metrics
        ]

        errors = [
            summary[(benchmark_name, metric)]["stddev"]
            / args.clock_mhz
            for metric in bar_metrics
        ]

        positions = [
            position + offset for position in x_positions
        ]

        axes[0].bar(
            positions,
            means,
            width,
            yerr=errors,
            capsize=4,
            color=colors[benchmark_name],
            label=BENCHMARKS[benchmark_name]["label"],
        )

    axes[0].set_xticks(x_positions)
    axes[0].set_xticklabels(bar_labels)
    axes[0].set_ylabel("Mean latency, microseconds")
    axes[0].set_title("Mean phase latency")
    axes[0].grid(axis="y", alpha=0.3)
    axes[0].legend()

    # global latency by trial
    for benchmark_name, benchmark in BENCHMARKS.items():
        selected = sorted(
            (
                row for row in rows
                if row["benchmark"] == benchmark_name
            ),
            key=lambda row: row["trial"],
        )

        axes[1].plot(
            [row["trial"] for row in selected],
            [
                row["global_cycles"] / args.clock_mhz
                for row in selected
            ],
            marker="o",
            linewidth=2,
            color=colors[benchmark_name],
            label=benchmark["label"],
        )

    axes[1].set_xlabel("Trial")
    axes[1].set_ylabel("Global latency, microseconds")
    axes[1].set_title("Global latency by trial")
    axes[1].grid(alpha=0.3)
    axes[1].legend()

    # start spread by trial
    for benchmark_name, benchmark in BENCHMARKS.items():
        selected = sorted(
            (
                row for row in rows
                if row["benchmark"] == benchmark_name
            ),
            key=lambda row: row["trial"],
        )

        axes[2].plot(
            [row["trial"] for row in selected],
            [row["start_spread_cycles"] for row in selected],
            marker="o",
            linewidth=2,
            color=colors[benchmark_name],
            label=benchmark["label"],
        )

    axes[2].set_xlabel("Trial")
    axes[2].set_ylabel("Start spread, cycles")
    axes[2].set_title("Synchronization spread")
    axes[2].grid(alpha=0.3)
    axes[2].legend()

    figure.suptitle(
        f"2D GEMV AllReduce, W={args.w}, H={args.h}, "
        f"M={args.m}, N={args.n}, SX=SY={args.sx}, "
        f"{args.clock_mhz:g} MHz"
    )

    figure.tight_layout(rect=(0, 0, 1, 0.94))

    png_path = output_root / "timing_comparison.png"
    pdf_path = output_root / "timing_comparison.pdf"

    figure.savefig(png_path, dpi=180)
    figure.savefig(pdf_path)
    plt.close(figure)

    return png_path, pdf_path


def print_comparison(args, summary):
    print()
    print("Comparison of mean cycle counts")
    print(
        f"{'Metric':16s} "
        f"{'Chain':>14s} "
        f"{'Two-Phase':>14s} "
        f"{'Chain/Two':>12s}"
    )

    for metric in METRICS:
        chain = summary[("chain", metric)]["mean"]
        two_phase = summary[
            ("two_phase", metric)
        ]["mean"]
        ratio = chain / two_phase if two_phase else 0

        print(
            f"{metric:16s} "
            f"{chain:14.3f} "
            f"{two_phase:14.3f} "
            f"{ratio:12.4f}"
        )

    chain_global = (
        summary[("chain", "global")]["mean"]
        / args.clock_mhz
    )
    two_phase_global = (
        summary[("two_phase", "global")]["mean"]
        / args.clock_mhz
    )

    print()
    print(
        f"Chain mean global time: "
        f"{chain_global:.6f} microseconds"
    )
    print(
        f"Two-Phase mean global time: "
        f"{two_phase_global:.6f} microseconds"
    )


def parse_arguments():
    parser = argparse.ArgumentParser(
        description=(
            "Run and compare the Chain and Two-Phase "
            "2D GEMV AllReduce benchmarks."
        )
    )

    parser.add_argument("--w", type=int, default=512)
    parser.add_argument("--h", type=int, default=512)
    parser.add_argument("--m", type=int, default=64)
    parser.add_argument("--n", type=int, default=262144)
    parser.add_argument("--sx", type=int, default=23)
    parser.add_argument("--sy", type=int, default=23)

    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument(
        "--clock-mhz", type=float, default=850.0
    )
    parser.add_argument("--wait-alpha", type=int, default=0)

    parser.add_argument(
        "--server",
        default=os.environ.get(
            "WSE_SERVER",
            "http://localhost:8080",
        ),
    )
    parser.add_argument(
        "--wafer",
        default=os.environ.get("WSE_WAFER"),
    )
    parser.add_argument("--lifetime", type=int, default=2000)

    parser.add_argument(
        "--timer-direction",
        choices=("auto", "up", "down"),
        default="auto",
    )
    parser.add_argument(
        "--trigger-hop-cycles",
        type=int,
        default=1,
    )
    parser.add_argument(
        "--trigger-base-cycles",
        type=int,
        default=2,
    )

    parser.add_argument("--job")
    parser.add_argument("--results-dir")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-queue", action="store_true")

    return parser.parse_args()


def main():
    args = parse_arguments()
    validate_sources()

    if min(
        args.w,
        args.h,
        args.m,
        args.n,
        args.sx,
        args.sy,
        args.runs,
    ) <= 0:
        raise SystemExit(
            "Dimensions, group sizes, and runs must be positive"
        )

    if args.sx > args.w or args.sy > args.h:
        raise SystemExit("SX and SY cannot exceed W and H")

    if args.skip_queue and not args.job:
        raise SystemExit(
            "--skip-queue requires --job with an active job name"
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    job = args.job or f"gemv-compare-{timestamp}"

    if args.results_dir:
        output_root = Path(args.results_dir)

        if not output_root.is_absolute():
            output_root = ROOT / output_root
    else:
        output_root = (
            ROOT / f"gemv_comparison_{timestamp}"
        )

    output_root.mkdir(parents=True, exist_ok=True)

    pe_count = args.w * args.h
    k = (args.n + pe_count - 1) // pe_count

    configuration = {
        "job": job,
        "W": args.w,
        "H": args.h,
        "M": args.m,
        "B": args.m,
        "N": args.n,
        "K": k,
        "PEs": pe_count,
        "SX": args.sx,
        "SY": args.sy,
        "runs": args.runs,
        "clock_mhz": args.clock_mhz,
        "wait_alpha": args.wait_alpha,
        "server": args.server,
        "wafer": args.wafer,
    }

    (output_root / "configuration.json").write_text(
        json.dumps(configuration, indent=2) + "\n"
    )

    print("GEMV comparison configuration")
    print(json.dumps(configuration, indent=2))
    print(f"Output directory: {output_root}")

    build_benchmarks(args)
    queue_hardware(args, job)

    rows = []

    for benchmark_name in ("chain", "two_phase"):
        rows.extend(
            run_trials(
                args,
                benchmark_name,
                job,
                output_root,
            )
        )

    summary, all_runs, summary_csv, comparison_csv = (
        write_reports(args, rows, output_root)
    )

    png_path, pdf_path = plot_results(
        args, rows, summary, output_root
    )

    print_comparison(args, summary)

    print()
    print("Created:")
    print(f"  {all_runs}")
    print(f"  {summary_csv}")
    print(f"  {comparison_csv}")
    print(f"  {png_path}")
    print(f"  {pdf_path}")


if __name__ == "__main__":
    main()
