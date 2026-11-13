#!/usr/bin/env python3

import argparse
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("--w", type=int, required=True)
parser.add_argument("--h", type=int, required=True)
parser.add_argument("--b", type=int, required=True)
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()

data = np.fromfile(args.input, dtype=np.float32)

expected = args.w * args.h * args.b
if data.size != expected:
    raise SystemExit(f"Expected {expected} values, found {data.size}")

data = data.reshape(args.h, args.w, args.b)
total = data.sum(axis=(0, 1), dtype=np.float32)

# Every PE receives the same reduced vector.
result = np.broadcast_to(total, data.shape).copy()
result.tofile(args.output)

print(f"Wrote {result.size} values to {args.output}")
