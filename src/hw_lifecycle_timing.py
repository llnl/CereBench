#!/usr/bin/env python3
"""end-to-end kingfisher hardware lifecycle timing harness

Times the real wall-clock cost of each phase of running one already-built
experiment on real wafer-scale hardware:

    allocate (queue a wafer reservation) -> wipe -> program -> run -> teardown

This is orchestration-overhead timing. It is a different measurement from
the on-chip, cycle-accurate `phase_timestamps` that collect_timings.py
already extracts from a completed run -- this harness answers "how long
did it take to get compute time on the machine at all," not "how many
cycles did the kernel take once it was running."

This has NOT been run against real kingfisher hardware -- there is no
CSRTSERV reachable from this machine to test against. The commands below
are the same csclient invocations the existing per-experiment Makefiles
use (wse-queue/wse-program/wse-exec), just timed individually and given
an explicit teardown step (`csclient bundle --cancel`), which none of the
Makefiles currently do. Sanity-check with --dry-run before pointing this
at a real server.

Usage:
  src/hw_lifecycle_timing.py --dry-run \\
      --dir build/CG-dotprod-chain --map xy-two-phase-allreduce.map \\
      --image xy-two-phase-allreduce-run.img --width 8 --height 8

  src/hw_lifecycle_timing.py \\
      --dir build/CG-dotprod-chain --map xy-two-phase-allreduce.map \\
      --image xy-two-phase-allreduce-run.img --width 8 --height 8 \\
      --server http://kingfisher-host:8080
"""

import argparse
import json
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CEREBRAS_ENV = REPO_ROOT / "cerebras-env"

WSE_SERVER_DEFAULT = "http://localhost:8080"

PHASES = ("allocate", "wipe", "program", "run", "teardown")


def write_bundle(path, wafer, width, height, lifetime, region):
    path.write_text(
        json.dumps(
            {
                "lifetime": lifetime,
                "regions": {
                    region: {
                        "wafer": wafer,
                        "width": width,
                        "height": height,
                        "padding": 0,
                    }
                },
            },
            indent=2,
        )
        + "\n"
    )


def run_in_cerebras_env(command, cwd):
    """Run one argv command inside the cerebras-env nix FHS shell (for
    csclient on PATH), with cwd set to the experiment's build directory."""

    inner = f"cd {shlex.quote(str(cwd))} && " + shlex.join(command)
    full_command = ["nix", "run", ".#", "--", "-c", inner]

    result = subprocess.run(
        full_command,
        cwd=str(CEREBRAS_ENV),
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout + result.stderr


def time_phase(name, command, cwd, dry_run):
    if dry_run:
        print(f"[{name}] {shlex.join(command)}")
        return {
            "phase": name,
            "command": shlex.join(command),
            "started_at": None,
            "duration_s": None,
            "returncode": None,
            "log": "(dry run, not executed)",
        }

    started_at = datetime.now()
    started = time.time()
    returncode, log = run_in_cerebras_env(command, cwd)
    duration = time.time() - started

    print(f"[{name}] {duration:.3f}s (exit {returncode})")

    return {
        "phase": name,
        "command": shlex.join(command),
        "started_at": started_at.isoformat(timespec="seconds"),
        "duration_s": round(duration, 3),
        "returncode": returncode,
        "log": log,
    }


def parse_arguments():
    parser = argparse.ArgumentParser(
        description=(
            "Time each phase of a real kingfisher hardware run: allocate, "
            "wipe, program, run, teardown."
        ),
    )
    parser.add_argument(
        "--dir",
        required=True,
        help="build directory containing the already-built map/image (e.g. build/CG-dotprod-chain)",
    )
    parser.add_argument("--map", required=True, help="map file, relative to --dir")
    parser.add_argument("--image", required=True, help="image file to program, relative to --dir")
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--wafer", default="xs20863")
    parser.add_argument("--region", default="main_compute")
    parser.add_argument("--lifetime", type=int, default=1000, help="bundle lifetime, seconds")
    parser.add_argument("--run-wait", type=int, default=30, help="seconds to wait for the run to finish")
    parser.add_argument("--server", default=WSE_SERVER_DEFAULT)
    parser.add_argument("--job", help="bundle name (default: auto-generated, timestamped)")
    parser.add_argument("--results-dir")
    parser.add_argument(
        "--skip-teardown",
        action="store_true",
        help="leave the wafer reservation active instead of cancelling it at the end",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the exact commands without executing them or requiring nix",
    )

    return parser.parse_args()


def main():
    args = parse_arguments()

    build_dir = Path(args.dir)
    if not build_dir.is_absolute():
        build_dir = REPO_ROOT / build_dir

    job = args.job or f"lifecycle-{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = (
        Path(args.results_dir)
        if args.results_dir
        else REPO_ROOT / "results" / f"hw_lifecycle_{timestamp}"
    )
    results_dir.mkdir(parents=True, exist_ok=True)

    print(f"Job: {job}")
    print(f"Server: {args.server}")
    print(f"Build dir: {build_dir}")
    print(f"Results: {results_dir}")
    print()

    if not args.dry_run:
        write_bundle(
            build_dir / "bundle.json",
            args.wafer,
            args.width,
            args.height,
            args.lifetime,
            args.region,
        )

    server_env = f"CSRTSERV={args.server}"

    phases = [
        (
            "allocate",
            ["env", server_env, "csclient", "bundle", "-bn", job, "--queue", "bundle.json"],
        ),
        (
            "wipe",
            ["env", server_env, "csclient", "job", "-bn", job, "-r", args.region, "wipe"],
        ),
        (
            "program",
            [
                "env",
                server_env,
                "csclient",
                "job",
                "-bn",
                job,
                "-r",
                args.region,
                f"program={args.image}",
            ],
        ),
        (
            "run",
            [
                "env",
                server_env,
                "csclient",
                "job",
                "-bn",
                job,
                "-r",
                args.region,
                "run",
                f"wait={args.run_wait}",
            ],
        ),
    ]

    if not args.skip_teardown:
        phases.append(
            (
                "teardown",
                ["env", server_env, "csclient", "bundle", "-bn", job, "--cancel"],
            )
        )

    records = []
    for name, command in phases:
        record = time_phase(name, command, build_dir, args.dry_run)
        records.append(record)

        if not args.dry_run and record["returncode"] != 0:
            print(f"[{name}] failed, stopping (teardown was NOT run if it hadn't run yet)")
            break

    total = sum(record["duration_s"] or 0 for record in records)

    summary = {
        "job": job,
        "server": args.server,
        "build_dir": str(build_dir),
        "width": args.width,
        "height": args.height,
        "dry_run": args.dry_run,
        "phases": records,
        "total_duration_s": round(total, 3) if not args.dry_run else None,
    }

    (results_dir / "lifecycle.json").write_text(json.dumps(summary, indent=2) + "\n")

    with (results_dir / "lifecycle.csv").open("w") as file:
        file.write("phase,started_at,duration_s,returncode\n")
        for record in records:
            file.write(
                f"{record['phase']},{record['started_at']},"
                f"{record['duration_s']},{record['returncode']}\n"
            )

    print()
    print(f"Total (excluding dry-run): {total:.3f}s" if not args.dry_run else "Dry run only.")
    print(f"Wrote {results_dir / 'lifecycle.json'}")
    print(f"Wrote {results_dir / 'lifecycle.csv'}")

    if not args.dry_run and any(record["returncode"] not in (0, None) for record in records):
        sys.exit(1)


if __name__ == "__main__":
    main()
