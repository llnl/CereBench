#!/usr/bin/env python3

import argparse
import csv
from pathlib import Path

import numpy as np

from collect_timings import (
    COUNTER_MOD,
    choose_direction,
    elapsed,
    load_words,
    snapshot,
)

PHASE_WORDS = 15
STAGE_WORDS = 12


def load_grid(root_path, top_path, lower_path, w, h, words_per_pe):
    words = np.zeros(
        (h, w, words_per_pe),
        dtype=np.uint16,
    )

    words[0, 0] = load_words(
        root_path,
        words_per_pe,
        "root",
    )

    words[0, 1:] = load_words(
        top_path,
        (w - 1) * words_per_pe,
        "top",
    ).reshape(w - 1, words_per_pe)

    words[1:] = load_words(
        lower_path,
        (h - 1) * w * words_per_pe,
        "lower",
    ).reshape(h - 1, w, words_per_pe)

    return words


def coord(array, maximum=True, mask=None):
    if mask is not None:
        if maximum:
            selected = np.where(mask, array, 0)
        else:
            selected = np.where(
                mask,
                array,
                np.iinfo(np.uint64).max,
            )
    else:
        selected = array

    index = (
        np.argmax(selected)
        if maximum
        else np.argmin(selected)
    )

    y, x = np.unravel_index(index, array.shape)
    return int(x), int(y)


def leader_mask(coordinates, length, group_size):
    remainder = length % group_size

    if remainder:
        return (
            (coordinates == 0)
            | (
                (coordinates >= remainder)
                & ((coordinates - remainder) % group_size == 0)
            )
        )

    return coordinates % group_size == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--w", type=int, required=True)
    parser.add_argument("--h", type=int, required=True)
    parser.add_argument("--sx", type=int, required=True)
    parser.add_argument("--sy", type=int, required=True)

    parser.add_argument("--phase-root", required=True)
    parser.add_argument("--phase-top", required=True)
    parser.add_argument("--phase-lower", required=True)

    parser.add_argument("--stage-root", required=True)
    parser.add_argument("--stage-top", required=True)
    parser.add_argument("--stage-lower", required=True)

    parser.add_argument("--summary", required=True)
    parser.add_argument("--per-pe", required=True)
    parser.add_argument("--clock-mhz", type=float, default=850.0)
    parser.add_argument(
        "--counter-direction",
        choices=["auto", "up", "down"],
        default="auto",
    )
    args = parser.parse_args()

    w, h = args.w, args.h

    phase = load_grid(
        args.phase_root,
        args.phase_top,
        args.phase_lower,
        w,
        h,
        PHASE_WORDS,
    )

    stage = load_grid(
        args.stage_root,
        args.stage_top,
        args.stage_lower,
        w,
        h,
        STAGE_WORDS,
    )

    reference = snapshot(phase, 0)
    start = snapshot(phase, 3)
    gemv_stop = snapshot(phase, 6)
    reduction_stop = snapshot(phase, 9)
    final_stop = snapshot(phase, 12)

    x1_stop = snapshot(stage, 0)
    x2_stop = snapshot(stage, 3)
    y1_stop = snapshot(stage, 6)
    y2_stop = snapshot(stage, 9)

    if not np.any(stage):
        raise SystemExit(
            "All stage timestamps are zero. "
            "Rebuild with PROFILE_STAGES=1."
        )

    direction = args.counter_direction

    if direction == "auto":
        direction = choose_direction(
            reference,
            start,
            gemv_stop,
            reduction_stop,
            final_stop,
        )

    local_x1 = elapsed(gemv_stop, x1_stop, direction)
    local_x2 = elapsed(x1_stop, x2_stop, direction)
    local_y1 = elapsed(x2_stop, y1_stop, direction)
    local_y2 = elapsed(y1_stop, y2_stop, direction)

    for name, duration in (
        ("X phase 1", local_x1),
        ("X phase 2", local_x2),
        ("Y phase 1", local_y1),
        ("Y phase 2", local_y2),
    ):
        if int(duration.max()) >= COUNTER_MOD // 4:
            raise SystemExit(
                f"Implausible {name} duration; "
                "check counter direction."
            )

    yy, xx = np.indices((h, w), dtype=np.uint64)
    propagation = xx + yy + 2

    def aligned(event):
        return (
            elapsed(reference, event, direction)
            + propagation
        )

    aligned_gemv = aligned(gemv_stop)
    aligned_x1 = aligned(x1_stop)
    aligned_x2 = aligned(x2_stop)
    aligned_y1 = aligned(y1_stop)
    aligned_y2 = aligned(y2_stop)
    aligned_final = aligned(final_stop)

    x_leader = leader_mask(xx, w, args.sx)
    y_leader = leader_mask(yy, h, args.sy)

    row_roots = xx == 0
    vertical_leaders = row_roots & y_leader

    gemv_min = int(aligned_gemv.min())
    gemv_coord = coord(aligned_gemv, maximum=False)

    rows = []

    def add(name, cycles, start_coord, stop_coord):
        rows.append(
            (
                name,
                int(cycles),
                int(start_coord[0]),
                int(start_coord[1]),
                int(stop_coord[0]),
                int(stop_coord[1]),
            )
        )

    root = (0, 0)

    add(
        "root_x_phase1",
        local_x1[0, 0],
        root,
        root,
    )
    add(
        "root_x_phase2",
        local_x2[0, 0],
        root,
        root,
    )
    add(
        "root_y_phase1",
        local_y1[0, 0],
        root,
        root,
    )
    add(
        "root_y_phase2",
        local_y2[0, 0],
        root,
        root,
    )

    add(
        "root_four_stage_total",
        elapsed(gemv_stop[0, 0], y2_stop[0, 0], direction),
        root,
        root,
    )

    add(
        "root_profiled_reduction",
        elapsed(
            gemv_stop[0, 0],
            reduction_stop[0, 0],
            direction,
        ),
        root,
        root,
    )

    add(
        "stage_snapshot_tail",
        elapsed(
            y2_stop[0, 0],
            reduction_stop[0, 0],
            direction,
        ),
        root,
        root,
    )

    x1_coord = coord(aligned_x1)
    add(
        "all_pe_x1_frontier",
        int(aligned_x1.max()) - gemv_min,
        gemv_coord,
        x1_coord,
    )

    horizontal_coord = coord(
        aligned_x2,
        mask=row_roots,
    )
    horizontal_stop = int(
        aligned_x2[row_roots].max()
    )
    add(
        "all_rows_horizontal_frontier",
        horizontal_stop - gemv_min,
        gemv_coord,
        horizontal_coord,
    )

    vertical_coord = coord(
        aligned_y1,
        mask=vertical_leaders,
    )
    vertical_stop = int(
        aligned_y1[vertical_leaders].max()
    )
    add(
        "all_vertical_groups_frontier",
        vertical_stop - gemv_min,
        gemv_coord,
        vertical_coord,
    )

    add(
        "root_reduction_frontier",
        int(aligned_y2[0, 0]) - gemv_min,
        gemv_coord,
        root,
    )

    stage_min_coord = coord(aligned_y2, maximum=False)
    stage_max_coord = coord(aligned_y2)
    add(
        "all_pe_stage_exit_spread",
        int(aligned_y2.max() - aligned_y2.min()),
        stage_min_coord,
        stage_max_coord,
    )

    final_coord = coord(aligned_final)
    add(
        "profiled_broadcast_from_root",
        int(aligned_final.max())
        - int(aligned_y2[0, 0]),
        root,
        final_coord,
    )

    for name, values, mask in (
        ("max_local_x_phase1", local_x1, None),
        ("max_local_x_phase2", local_x2, x_leader),
        ("max_local_y_phase1", local_y1, row_roots),
        ("max_local_y_phase2", local_y2, vertical_leaders),
    ):
        location = coord(values, mask=mask)
        x, y = location
        add(name, values[y, x], location, location)

    summary = Path(args.summary)
    per_pe = Path(args.per_pe)
    summary.parent.mkdir(parents=True, exist_ok=True)
    per_pe.parent.mkdir(parents=True, exist_ok=True)

    with summary.open("w", newline="") as output:
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

        for name, cycles, sx, sy, tx, ty in rows:
            writer.writerow([
                name,
                cycles,
                f"{cycles / args.clock_mhz:.9f}",
                direction,
                sx,
                sy,
                tx,
                ty,
            ])

    with per_pe.open("w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow([
            "x",
            "y",
            "x_group_leader",
            "y_group_leader",
            "aligned_gemv_stop",
            "aligned_x1_stop",
            "aligned_x2_stop",
            "aligned_y1_stop",
            "aligned_y2_stop",
            "aligned_final_stop",
            "local_x1_cycles",
            "local_x2_cycles",
            "local_y1_cycles",
            "local_y2_cycles",
        ])

        for y in range(h):
            for x in range(w):
                writer.writerow([
                    x,
                    y,
                    int(x_leader[y, x]),
                    int(y_leader[y, x]),
                    int(aligned_gemv[y, x]),
                    int(aligned_x1[y, x]),
                    int(aligned_x2[y, x]),
                    int(aligned_y1[y, x]),
                    int(aligned_y2[y, x]),
                    int(aligned_final[y, x]),
                    int(local_x1[y, x]),
                    int(local_x2[y, x]),
                    int(local_y1[y, x]),
                    int(local_y2[y, x]),
                ])

    print(f"Counter direction: {direction}")
    print(f"{'metric':36s} {'cycles':>10s}")

    for name, cycles, *_ in rows:
        print(f"{name:36s} {cycles:10d}")

    print(f"Wrote {summary}")
    print(f"Wrote {per_pe}")


if __name__ == "__main__":
    main()
