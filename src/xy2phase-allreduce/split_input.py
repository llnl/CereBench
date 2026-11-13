#!/usr/bin/env python3

import argparse
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("--w", type=int, required=True)
parser.add_argument("--h", type=int, required=True)
parser.add_argument("--b", type=int, required=True)
parser.add_argument("--input", required=True)
parser.add_argument("--root", required=True)
parser.add_argument("--top", required=True)
parser.add_argument("--lower", required=True)
args = parser.parse_args()

# Each 32-bit value appears as two 16-bit _word elements in the map.
raw = np.fromfile(args.input, dtype="<u2")
expected = args.h * args.w * args.b * 2

if raw.size != expected:
    raise ValueError(
        f"Expected {expected} uint16 words, found {raw.size}"
    )

data = raw.reshape(args.h, args.w, args.b, 2)

np.ascontiguousarray(data[0, 0]).tofile(args.root)
np.ascontiguousarray(data[0, 1:]).tofile(args.top)
np.ascontiguousarray(data[1:]).tofile(args.lower)
