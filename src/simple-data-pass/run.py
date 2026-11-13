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

    # A flat array representing the entire grid's memory
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

        print("[INFO] Launching fabric communication kernel...")
        runner.launch('compute', nonblock=False)

        print("[INFO] Fetching results...")
        runner.memcpy_d2h(
            output_data, data_symbol,
            0, 0, WIDTH, HEIGHT, TENSOR_SIZE,
            streaming=False, data_type=MemcpyDataType.MEMCPY_32BIT,
            order=MemcpyOrder.ROW_MAJOR, nonblock=False
        )

        print("\n[SUCCESS] Simulation Complete! Verifying Data Shift:")
        print(f"  PE(0,0) First Value : {output_data[0]}")
        
        if WIDTH > 1:
            print(f"  PE(1,0) First Value : {output_data[TENSOR_SIZE]}")

        runner.stop()

    except Exception as e:
        print(f"\n[!] Caught stall: {e}")
        runner.dump_core("corefile.cs1")
        runner.stop()
        subprocess.run(["csdb"])
        sys.exit(1)

if __name__ == "__main__":
    main()
