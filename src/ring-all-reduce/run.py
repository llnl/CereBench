#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys

import numpy as np
from cerebras.sdk.runtime.sdkruntimepybind import (
    SdkRuntime,
    MemcpyDataType,
    MemcpyOrder,
)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", help="The compiled output dir", required=True)
    parser.add_argument("--cmaddr", help="IP:port for CS system", default=None)
    args = parser.parse_args()

    try:
        with open(f"{args.name}/out.json", encoding="utf-8") as json_file:
            compile_data = json.load(json_file)

        WIDTH = int(compile_data["params"]["width"])
        HEIGHT = int(compile_data["params"]["height"])
        TENSOR_SIZE = int(compile_data["params"]["tensor_size"])
    except Exception as e:
        print(f"[ERROR] Could not read metadata from {args.name}/out.json")
        print(f"        Did compilation fail? {e}")
        sys.exit(1)

    print(f"[INFO] Starting Cerebras Host for {WIDTH}x{HEIGHT} grid")
    print(f"[INFO] Tensor size: {TENSOR_SIZE}")

    runner = SdkRuntime(args.name, cmaddr=args.cmaddr)
    runner.load()
    runner.run()

    data_symbol = runner.get_id("data_buffer")

    num_pes = WIDTH * HEIGHT
    total_elems = num_pes * TENSOR_SIZE

    # initialize every tensor element on every PE to 1.0
    input_data = np.ones([total_elems], dtype=np.float32)
    output_data = np.zeros([total_elems], dtype=np.float32)

    # for current Option C kernel, reduction is along each row only
    expected_value = float(WIDTH)

    try:
        print("[INFO] Copying initial tensors to device...")
        runner.memcpy_h2d(
            data_symbol,
            input_data,
            0, 0, WIDTH, HEIGHT, TENSOR_SIZE,
            streaming=False,
            data_type=MemcpyDataType.MEMCPY_32BIT,
            order=MemcpyOrder.ROW_MAJOR,
            nonblock=False,
        )

        print("[INFO] Launching ring all-reduce kernel...")
        runner.launch("compute", nonblock=False)

        print("[INFO] Copying results back to host...")
        runner.memcpy_d2h(
            output_data,
            data_symbol,
            0, 0, WIDTH, HEIGHT, TENSOR_SIZE,
            streaming=False,
            data_type=MemcpyDataType.MEMCPY_32BIT,
            order=MemcpyOrder.ROW_MAJOR,
            nonblock=False,
        )

        print("\n" + "=" * 72)
        print("[SUCCESS] Ring all-reduce run complete, analyzing results")
        print("=" * 72)

        # reshape as [HEIGHT][WIDTH][TENSOR_SIZE]
        output_3d = output_data.reshape((HEIGHT, WIDTH, TENSOR_SIZE))

        print("\n[RESULTS] First element from each PE tensor:\n")
        for y in range(HEIGHT):
            row_vals = []
            for x in range(WIDTH):
                row_vals.append(f"PE({x},{y})={output_3d[y, x, 0]:.1f}")
            print("  " + "  ".join(row_vals))

        print("\n[VERIFICATION]")
        print("  Initial value on every PE tensor element: 1.0")
        print("  Current kernel behavior: row-wise ring all-reduce")
        print(f"  Expected final value on every tensor element: {expected_value:.1f}")

        all_passed = True
        max_abs_error = 0.0

        print("\n[PER-PE CHECK]")
        for y in range(HEIGHT):
            for x in range(WIDTH):
                pe_tensor = output_3d[y, x, :]
                pe_ok = np.allclose(pe_tensor, expected_value, atol=1e-2, rtol=0.0)

                pe_max_err = float(np.max(np.abs(pe_tensor - expected_value)))
                max_abs_error = max(max_abs_error, pe_max_err)

                status = "PASS" if pe_ok else "FAIL"
                first_val = float(pe_tensor[0])
                last_val = float(pe_tensor[-1])

                print(
                    f"  PE({x},{y}): expected={expected_value:.1f}, "
                    f"first={first_val:.1f}, last={last_val:.1f}, "
                    f"max_err={pe_max_err:.6f}, {status}"
                )

                if not pe_ok:
                    all_passed = False

        print("\n[SUMMARY]")
        print(f"  Grid size: {WIDTH}x{HEIGHT}")
        print(f"  Tensor size: {TENSOR_SIZE}")
        print(f"  Expected reduced value: {expected_value:.1f}")
        print(f"  Maximum absolute error: {max_abs_error:.6f}")

        print("\n" + "=" * 72)
        if all_passed:
            print("[PASS] All PEs contain the expected all-reduced tensor")
        else:
            print("[FAIL] One or more PEs did not match the expected result")
        print("=" * 72 + "\n")

        runner.stop()

    except Exception as e:
        print(f"\n[ERROR] Runtime failure or stall: {e}")
        runner.dump_core("corefile.cs1")
        runner.stop()
        subprocess.run(["csdb"])
        sys.exit(1)

if __name__ == "__main__":
    main()
