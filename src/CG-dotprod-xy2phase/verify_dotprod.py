#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("trial", type=Path)
parser.add_argument("--w", type=int, default=512)
parser.add_argument("--h", type=int, default=512)
parser.add_argument("--b", type=int)
parser.add_argument("--k", type=int, default=1)
parser.add_argument("--sx", type=int, default=23)
parser.add_argument("--sy", type=int, default=23)
parser.add_argument("--input-dir", type=Path, default=Path("gemv_input"))
args = parser.parse_args()

W = args.w
H = args.h
K = args.k
SX = args.sx
SY = args.sy
trial = args.trial
input_dir = args.input_dir

if args.b is None:
    root_input = input_dir / "matrix-root.bin"
    if not root_input.is_file():
        parser.error(f"missing input file: {root_input}")

    byte_count = root_input.stat().st_size
    bytes_per_b = 4 * K

    if byte_count % bytes_per_b:
        parser.error(f"cannot infer B from {root_input}")

    B = byte_count // bytes_per_b
else:
    B = args.b

CHUNK = 1_048_576

regions = [
    ("root", B * K),
    ("top", (W - 1) * B * K),
    ("lower", (H - 1) * W * B * K),
]

reference = 0.0
sum_abs = 0.0
elements = 0

for name, expected in regions:
    matrix = np.memmap(
        input_dir / f"matrix-{name}.bin",
        dtype="<f4",
        mode="r",
    )
    xvec = np.memmap(
        input_dir / f"xvec-{name}.bin",
        dtype="<f4",
        mode="r",
    )

    if matrix.size != expected or xvec.size != expected:
        raise SystemExit(
            f"{name}: expected {expected} elements, "
            f"matrix={matrix.size}, xvec={xvec.size}"
        )

    for begin in range(0, expected, CHUNK):
        stop = min(begin + CHUNK, expected)
        products = np.multiply(
            matrix[begin:stop],
            xvec[begin:stop],
            dtype=np.float32,
        )
        products64 = products.astype(np.float64)
        reference += products64.sum(dtype=np.float64)
        sum_abs += np.abs(products64).sum(dtype=np.float64)

    elements += expected


def result(name, expected):
    values = np.fromfile(
        trial / f"result-{name}.bin",
        dtype="<f4",
    )
    if values.size != expected:
        raise SystemExit(
            f"result-{name}: expected {expected}, "
            f"found {values.size}"
        )
    return values


results = np.concatenate([
    result("root", 1),
    result("top", W - 1),
    result("lower", (H - 1) * W),
])

actual = float(results[0])
bits = results.view(np.uint32)
broadcast_ok = bool(np.all(bits == bits[0]))

depth = (
    (SX - 1)
    + ((W + SX - 1) // SX - 1)
    + (SY - 1)
    + ((H + SY - 1) // SY - 1)
    + (B - 1)
)

epsilon = np.finfo(np.float32).eps
gamma = depth * epsilon / (1.0 - depth * epsilon)
tolerance = max(
    gamma * sum_abs,
    epsilon * max(abs(reference), 1.0),
)

error = abs(actual - reference)
calculation_ok = np.isfinite(actual) and error <= tolerance

print(f"elements        = {elements}")
print(f"reference       = {reference:.9g}")
print(f"WSE result      = {actual:.9g}")
print(f"absolute error  = {error:.9g}")
print(f"tolerance       = {tolerance:.9g}")
print(f"broadcast       = {'PASS' if broadcast_ok else 'FAIL'}")
print(f"calculation     = {'PASS' if calculation_ok else 'FAIL'}")

raise SystemExit(
    0 if broadcast_ok and calculation_ok else 1
)
