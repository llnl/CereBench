#!/usr/bin/env python3

import argparse
from pathlib import Path

import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--w", type=int, required=True)
    parser.add_argument("--h", type=int, required=True)
    parser.add_argument("--m", type=int, required=True)
    parser.add_argument("--n", type=int, required=True)
    parser.add_argument("--mode", default="pattern")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--reduction")
    parser.add_argument("--sx", type=int)
    parser.add_argument("--sy", type=int)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    if min(args.w, args.h, args.m, args.n) <= 0:
        raise SystemExit("All dimensions must be positive")

    W, H, B, N = args.w, args.h, args.m, args.n
    pe_count = W * H
    K = (N + pe_count - 1) // pe_count

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    lhs = np.empty((B, N), dtype=np.float32)
    rhs = np.empty((B, N), dtype=np.float32)
    columns = np.arange(N, dtype=np.int64)

    if args.mode == "pattern":
        for i in range(B):
            lhs[i] = ((3 * i + 5 * columns) % 7 - 3)
            rhs[i] = ((2 * i + 7 * columns) % 5 - 2)
    elif args.mode == "ones":
        lhs.fill(1.0)
        rhs.fill(1.0)
    elif args.mode == "random":
        rng = np.random.default_rng(args.seed)
        for i in range(B):
            lhs[i] = rng.uniform(-1.0, 1.0, N)
            rhs[i] = rng.uniform(-1.0, 1.0, N)
    else:
        raise SystemExit(
            f"Unsupported input mode {args.mode!r}; "
            "use pattern, ones, or random"
        )

    lhs.astype("<f4", copy=False).tofile(
        output / "matrix-global.bin"
    )
    rhs.astype("<f4", copy=False).tofile(
        output / "vector-global.bin"
    )

    def write_distributed(array, prefix):
        padded = np.zeros(
            (B, pe_count * K), dtype=np.float32
        )
        padded[:, :N] = array

        tiles = (
            padded.reshape(B, pe_count, K)
            .transpose(1, 0, 2)
            .reshape(H, W, B, K)
        )

        tiles[0, 0].astype("<f4", copy=False).tofile(
            output / f"{prefix}-root.bin"
        )
        tiles[0, 1:].astype("<f4", copy=False).tofile(
            output / f"{prefix}-top.bin"
        )
        tiles[1:].astype("<f4", copy=False).tofile(
            output / f"{prefix}-lower.bin"
        )

    write_distributed(lhs, "matrix")
    write_distributed(rhs, "xvec")

    result = np.float32(0.0)
    for i in range(B):
        partial = np.sum(
            lhs[i] * rhs[i], dtype=np.float32
        )
        result = np.float32(result + partial)

    np.asarray([result], dtype="<f4").tofile(
        output / "reference.bin"
    )

    print(
        f"Generated CG dot product: B={B}, K={K}, "
        f"global elements={B * N}, reference={float(result)}"
    )


if __name__ == "__main__":
    main()
