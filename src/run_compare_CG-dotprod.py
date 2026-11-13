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
        "directory": ROOT / "CG-dotprod-chain",
        "map": "xy-two-phase-allreduce.map",
        "image": "xy-two-phase-allreduce-run.img",
    },
    "two_phase": {
        "label": "XY Two-Phase",
        "directory": ROOT / "CG-dotprod-xy2phase",
        "map": "xy-two-phase-allreduce.map",
        "image": "xy-two-phase-allreduce-run.img",
    },
    "partial_fusion_chain": {
        "label": "Partial-Fusion Chain",
        "directory": ROOT / "CG-dotprod-partial-fusion-chain",
        "map": "xy-two-phase-allreduce.map",
        "image": "xy-two-phase-allreduce-run.img",
    },
    "partial_fusion_two_phase": {
        "label": "Partial-Fusion XY Two-Phase",
        "directory": ROOT / "CG-dotprod-partial-fusion-xy2phase",
        "map": "xy-two-phase-allreduce.map",
        "image": "xy-two-phase-allreduce-run.img",
    },
}

METRICS = (
    "start_spread",
    "compute_x1_fused",
    "remaining_reduction",
    "total",
)


def run_command(command, cwd, env=None):
    print()
    print(f"[{cwd}]")
    print("+", " ".join(shlex.quote(str(item)) for item in command))
    sys.stdout.flush()

    subprocess.run(
        [str(item) for item in command],
        cwd=str(cwd),
        env=env,
        check=True,
    )


def parse_b_values(text):
    values = []

    for item in text.replace(",", " ").split():
        try:
            value = int(item)
        except ValueError:
            raise SystemExit(f"Invalid B value: {item}")

        if value <= 0:
            raise SystemExit("B values must be positive")

        if value in values:
            raise SystemExit(f"Duplicate B value: {value}")

        values.append(value)

    if not values:
        raise SystemExit("At least one B value is required")

    return values


def make_variables(args, b_value):
    n_value = args.w * args.h * args.k

    return [
        f"ARCH={args.arch}",
        f"W={args.w}",
        f"H={args.h}",
        f"M={b_value}",
        f"N={n_value}",
        f"B={b_value}",
        f"K={args.k}",
        f"SX={args.sx}",
        f"SY={args.sy}",
        f"WAIT_ALPHA={args.wait_alpha}",
        f"CLOCK_MHZ={args.clock_mhz}",
        f"INPUT_MODE={args.input_mode}",
        f"INPUT_SEED={args.input_seed}",
    ]


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


def build_benchmark(args, benchmark_name, b_value):
    benchmark = BENCHMARKS[benchmark_name]

    if args.skip_build:
        print(
            f"Skipping build for {benchmark['label']}, "
            f"B={b_value}"
        )

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

    command = [
        "make",
        "build-run",
        *make_variables(args, b_value),
    ]

    run_command(command, benchmark["directory"])


def queue_hardware(args, job, benchmark_name, b_value):
    benchmark = BENCHMARKS[benchmark_name]

    command = [
        "make",
        "wse-queue",
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

            row = {
                "benchmark": benchmark_name,
                "b": b_value,
                "trial": int(source.get("trial") or index),
            }

            for metric in METRICS:
                value = source.get(metric)

                if value in (None, ""):
                    raise SystemExit(
                        f"{path}: missing column {metric}"
                    )

                row[f"{metric}_cycles"] = int(float(value))

            rows.append(row)

    if not rows:
        raise SystemExit(f"No timing rows found in {path}")

    return rows


def run_trials(
    args,
    benchmark_name,
    b_value,
    job,
    output_root,
):
    benchmark = BENCHMARKS[benchmark_name]

    timing_output = (
        output_root
        / benchmark_name
        / f"B_{b_value}"
        / "hardware_runs"
    ).resolve()

    environment = os.environ.copy()
    environment.update({
        "JOB": job,
        "WSE_SERVER": args.server,
        "MAP": benchmark["map"],
        "IMAGE": benchmark["image"],
        "W": str(args.w),
        "H": str(args.h),
        "B": str(b_value),
        "M": str(b_value),
        "N": str(args.w * args.h * args.k),
        "K": str(args.k),
        "SX": str(args.sx),
        "SY": str(args.sy),
        "RUNS": str(args.runs),
        "CLOCK_MHZ": str(args.clock_mhz),
        "WAIT_ALPHA": str(args.wait_alpha),
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

    rows = parse_results(
        results_path,
        benchmark_name,
        b_value,
    )

    if len(rows) != args.runs:
        raise SystemExit(
            f"{results_path}: expected {args.runs} runs, "
            f"found {len(rows)}"
        )

    return rows


def metric_statistics(rows, benchmark_name, b_value, metric):
    values = [
        row[f"{metric}_cycles"]
        for row in rows
        if row["benchmark"] == benchmark_name
        and row["b"] == b_value
    ]

    if not values:
        raise SystemExit(
            f"No values for {benchmark_name}, "
            f"B={b_value}, metric={metric}"
        )

    return {
        "runs": len(values),
        "mean": statistics.mean(values),
        "stddev": statistics.pstdev(values),
        "minimum": min(values),
        "maximum": max(values),
    }


def write_reports(args, rows, b_values, output_root):
    n_value = args.w * args.h * args.k
    all_runs_path = output_root / "all_runs.csv"

    fieldnames = [
        "benchmark",
        "label",
        "B",
        "K",
        "N",
        "trial",
    ]

    for metric in METRICS:
        fieldnames.extend([
            f"{metric}_cycles",
            f"{metric}_microseconds",
        ])

    with all_runs_path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            output = {
                "benchmark": row["benchmark"],
                "label": BENCHMARKS[
                    row["benchmark"]
                ]["label"],
                "B": row["b"],
                "K": args.k,
                "N": n_value,
                "trial": row["trial"],
            }

            for metric in METRICS:
                cycles = row[f"{metric}_cycles"]
                output[f"{metric}_cycles"] = cycles
                output[f"{metric}_microseconds"] = (
                    cycles / args.clock_mhz
                )

            writer.writerow(output)

    summary = {}

    for benchmark_name in BENCHMARKS:
        for b_value in b_values:
            for metric in METRICS:
                summary[(benchmark_name, b_value, metric)] = (
                    metric_statistics(
                        rows,
                        benchmark_name,
                        b_value,
                        metric,
                    )
                )

    summary_path = output_root / "summary.csv"

    with summary_path.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([
            "benchmark",
            "label",
            "B",
            "K",
            "N",
            "metric",
            "runs",
            "mean_cycles",
            "stddev_cycles",
            "min_cycles",
            "max_cycles",
            "mean_microseconds",
        ])

        for benchmark_name, benchmark in BENCHMARKS.items():
            for b_value in b_values:
                for metric in METRICS:
                    values = summary[
                        (benchmark_name, b_value, metric)
                    ]

                    writer.writerow([
                        benchmark_name,
                        benchmark["label"],
                        b_value,
                        args.k,
                        n_value,
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

        header = ["B", "K", "N", "metric"]

        for benchmark_name in BENCHMARKS:
            header.extend([
                f"{benchmark_name}_mean_cycles",
                f"{benchmark_name}_mean_microseconds",
            ])

        header.extend([
            "chain_over_two_phase",
            "partial_chain_over_partial_two_phase",
            "chain_over_partial_chain",
            "two_phase_over_partial_two_phase",
        ])

        writer.writerow(header)

        for b_value in b_values:
            for metric in METRICS:
                means = {
                    benchmark_name: summary[
                        (benchmark_name, b_value, metric)
                    ]["mean"]
                    for benchmark_name in BENCHMARKS
                }

                row = [b_value, args.k, n_value, metric]

                for benchmark_name in BENCHMARKS:
                    value = means[benchmark_name]
                    row.extend([
                        f"{value:.6f}",
                        f"{value / args.clock_mhz:.9f}",
                    ])

                ratios = (
                    (
                        means["chain"]
                        / means["two_phase"]
                        if means["two_phase"]
                        else 0.0
                    ),
                    (
                        means["partial_fusion_chain"]
                        / means["partial_fusion_two_phase"]
                        if means["partial_fusion_two_phase"]
                        else 0.0
                    ),
                    (
                        means["chain"]
                        / means["partial_fusion_chain"]
                        if means["partial_fusion_chain"]
                        else 0.0
                    ),
                    (
                        means["two_phase"]
                        / means["partial_fusion_two_phase"]
                        if means["partial_fusion_two_phase"]
                        else 0.0
                    ),
                )

                row.extend(f"{value:.6f}" for value in ratios)
                writer.writerow(row)

    return (
        summary,
        all_runs_path,
        summary_path,
        comparison_path,
    )


def plot_results(args, b_values, summary, output_root):
    if plt is None:
        print(
            "matplotlib is unavailable, skipping PNG and PDF plots."
        )
        return ()

    colors = {
        "chain": "#4472C4",
        "two_phase": "#ED7D31",
        "partial_fusion_chain": "#70AD47",
        "partial_fusion_two_phase": "#A64D79",
    }

    titles = {
        "start_spread": "Synchronization spread",
        "compute_x1_fused": "Compute plus fused X phase",
        "remaining_reduction": "Remaining reduction",
        "total": "Total dot-product latency",
    }

    figure, axes = plt.subplots(
        2,
        2,
        figsize=(14, 10),
    )
    axes = axes.flatten()
    x_positions = list(range(len(b_values)))

    for axis, metric in zip(axes, METRICS):
        for benchmark_name, benchmark in BENCHMARKS.items():
            means = [
                summary[
                    (benchmark_name, b_value, metric)
                ]["mean"] / args.clock_mhz
                for b_value in b_values
            ]

            errors = [
                summary[
                    (benchmark_name, b_value, metric)
                ]["stddev"] / args.clock_mhz
                for b_value in b_values
            ]

            axis.errorbar(
                x_positions,
                means,
                yerr=errors,
                marker="o",
                linewidth=2,
                capsize=4,
                color=colors[benchmark_name],
                label=benchmark["label"],
            )

        axis.set_xticks(x_positions)
        axis.set_xticklabels(
            [str(value) for value in b_values]
        )
        axis.set_xlabel("B")
        axis.set_ylabel("Mean latency, microseconds")
        axis.set_title(titles[metric])
        axis.grid(alpha=0.3)

    axes[0].legend(fontsize=8)

    n_value = args.w * args.h * args.k

    figure.suptitle(
        f"CG Dot Product Comparison, "
        f"W={args.w}, H={args.h}, "
        f"K={args.k}, N={n_value}"
    )
    figure.tight_layout(rect=(0, 0, 1, 0.96))

    png_path = output_root / "cg_dotprod_comparison.png"
    pdf_path = output_root / "cg_dotprod_comparison.pdf"

    figure.savefig(png_path, dpi=180)
    figure.savefig(pdf_path)
    plt.close(figure)

    return png_path, pdf_path


def print_comparison(args, b_values, summary):
    print()
    print("Mean total latency, microseconds")

    labels = [
        BENCHMARKS[name]["label"]
        for name in BENCHMARKS
    ]

    print(
        f"{'B':>8s} "
        + " ".join(f"{label:>28s}" for label in labels)
    )

    for b_value in b_values:
        values = []

        for benchmark_name in BENCHMARKS:
            mean = summary[
                (benchmark_name, b_value, "total")
            ]["mean"]
            values.append(mean / args.clock_mhz)

        print(
            f"{b_value:8d} "
            + " ".join(
                f"{value:28.6f}" for value in values
            )
        )


def parse_arguments():
    parser = argparse.ArgumentParser(
        description=(
            "Build, run, and compare the four CG dot-product "
            "implementations."
        )
    )

    parser.add_argument("--w", type=int, default=512)
    parser.add_argument("--h", type=int, default=512)
    parser.add_argument("--k", type=int, default=1)
    parser.add_argument(
        "--b-values",
        default="1,4,16,64,256,1024",
    )
    parser.add_argument("--sx", type=int, default=23)
    parser.add_argument("--sy", type=int, default=23)
    parser.add_argument("--runs", type=int, default=5)

    parser.add_argument(
        "--clock-mhz",
        type=float,
        default=850.0,
    )
    parser.add_argument("--wait-alpha", type=int, default=1)
    parser.add_argument("--arch", default="sdr")
    parser.add_argument("--input-mode", default="pattern")
    parser.add_argument("--input-seed", type=int, default=1)

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
    parser.add_argument("--lifetime", type=int, default=40000)

    parser.add_argument("--job")
    parser.add_argument("--results-dir")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-queue", action="store_true")

    return parser.parse_args()


def main():
    args = parse_arguments()
    b_values = parse_b_values(args.b_values)

    validate_sources()

    if args.w < 2 or args.h < 2:
        raise SystemExit("W and H must be at least 2")

    if args.k <= 0 or args.runs <= 0:
        raise SystemExit("K and runs must be positive")

    if args.clock_mhz <= 0:
        raise SystemExit("Clock frequency must be positive")

    if args.wait_alpha < 0:
        raise SystemExit("WAIT_ALPHA must be nonnegative")

    if args.sx <= 0 or args.sx > args.w:
        raise SystemExit("SX must be between 1 and W")

    if args.sy <= 0 or args.sy > args.h:
        raise SystemExit("SY must be between 1 and H")

    if args.lifetime <= 0:
        raise SystemExit("Lifetime must be positive")

    if args.skip_queue and not args.job:
        raise SystemExit(
            "--skip-queue requires --job with an active job name"
        )

    if args.skip_build and len(b_values) != 1:
        raise SystemExit(
            "--skip-build requires exactly one B value because "
            "each benchmark directory contains one built image"
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    job = args.job or f"cg-dotprod-compare-{timestamp}"

    if args.results_dir:
        output_root = Path(args.results_dir)

        if not output_root.is_absolute():
            output_root = ROOT / output_root
    else:
        output_root = (
            ROOT / f"cg_dotprod_comparison_{timestamp}"
        )

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    n_value = args.w * args.h * args.k

    configuration = {
        "job": job,
        "W": args.w,
        "H": args.h,
        "K": args.k,
        "N": n_value,
        "B_values": b_values,
        "SX": args.sx,
        "SY": args.sy,
        "runs": args.runs,
        "clock_mhz": args.clock_mhz,
        "wait_alpha": args.wait_alpha,
        "server": args.server,
        "wafer": args.wafer,
        "lifetime": args.lifetime,
        "benchmarks": {
            name: benchmark["label"]
            for name, benchmark in BENCHMARKS.items()
        },
    }

    (output_root / "configuration.json").write_text(
        json.dumps(configuration, indent=2) + "\n"
    )

    print("CG dot-product comparison configuration")
    print(json.dumps(configuration, indent=2))
    print(f"Output directory: {output_root}")

    rows = []
    queue_created = args.skip_queue

    if args.skip_queue:
        print(f"Using existing hardware job: {job}")

    for b_value in b_values:
        print()
        print("=" * 72)
        print(f"B={b_value}, K={args.k}, N={n_value}")
        print("=" * 72)

        for benchmark_name, benchmark in BENCHMARKS.items():
            print()
            print(
                f"Running {benchmark['label']} with B={b_value}"
            )

            build_benchmark(
                args,
                benchmark_name,
                b_value,
            )

            if not queue_created:
                queue_hardware(
                    args,
                    job,
                    benchmark_name,
                    b_value,
                )
                queue_created = True

            rows.extend(
                run_trials(
                    args,
                    benchmark_name,
                    b_value,
                    job,
                    output_root,
                )
            )

    (
        summary,
        all_runs_path,
        summary_path,
        comparison_path,
    ) = write_reports(
        args,
        rows,
        b_values,
        output_root,
    )

    plot_paths = plot_results(
        args,
        b_values,
        summary,
        output_root,
    )

    print_comparison(args, b_values, summary)

    print()
    print("Created:")
    print(f"  {output_root / 'configuration.json'}")
    print(f"  {all_runs_path}")
    print(f"  {summary_path}")
    print(f"  {comparison_path}")

    for path in plot_paths:
        print(f"  {path}")


if __name__ == "__main__":
    main()
