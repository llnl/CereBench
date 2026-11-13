#!/usr/bin/env python3

import argparse
import numpy as np


parser = argparse.ArgumentParser()
parser.add_argument("--w", type=int, required=True)
parser.add_argument("--h", type=int, required=True)
parser.add_argument("--elements-per-pe", type=int)
parser.add_argument("--b", type=int)
parser.add_argument("--input", required=True)
parser.add_argument("--root", required=True)
parser.add_argument("--top", required=True)
parser.add_argument("--lower", required=True)
args = parser.parse_args()

elements = args.elements_per_pe
if elements is None:
    elements = args.b

if elements is None:
    raise SystemExit("Specify --elements-per-pe")

# preserve the exact bytes of every float32 value
raw = np.fromfile(args.input, dtype=np.uint8)
bytes_per_pe = elements * 4
expected = args.h * args.w * bytes_per_pe

if raw.size != expected:
    raise SystemExit(
        f"Expected {expected} bytes, found {raw.size}"
    )

data = raw.reshape(args.h, args.w, bytes_per_pe)

np.ascontiguousarray(data[0, 0]).tofile(args.root)
np.ascontiguousarray(data[0, 1:]).tofile(args.top)
np.ascontiguousarray(data[1:]).tofile(args.lower)
