#!/usr/bin/env python3

import argparse
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--w", type=int, required=True)
    parser.add_argument("--h", type=int, required=True)
    parser.add_argument("--b", type=int, required=True)
    parser.add_argument(
        "--mode",
        choices=["ones", "rank", "pattern", "random-int"],
        default="pattern",
    )
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    shape = (args.h, args.w, args.b)

    if args.mode == "ones":
        data = np.ones(shape, dtype=np.float32)

    elif args.mode == "rank":
        rank = np.arange(
            1, args.w * args.h + 1, dtype=np.int32
        ).reshape(args.h, args.w, 1)

        index = np.arange(args.b, dtype=np.int32).reshape(1, 1, args.b)
        data = (rank + index).astype(np.float32)

    elif args.mode == "pattern":
        rank = np.arange(
            args.w * args.h, dtype=np.int32
        ).reshape(args.h, args.w, 1)

        index = np.arange(args.b, dtype=np.int32).reshape(1, 1, args.b)
        data = (((rank + 1) * (index + 3)) % 31 - 15).astype(np.float32)

    else:
        rng = np.random.default_rng(args.seed)
        data = rng.integers(
            low=-8,
            high=9,
            size=shape,
            dtype=np.int32,
        ).astype(np.float32)

    data.tofile(args.output)

    print(f"Wrote {args.output}")
    print(f"Shape: {data.shape}")
    print(f"Mode: {args.mode}")


if __name__ == "__main__":
    main()
