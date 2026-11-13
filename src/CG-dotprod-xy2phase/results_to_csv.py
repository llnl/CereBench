#!/usr/bin/env python3

import argparse
import csv
import numpy as np


parser = argparse.ArgumentParser()
parser.add_argument("--reference", required=True)
parser.add_argument("--result", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()

expected = np.fromfile(args.reference, dtype=np.float32)
actual = np.fromfile(args.result, dtype=np.float32)

if expected.size != actual.size:
    raise SystemExit(
        f"Expected {expected.size} results, got {actual.size}"
    )

with open(args.output, "w", newline="") as output:
    writer = csv.writer(output)
    writer.writerow([
        "element",
        "expected",
        "actual",
        "absolute_error",
        "exact",
    ])

    for i, (exp, got) in enumerate(zip(expected, actual)):
        writer.writerow([
            i,
            exp,
            got,
            abs(float(exp) - float(got)),
            int(exp == got),
        ])

print(f"Wrote {args.output}")
