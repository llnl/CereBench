#!/usr/bin/env bash
# SCALAR_ALLREDUCE_48BIT_PATCH
set -euo pipefail

JOB="${JOB:?Set JOB to an active bundle name}"
SERVER="${WSE_SERVER:-http://localhost:8080}"
MAP="${MAP:-xy-two-phase-allreduce.map}"
IMAGE="${IMAGE:-xy-two-phase-allreduce-run.img}"

W="${W:-512}"
H="${H:-512}"
B="${B:?Set B to the compiled vector length}"
FREQ="${FREQ:-850000000}"
RUNS="${RUNS:-5}"
OUT="${OUT:-out_hw/timing_5runs}"

[[ -f "$MAP" ]] || { echo "Missing map: $MAP"; exit 1; }
[[ -f "$IMAGE" ]] || { echo "Missing image: $IMAGE"; exit 1; }

rm -rf "$OUT"
mkdir -p "$OUT"

echo \
"trial,start_spread,global_cycles,max_local_cycles,global_time_us,local_time_us" \
> "$OUT/results.csv"

fetch_symbol() {
    local symbol="$1"
    local output="$2"
    local expected="$3"
    local trial_dir="$4"
    local tag="${symbol//./_}"
    local zip="$trial_dir/${tag}.zip"
    local directory="$trial_dir/${tag}"
    local file actual

    rm -rf "$directory" "$zip"
    mkdir -p "$directory"

    CSRTSERV="$SERVER" csclient job \
        -bn "$JOB" \
        -r main_compute \
        pause \
        fetch="symbol=$symbol savepath=$zip map=$MAP"

    unzip -oq "$zip" -d "$directory"
    file="$(find "$directory" -type f -print -quit)"

    [[ -n "$file" ]] || {
        echo "No data returned for $symbol"
        exit 1
    }

    cp "$file" "$output"
    actual="$(wc -c < "$output" | tr -d '[:space:]')"

    [[ "$actual" -eq "$expected" ]] || {
        echo "$symbol: expected $expected bytes, got $actual"
        exit 1
    }

    rm -rf "$directory" "$zip"
}

for trial in $(seq 1 "$RUNS"); do
    echo
    echo "========== Trial $trial of $RUNS =========="

    trial_dir="$OUT/trial_${trial}"
    mkdir -p "$trial_dir"

    CSRTSERV="$SERVER" csclient job \
        -bn "$JOB" -r main_compute wipe

    sleep 2

    CSRTSERV="$SERVER" csclient job \
        -bn "$JOB" -r main_compute program="$IMAGE"

    sleep 2

    CSRTSERV="$SERVER" csclient job \
        -bn "$JOB" -r main_compute run wait=30

    fetch_symbol root.phase_timestamps \
        "$trial_dir/root-phase.bin" \
        30 "$trial_dir"

    fetch_symbol worker_top.phase_timestamps \
        "$trial_dir/top-phase.bin" \
        "$(((W - 1) * 15 * 2))" "$trial_dir"

    fetch_symbol worker_lower.phase_timestamps \
        "$trial_dir/lower-phase.bin" \
        "$((W * (H - 1) * 15 * 2))" "$trial_dir"

    fetch_symbol root.result \
        "$trial_dir/result-root.bin" \
        4 "$trial_dir"

    fetch_symbol worker_top.result \
        "$trial_dir/result-top.bin" \
        "$(((W - 1) * 4))" "$trial_dir"

    fetch_symbol worker_lower.result \
        "$trial_dir/result-lower.bin" \
        "$((W * (H - 1) * 4))" "$trial_dir"

    python3 - "$trial_dir" "$W" "$H" <<'PY'
import sys
import numpy as np
from pathlib import Path

directory = Path(sys.argv[1])
W = int(sys.argv[2])
H = int(sys.argv[3])

root = np.fromfile(directory / "result-root.bin", dtype="<u4")
top = np.fromfile(directory / "result-top.bin", dtype="<u4")
lower = np.fromfile(directory / "result-lower.bin", dtype="<u4")

if root.size != 1:
    raise SystemExit("Root result is not scalar")

if top.size != W - 1 or lower.size != W * (H - 1):
    raise SystemExit("Worker scalar-result dimensions are incorrect")

all_results = np.concatenate((root, top, lower))

if not np.all(all_results == root[0]):
    raise SystemExit("Scalar broadcast validation failed")

root.tofile(directory / "result-scalar.bin")
value = root.view("<f4")[0]

if not np.isfinite(value):
    raise SystemExit("Scalar result is not finite")

print(f"Scalar broadcast validated across {W * H} PEs: {value}")
PY

    metrics="$(
        python3 - "$trial_dir" "$W" "$H" "$FREQ" <<'PY'
import sys
from pathlib import Path
import numpy as np

directory = Path(sys.argv[1])
W = int(sys.argv[2])
H = int(sys.argv[3])
freq = float(sys.argv[4])

WORDS = 15
MOD = 1 << 48
MASK = MOD - 1

def load(path, count):
    data = np.fromfile(path, dtype="<u2")
    expected = count * WORDS

    if data.size != expected:
        raise RuntimeError(
            f"{path}: expected {expected} words, got {data.size}"
        )

    return data.reshape(count, WORDS)

def snapshot(words, offset):
    return (
        words[..., offset].astype(np.uint64)
        | (words[..., offset + 1].astype(np.uint64) << 16)
        | (words[..., offset + 2].astype(np.uint64) << 32)
    )

def elapsed(start, stop, direction):
    start = np.asarray(start, dtype=np.uint64)
    stop = np.asarray(stop, dtype=np.uint64)

    if direction == "down":
        return (
            start + np.uint64(MOD) - stop
        ) & np.uint64(MASK)

    return (
        stop + np.uint64(MOD) - start
    ) & np.uint64(MASK)

root = load(directory / "root-phase.bin", 1)
top = load(directory / "top-phase.bin", W - 1)
lower = load(directory / "lower-phase.bin", W * (H - 1))

words = np.zeros((H, W, WORDS), dtype=np.uint16)
words[0, 0] = root[0]
words[0, 1:] = top
words[1:] = lower.reshape(H - 1, W, WORDS)

reference = snapshot(words, 0)
start = snapshot(words, 3)
producer_end = snapshot(words, 6)
reduction_end = snapshot(words, 9)
final_end = snapshot(words, 12)

if not np.array_equal(start, producer_end):
    raise RuntimeError(
        "Plain AllReduce producer-end timestamp must equal start"
    )

scores = {}

for direction in ("down", "up"):
    intervals = (
        elapsed(reference, start, direction),
        elapsed(start, reduction_end, direction),
        elapsed(reduction_end, final_end, direction),
    )
    scores[direction] = max(int(x.max()) for x in intervals)

direction = min(scores, key=scores.get)
local_elapsed = elapsed(start, final_end, direction)

if int(local_elapsed.max()) >= MOD // 4:
    raise RuntimeError("Implausibly large 48-bit timing interval")

yy, xx = np.indices((H, W), dtype=np.uint64)
propagation = xx + yy + 2

aligned_start = (
    elapsed(reference, start, direction) + propagation
)
aligned_end = (
    elapsed(reference, final_end, direction) + propagation
)

if np.any(aligned_end < aligned_start):
    raise RuntimeError("Aligned completion precedes aligned start")

if not np.array_equal(
    aligned_end - aligned_start,
    local_elapsed,
):
    raise RuntimeError("48-bit timestamp consistency check failed")

aligned_start -= aligned_start.min()
aligned_end -= aligned_start.min()

start_spread = int(aligned_start.max())
global_cycles = int(aligned_end.max())
max_local_cycles = int(local_elapsed.max())

np.savetxt(
    directory / "corrected_start_grid.txt",
    aligned_start.astype(np.int64),
    fmt="%d",
)
np.savetxt(
    directory / "corrected_end_grid.txt",
    aligned_end.astype(np.int64),
    fmt="%d",
)
np.savetxt(
    directory / "local_elapsed_grid.txt",
    local_elapsed.astype(np.int64),
    fmt="%d",
)

(directory / "counter_direction.txt").write_text(
    direction + "\n"
)

global_us = global_cycles / freq * 1e6
local_us = max_local_cycles / freq * 1e6

print(
    f"{start_spread},"
    f"{global_cycles},"
    f"{max_local_cycles},"
    f"{global_us:.9f},"
    f"{local_us:.9f}"
)
PY
    )"

    IFS=',' read -r \
        start_spread global_cycles max_local_cycles \
        global_time_us local_time_us <<< "$metrics"

    echo \
"$trial,$start_spread,$global_cycles,$max_local_cycles,$global_time_us,$local_time_us" \
        >> "$OUT/results.csv"

    echo "Start spread     : $start_spread cycles"
    echo "Global latency   : $global_cycles cycles"
    echo "Maximum local    : $max_local_cycles cycles"
    echo "Global time      : $global_time_us microseconds"
done

echo
echo "========== Results =========="
column -s, -t "$OUT/results.csv" || cat "$OUT/results.csv"

python3 - "$OUT/results.csv" <<'PY'
import csv
import statistics
import sys

with open(sys.argv[1], newline="") as file:
    rows = list(csv.DictReader(file))

for name in (
    "start_spread",
    "global_cycles",
    "max_local_cycles",
):
    values = [int(row[name]) for row in rows]
    print()
    print(f"{name} values = {values}")
    print(f"{name} mean   = {statistics.mean(values):.3f}")
    print(f"{name} min    = {min(values)}")
    print(f"{name} max    = {max(values)}")
    print(f"{name} stddev = {statistics.pstdev(values):.3f}")
PY
