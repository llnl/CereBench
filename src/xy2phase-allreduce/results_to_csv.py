#!/usr/bin/env python3

import argparse
import csv
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--w", type=int, required=True)
    parser.add_argument("--h", type=int, required=True)
    parser.add_argument("--b", type=int, required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    shape = (args.h, args.w, args.b)

    inputs = np.fromfile(args.input, dtype=np.float32).reshape(shape)
    expected = np.fromfile(args.reference, dtype=np.float32).reshape(shape)
    actual = np.fromfile(args.result, dtype=np.float32).reshape(shape)

    with open(args.output, "w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow([
            "x",
            "y",
            "element",
            "local_input",
            "expected",
            "actual",
            "absolute_error",
            "exact",
        ])

        for y in range(args.h):
            for x in range(args.w):
                for i in range(args.b):
                    exp = expected[y, x, i]
                    got = actual[y, x, i]

                    writer.writerow([
                        x,
                        y,
                        i,
                        inputs[y, x, i],
                        exp,
                        got,
                        abs(float(exp) - float(got)),
                        int(exp == got),
                    ])

    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
