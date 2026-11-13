#!/usr/bin/env python3
import argparse
import numpy as np
import subprocess
import sys
import json
from cerebras.sdk.runtime.sdkruntimepybind import SdkRuntime, MemcpyDataType, MemcpyOrder

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', help="The compiled output dir", required=True)
    parser.add_argument('--cmaddr', help="IP:port for CS system", default=None)
    args = parser.parse_args()

    try:
        with open(f"{args.name}/out.json", encoding='utf-8') as json_file:
            compile_data = json.load(json_file)
            
        WIDTH = int(compile_data['params']['width'])
        HEIGHT = int(compile_data['params']['height'])
        TENSOR_SIZE = int(compile_data['params']['tensor_size'])
    except Exception as e:
        print(f"[ERROR] Could not read metadata from {args.name}/out.json. Did compilation fail?\n{e}")
        sys.exit(1)

    print(f"[INFO] Starting Cerebras Host for {WIDTH}x{HEIGHT} grid (Tensor Size: {TENSOR_SIZE})...")
    runner = SdkRuntime(args.name, cmaddr=args.cmaddr)
    runner.load()
    runner.run()

    data_symbol = runner.get_id("data_buffer")

    # initialize each PE with value = 1.0
    input_data = np.ones([WIDTH * HEIGHT * TENSOR_SIZE], dtype=np.float32)
    output_data = np.zeros([WIDTH * HEIGHT * TENSOR_SIZE], dtype=np.float32)

    try:
        print("[INFO] Streaming initial data to wafer...")
        runner.memcpy_h2d(
            data_symbol, input_data,
            0, 0, WIDTH, HEIGHT, TENSOR_SIZE,
            streaming=False, data_type=MemcpyDataType.MEMCPY_32BIT,
            order=MemcpyOrder.ROW_MAJOR, nonblock=False
        )

        print("[INFO] Launching PINGPONG kernel...")
        runner.launch('compute', nonblock=False)

        print("[INFO] Fetching results...")
        runner.memcpy_d2h(
            output_data, data_symbol,
            0, 0, WIDTH, HEIGHT, TENSOR_SIZE,
            streaming=False, data_type=MemcpyDataType.MEMCPY_32BIT,
            order=MemcpyOrder.ROW_MAJOR, nonblock=False
        )

        print("\n" + "="*60)
        print("[SUCCESS] Pingpong Complete! Analyzing Results...")
        print("="*60)
        
        # extract per-PE results (first element of each PE's tensor)
        results = []
        for pe_idx in range(WIDTH * HEIGHT):
            offset = pe_idx * TENSOR_SIZE
            pe_value = output_data[offset]
            results.append(pe_value)
        
        # display results in a grid
        print("\n[RESULTS] PE Grid (first value from each tensor):\n")
        for y in range(HEIGHT):
            row_str = "  "
            for x in range(WIDTH):
                pe_idx = y * WIDTH + x
                row_str += f"PE({x},{y})={results[pe_idx]:.1f}  "
            print(row_str)
        
        # verify pingpong behavior
        print("\n[VERIFICATION] Expected Behavior:")
        print("  Initial: All PEs start with 1.0")
        print("  PING (East): Data flows left→right, accumulating")
        print("  PONG (West): Data flows right→left, accumulating")
        
        all_passed = True
        
        if WIDTH > 1:
            # for a 1D row (y=0), calculate expected values
            print("\n[EXPECTED VALUES] For row y=0:")
            for x in range(WIDTH):
                if x == 0:
                    # leftmost PE: starts with 1, receives (1+...+1) from right in pong
                    expected = 1.0 + float(WIDTH)
                elif x == WIDTH - 1:
                    # rightmost PE: starts with 1, receives (1+...+1) from left in ping
                    expected = 1.0 + float(WIDTH)
                else:
                    # middle PEs: accumulate from both directions
                    expected = 1.0 + float(x + 1) + float(WIDTH - x)
                
                pe_idx = x  # y=0 row
                actual = results[pe_idx]
                status = "✓ PASS" if abs(actual - expected) < 0.01 else "✗ FAIL"
                print(f"  PE({x},0): Expected={expected:.1f}, Actual={actual:.1f} {status}")
                
                if abs(actual - expected) >= 0.01:
                    all_passed = False
        
        print("\n" + "="*60)
        if all_passed:
            print("[✓] ALL TESTS PASSED - Pingpong working correctly!")
        else:
            print("[✗] SOME TESTS FAILED - Check PE logic")
        print("="*60 + "\n")

        runner.stop()

    except Exception as e:
        print(f"\n[!] Caught stall: {e}")
        runner.dump_core("corefile.cs1")
        runner.stop()
        subprocess.run(["csdb"])
        sys.exit(1)

if __name__ == "__main__":
    main()
