#!/usr/bin/env python3

import argparse
import numpy as np

p = argparse.ArgumentParser()
p.add_argument("--w", type=int, required=True)
p.add_argument("--h", type=int, required=True)
args = p.parse_args()

np.array([0, 0], dtype=np.int16).tofile("coords-root.bin")

np.array(
    [[x, 0] for x in range(1, args.w)],
    dtype=np.int16,
).tofile("coords-top.bin")

np.array(
    [[[x, y] for x in range(args.w)]
     for y in range(1, args.h)],
    dtype=np.int16,
).tofile("coords-lower.bin")
