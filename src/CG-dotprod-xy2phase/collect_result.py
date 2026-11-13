#!/usr/bin/env python3

import argparse
import numpy as np


def load(path, expected, label):
    data = np.fromfile(path, dtype=np.float32)

    if data.size != expected:
        raise SystemExit(
            f"{label}: expected {expected} values, "
            f"found {data.size}"
        )

    return data


def verify_broadcast(label, values, root, b):
    values = values.reshape(-1, b)
    root_bits = root.view(np.uint32)
    chunk_size = 1024

    for start in range(0, values.shape[0], chunk_size):
        stop = min(values.shape[0], start + chunk_size)
        chunk = values[start:stop].view(np.uint32)
        differences = chunk != root_bits[None, :]

        if np.any(differences):
            local_pe, element = np.argwhere(
                differences
            )[0]

            pe = start + int(local_pe)
            element = int(element)

            raise SystemExit(
                f"{label}: PE {pe}, element {element} "
                f"differs from root: "
                f"{values[pe, element]} != {root[element]}"
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--w", type=int, required=True)
    parser.add_argument("--h", type=int, required=True)
    parser.add_argument("--b", type=int, required=True)
    parser.add_argument("--m", type=int, required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--lower", required=True)
    parser.add_argument("--top", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if args.b != args.m:
        raise SystemExit(
            f"Full AllReduce requires B=M, got "
            f"B={args.b}, M={args.m}"
        )

    root = load(args.root, args.b, "root")

    top = load(
        args.top,
        (args.w - 1) * args.b,
        "worker_top",
    )

    lower = load(
        args.lower,
        (args.h - 1) * args.w * args.b,
        "worker_lower",
    )

    verify_broadcast("worker_top", top, root, args.b)
    verify_broadcast("worker_lower", lower, root, args.b)

    root.tofile(args.output)

    pe_count = args.w * args.h
    print(
        f"Verified identical {args.b}-value results "
        f"on all {pe_count} PEs"
    )
    print(f"Wrote {root.size} values to {args.output}")


if __name__ == "__main__":
    main()
