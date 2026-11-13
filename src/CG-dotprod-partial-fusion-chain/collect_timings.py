#!/usr/bin/env python3

import argparse
import csv
from pathlib import Path

import numpy as np

WORDS_PER_PE = 15
COUNTER_BITS = 48
COUNTER_MOD = 1 << COUNTER_BITS
COUNTER_MASK = COUNTER_MOD - 1


def load_words(path, expected, label):
    data = np.fromfile(path, dtype="<u2")

    if data.size != expected:
        raise SystemExit(
            f"{label}: expected {expected} uint16 words, "
            f"found {data.size}"
        )

    return data


def snapshot(words, offset):
    return (
        words[..., offset].astype(np.uint64)
        | (words[..., offset + 1].astype(np.uint64) << 16)
        | (words[..., offset + 2].astype(np.uint64) << 32)
    )


def elapsed(start, stop, direction):
    if direction == "down":
        return (
            start + np.uint64(COUNTER_MOD) - stop
        ) & np.uint64(COUNTER_MASK)

    return (
        stop + np.uint64(COUNTER_MOD) - start
    ) & np.uint64(COUNTER_MASK)


def choose_direction(
    reference,
    start,
    fused_x1_stop,
    reduction_stop,
    final_stop,
):
    scores = {}

    for direction in ("down", "up"):
        intervals = [
            elapsed(reference, start, direction),
            elapsed(start, fused_x1_stop, direction),
            elapsed(fused_x1_stop, reduction_stop, direction),
            elapsed(reduction_stop, final_stop, direction),
        ]

        scores[direction] = max(
            int(value.max()) for value in intervals
        )

    return min(scores, key=scores.get)


def extremum(values, mode):
    if mode == "min":
        flat = int(np.argmin(values))
    else:
        flat = int(np.argmax(values))

    y, x = np.unravel_index(flat, values.shape)
    return int(values[y, x]), int(x), int(y)


def checked_delta(stop, start, label):
    result = int(stop) - int(start)

    if result < 0:
        raise SystemExit(
            f"{label}: negative aligned duration "
            f"({stop} - {start})"
        )

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--w", type=int, required=True)
    parser.add_argument("--h", type=int, required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--top", required=True)
    parser.add_argument("--lower", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--per-pe", required=True)
    parser.add_argument("--extrema")
    parser.add_argument("--clock-mhz", type=float, default=850.0)
    parser.add_argument("--wait-alpha", type=int, default=0)
    parser.add_argument(
        "--counter-direction",
        choices=["auto", "down", "up"],
        default="auto",
    )
    args = parser.parse_args()

    if args.wait_alpha < 0:
        raise SystemExit("WAIT_ALPHA must be nonnegative")

    if args.clock_mhz <= 0:
        raise SystemExit("Clock frequency must be positive")

    W, H = args.w, args.h

    words = np.zeros(
        (H, W, WORDS_PER_PE),
        dtype=np.uint16,
    )

    words[0, 0] = load_words(
        args.root,
        WORDS_PER_PE,
        "root timestamps",
    )

    words[0, 1:] = load_words(
        args.top,
        (W - 1) * WORDS_PER_PE,
        "top timestamps",
    ).reshape(W - 1, WORDS_PER_PE)

    words[1:] = load_words(
        args.lower,
        (H - 1) * W * WORDS_PER_PE,
        "lower timestamps",
    ).reshape(H - 1, W, WORDS_PER_PE)

    reference = snapshot(words, 0)
    start = snapshot(words, 3)
    fused_x1_stop = snapshot(words, 6)
    reduction_stop = snapshot(words, 9)
    final_stop = snapshot(words, 12)

    direction = args.counter_direction

    if direction == "auto":
        direction = choose_direction(
            reference,
            start,
            fused_x1_stop,
            reduction_stop,
            final_stop,
        )

    reference_to_start = elapsed(
        reference, start, direction
    )
    local_compute_x1_fused = elapsed(
        start, fused_x1_stop, direction
    )
    local_remaining_reduction = elapsed(
        fused_x1_stop, reduction_stop, direction
    )
    local_post_reduction = elapsed(
        reduction_stop, final_stop, direction
    )
    local_remaining_collective = elapsed(
        fused_x1_stop, final_stop, direction
    )
    local_total = elapsed(
        start, final_stop, direction
    )

    if int(local_total.max()) >= COUNTER_MOD // 4:
        raise SystemExit(
            "Implausibly large duration. Try the other "
            "counter direction."
        )

    yy, xx = np.indices((H, W), dtype=np.int64)

    propagation = (xx + yy + 2).astype(np.uint64)

    aligned_start = reference_to_start + propagation
    aligned_fused_x1_stop = (
        elapsed(reference, fused_x1_stop, direction)
        + propagation
    )
    aligned_reduction_stop = (
        elapsed(reference, reduction_stop, direction)
        + propagation
    )
    aligned_final_stop = (
        elapsed(reference, final_stop, direction)
        + propagation
    )

    # this exactly matches the kernel calculation:
    # floor((WAIT_ALPHA * distance + 4) / 9)
    wait_distance = W + H - xx - yy
    wait_iterations = (
        args.wait_alpha * wait_distance + 4
    ) // 9

    start_min = extremum(aligned_start, "min")
    start_max = extremum(aligned_start, "max")
    fused_x1_min = extremum(aligned_fused_x1_stop, "min")
    fused_x1_max = extremum(aligned_fused_x1_stop, "max")
    reduction_max = extremum(
        aligned_reduction_stop, "max"
    )
    final_max = extremum(aligned_final_stop, "max")

    local_fused_x1_max = extremum(local_compute_x1_fused, "max")
    local_remaining_reduction_max = extremum(
        local_remaining_reduction, "max"
    )
    local_post_reduction_max = extremum(
        local_post_reduction, "max"
    )
    local_remaining_collective_max = extremum(
        local_remaining_collective, "max"
    )

    root_remaining_reduction_stop = int(
        aligned_reduction_stop[0, 0]
    )

    def location(item):
        return item[1], item[2]

    def metric(name, cycles, start_location, stop_location):
        return (
            name,
            int(cycles),
            start_location[0],
            start_location[1],
            stop_location[0],
            stop_location[1],
        )

    metrics = [
        metric(
            "start_spread",
            checked_delta(
                start_max[0],
                start_min[0],
                "start spread",
            ),
            location(start_min),
            location(start_max),
        ),
        metric(
            "compute_x1_fused",
            checked_delta(
                fused_x1_max[0],
                start_min[0],
                "compute plus horizontal phase 1",
            ),
            location(start_min),
            location(fused_x1_max),
        ),
        metric(
            "root_remaining_reduction",
            checked_delta(
                root_remaining_reduction_stop,
                fused_x1_min[0],
                "root reduction",
            ),
            location(fused_x1_min),
            (0, 0),
        ),
        metric(
            "all_pe_remaining_reduction_return",
            checked_delta(
                reduction_max[0],
                fused_x1_min[0],
                "all-PE remaining reduction return",
            ),
            location(fused_x1_min),
            location(reduction_max),
        ),
        metric(
            "broadcast_from_root",
            checked_delta(
                final_max[0],
                root_remaining_reduction_stop,
                "broadcast from root",
            ),
            (0, 0),
            location(final_max),
        ),
        metric(
            "remaining_collective",
            checked_delta(
                final_max[0],
                fused_x1_min[0],
                "remaining collective",
            ),
            location(fused_x1_min),
            location(final_max),
        ),
        metric(
            "dotprod_total",
            checked_delta(
                final_max[0],
                start_min[0],
                "Dot product total",
            ),
            location(start_min),
            location(final_max),
        ),
        metric(
            "max_local_compute_x1_fused",
            local_fused_x1_max[0],
            location(local_fused_x1_max),
            location(local_fused_x1_max),
        ),
        metric(
            "max_local_remaining_reduction",
            local_remaining_reduction_max[0],
            location(local_remaining_reduction_max),
            location(local_remaining_reduction_max),
        ),
        metric(
            "max_local_post_reduction",
            local_post_reduction_max[0],
            location(local_post_reduction_max),
            location(local_post_reduction_max),
        ),
        metric(
            "max_local_remaining_collective",
            local_remaining_collective_max[0],
            location(local_remaining_collective_max),
            location(local_remaining_collective_max),
        ),
        metric(
            "root_local_remaining_reduction",
            int(local_remaining_reduction[0, 0]),
            (0, 0),
            (0, 0),
        ),
    ]

    extrema = [
        (
            "earliest_aligned_start",
            "min",
            *start_min,
        ),
        (
            "latest_aligned_start",
            "max",
            *start_max,
        ),
        (
            "earliest_aligned_fused_x1_end",
            "min",
            *fused_x1_min,
        ),
        (
            "latest_aligned_fused_x1_end",
            "max",
            *fused_x1_max,
        ),
        (
            "latest_aligned_reduction_end",
            "max",
            *reduction_max,
        ),
        (
            "latest_aligned_remaining_collective_end",
            "max",
            *final_max,
        ),
        (
            "maximum_local_compute_x1_fused_duration",
            "max",
            *local_fused_x1_max,
        ),
        (
            "maximum_local_remaining_reduction_duration",
            "max",
            *local_remaining_reduction_max,
        ),
        (
            "maximum_local_post_reduction_duration",
            "max",
            *local_post_reduction_max,
        ),
        (
            "maximum_local_remaining_collective_duration",
            "max",
            *local_remaining_collective_max,
        ),
    ]

    summary_path = Path(args.summary)
    per_pe_path = Path(args.per_pe)

    if args.extrema:
        extrema_path = Path(args.extrema)
    else:
        extrema_path = summary_path.with_name(
            summary_path.stem + "-extrema.csv"
        )

    for path in (
        summary_path,
        per_pe_path,
        extrema_path,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)

    with summary_path.open("w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow([
            "metric",
            "cycles",
            "microseconds",
            "counter_direction",
            "start_x",
            "start_y",
            "stop_x",
            "stop_y",
        ])

        for (
            name,
            cycles,
            start_x,
            start_y,
            stop_x,
            stop_y,
        ) in metrics:
            writer.writerow([
                name,
                cycles,
                f"{cycles / args.clock_mhz:.9f}",
                direction,
                start_x,
                start_y,
                stop_x,
                stop_y,
            ])

    with extrema_path.open("w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow([
            "event",
            "extremum",
            "cycles",
            "microseconds",
            "x",
            "y",
        ])

        for name, mode, cycles, x, y in extrema:
            writer.writerow([
                name,
                mode,
                cycles,
                f"{cycles / args.clock_mhz:.9f}",
                x,
                y,
            ])

    with per_pe_path.open("w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow([
            "x",
            "y",
            "reference_counter",
            "dotprod_start_counter",
            "fused_x1_stop_counter",
            "reduction_stop_counter",
            "final_stop_counter",
            "wait_distance",
            "wait_iterations",
            "reference_to_start",
            "aligned_start",
            "aligned_fused_x1_stop",
            "aligned_reduction_stop",
            "aligned_final_stop",
            "local_compute_x1_fused_cycles",
            "local_remaining_reduction_cycles",
            "local_post_reduction_cycles",
            "local_remaining_collective_cycles",
            "local_total_cycles",
        ])

        for y in range(H):
            for x in range(W):
                writer.writerow([
                    x,
                    y,
                    int(reference[y, x]),
                    int(start[y, x]),
                    int(fused_x1_stop[y, x]),
                    int(reduction_stop[y, x]),
                    int(final_stop[y, x]),
                    int(wait_distance[y, x]),
                    int(wait_iterations[y, x]),
                    int(reference_to_start[y, x]),
                    int(aligned_start[y, x]),
                    int(aligned_fused_x1_stop[y, x]),
                    int(aligned_reduction_stop[y, x]),
                    int(aligned_final_stop[y, x]),
                    int(local_compute_x1_fused[y, x]),
                    int(local_remaining_reduction[y, x]),
                    int(local_post_reduction[y, x]),
                    int(local_remaining_collective[y, x]),
                    int(local_total[y, x]),
                ])

    print(f"Counter direction: {direction}")
    print(
        f"{'metric':28s} {'cycles':>12s} "
        f"{'microseconds':>14s} {'start':>12s} {'stop':>12s}"
    )

    for (
        name,
        cycles,
        start_x,
        start_y,
        stop_x,
        stop_y,
    ) in metrics:
        print(
            f"{name:28s} "
            f"{cycles:12d} "
            f"{cycles / args.clock_mhz:14.6f} "
            f"({start_x},{start_y}) "
            f"({stop_x},{stop_y})"
        )

    if args.wait_alpha > 0 and W * H > 2:
        mask = np.ones((H, W), dtype=bool)
        mask[0, 0] = False

        iterations = wait_iterations[mask].astype(
            np.float64
        )
        delays = reference_to_start[mask].astype(
            np.float64
        )

        centered = iterations - iterations.mean()
        denominator = np.dot(centered, centered)

        if denominator > 0:
            cycles_per_iteration = np.dot(
                centered,
                delays - delays.mean(),
            ) / denominator

            print(
                "Estimated wait-loop cost: "
                f"{cycles_per_iteration:.6f} "
                "cycles per executed iteration"
            )

    print(f"Wrote {summary_path}")
    print(f"Wrote {extrema_path}")
    print(f"Wrote {per_pe_path}")


if __name__ == "__main__":
    main()
