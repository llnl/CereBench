#!/usr/bin/env python3

import argparse
from pathlib import Path

import numpy as np


def load(path, expected, label):
    values = np.fromfile(path, dtype="<f4")
    if values.size != expected:
        raise SystemExit(
            f"{label}: expected {expected} float32 values, "
            f"found {values.size}"
        )
    return values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--w", type=int, required=True)
    parser.add_argument("--h", type=int, required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--top", required=True)
    parser.add_argument("--lower", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    root = load(args.root, 1, "root result")
    top = load(args.top, args.w - 1, "top results")
    lower = load(
        args.lower,
        (args.h - 1) * args.w,
        "lower results",
    )

    values = np.concatenate((root, top, lower))
    bits = values.view(np.uint32)

    different = np.flatnonzero(bits != bits[0])
    if different.size:
        index = int(different[0])
        y, x = divmod(index, args.w)
        raise SystemExit(
            f"Broadcast mismatch at PE ({x},{y}): "
            f"root={float(values[0])}, "
            f"worker={float(values[index])}"
        )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    values[:1].astype("<f4", copy=False).tofile(output)

    print(
        f"All {values.size} PEs received dot product "
        f"{float(values[0])}"
    )


if __name__ == "__main__":
    main()
