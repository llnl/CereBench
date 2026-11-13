#!/usr/bin/env python3

import argparse
import numpy as np


parser = argparse.ArgumentParser()
parser.add_argument("--reference", required=True)
parser.add_argument("--actual", required=True)
parser.add_argument(
    "--mode",
    choices=["exact", "tolerant"],
    default="tolerant",
)
parser.add_argument("--atol", type=float, default=1.0e-4)
parser.add_argument("--rtol", type=float, default=1.0e-4)
args = parser.parse_args()

reference = np.fromfile(args.reference, dtype=np.float32)
actual = np.fromfile(args.actual, dtype=np.float32)

if reference.shape != actual.shape:
    raise SystemExit(
        f"Size mismatch: expected {reference.size}, "
        f"got {actual.size}"
    )

if args.mode == "exact":
    passed = np.array_equal(reference, actual)
else:
    passed = np.allclose(
        reference,
        actual,
        atol=args.atol,
        rtol=args.rtol,
    )

error = np.abs(reference - actual)
max_error = float(error.max()) if error.size else 0.0

print(f"Elements: {actual.size}")
print(f"Maximum absolute error: {max_error}")

if not passed:
    bad = np.flatnonzero(
        ~np.isclose(
            reference,
            actual,
            atol=args.atol,
            rtol=args.rtol,
        )
    )

    for index in bad[:10]:
        print(
            f"Mismatch {index}: "
            f"expected={reference[index]}, "
            f"actual={actual[index]}"
        )

    raise SystemExit("Verification failed")

print("Verification passed")
