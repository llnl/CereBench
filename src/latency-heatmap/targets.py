import argparse
import numpy as np


def filter_valid_points(points, w, h, cx, cy, exclude_edge_columns=False):
    out = []
    for x, y in points:
        if not (0 <= x < w and 0 <= y < h):
            continue
        if x == cx and y == cy:
            continue
        if exclude_edge_columns and (x == 0 or x == w - 1):
            continue
        out.append((x, y))
    return out


def row_scan(w, h, cx, cy, exclude_edge_columns=False):
    pts = [(x, cy) for x in range(w)]
    return filter_valid_points(pts, w, h, cx, cy, exclude_edge_columns)


def column_scan(w, h, cx, cy, exclude_edge_columns=False):
    pts = [(cx, y) for y in range(h)]
    return filter_valid_points(pts, w, h, cx, cy, exclude_edge_columns)


def box_scan(w, h, x0, y0, dx, dy, exclude_edge_columns=False, cx=None, cy=None):
    pts = []
    y = y0
    while y < h:
        x = x0
        while x < w:
            pts.append((x, y))
            x += dx
        y += dy
    return filter_valid_points(pts, w, h, cx, cy, exclude_edge_columns)


def window_scan(w, h, x0, y0, ww, wh, cx, cy, exclude_edge_columns=False):
    pts = []
    for y in range(y0, min(y0 + wh, h)):
        for x in range(x0, min(x0 + ww, w)):
            pts.append((x, y))
    return filter_valid_points(pts, w, h, cx, cy, exclude_edge_columns)


def full_scan(w, h, cx, cy, exclude_edge_columns=False):
    x_start = 1 if exclude_edge_columns else 0
    x_stop = w - 1 if exclude_edge_columns else w
    pts = []
    for y in range(h):
        for x in range(x_start, x_stop):
            if x == cx and y == cy:
                continue
            pts.append((x, y))
    return pts


def expand_to_nprobe(points, nprobe):
    if nprobe is None:
        return points

    if nprobe < 0:
        raise RuntimeError(f"nprobe must be non-negative, got {nprobe}")

    if nprobe == 0:
        return []

    if len(points) == 0:
        raise RuntimeError("generated zero valid targets")

    if len(points) >= nprobe:
        return points[:nprobe]

    reps = (nprobe + len(points) - 1) // len(points)
    return (points * reps)[:nprobe]


def to_arrays(points):
    xs = np.array([p[0] for p in points], dtype=np.int16)
    ys = np.array([p[1] for p in points], dtype=np.int16)
    return xs, ys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["row", "column", "box", "window", "full"], required=True)
    ap.add_argument("--w", type=int, required=True)
    ap.add_argument("--h", type=int, required=True)
    ap.add_argument("--cx", type=int, required=True)
    ap.add_argument("--cy", type=int, required=True)
    ap.add_argument("--nprobe", type=int, default=None)
    ap.add_argument("--x0", type=int, default=0)
    ap.add_argument("--y0", type=int, default=0)
    ap.add_argument("--dx", type=int, default=1)
    ap.add_argument("--dy", type=int, default=1)
    ap.add_argument("--ww", type=int, default=32)
    ap.add_argument("--wh", type=int, default=32)
    ap.add_argument("--exclude-edge-columns", action="store_true")
    args = ap.parse_args()

    if args.mode == "row":
        pts = row_scan(args.w, args.h, args.cx, args.cy, args.exclude_edge_columns)
    elif args.mode == "column":
        pts = column_scan(args.w, args.h, args.cx, args.cy, args.exclude_edge_columns)
    elif args.mode == "box":
        pts = box_scan(
            args.w, args.h, args.x0, args.y0, args.dx, args.dy,
            args.exclude_edge_columns, args.cx, args.cy
        )
    elif args.mode == "window":
        pts = window_scan(
            args.w, args.h, args.x0, args.y0, args.ww, args.wh,
            args.cx, args.cy, args.exclude_edge_columns
        )
    else:
        pts = full_scan(args.w, args.h, args.cx, args.cy, args.exclude_edge_columns)

    pts = expand_to_nprobe(pts, args.nprobe)

    xs, ys = to_arrays(pts)
    xs.tofile("targets_x.bin")
    ys.tofile("targets_y.bin")

    print(f"generated {len(xs)} targets")


if __name__ == "__main__":
    main()
