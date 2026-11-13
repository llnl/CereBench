#!/usr/bin/env bash
set -euo pipefail

JOB="${JOB:?Set JOB to an active bundle name}"
SERVER="${WSE_SERVER:-http://localhost:8080}"

case "$(basename "$PWD")" in
    GEMV-chain-allreduce)
        DEFAULT_MAP="chain-allreduce.map"
        DEFAULT_IMAGE="chain-allreduce-run.img"
        ;;
    GEMV-xy2phase-allreduce|CG-dotprod-xy2phase|CG-dotprod-*-xy2phase|CG-dotprod-chain|CG-dotprod-*-chain)
        DEFAULT_MAP="xy-two-phase-allreduce.map"
        DEFAULT_IMAGE="xy-two-phase-allreduce-run.img"
        ;;
    *)
        echo "Run this script from a supported benchmark directory."
        exit 1
        ;;
esac

MAP="${MAP:-$DEFAULT_MAP}"
IMAGE="${IMAGE:-$DEFAULT_IMAGE}"

W="${W:-512}"
H="${H:-512}"
B="${B:-64}"
CLOCK_MHZ="${CLOCK_MHZ:-850}"
WAIT_ALPHA="${WAIT_ALPHA:-1}"
RUNS="${RUNS:-5}"

OUT="${OUT:-out_hw/timing_5runs}"

[[ -f "$MAP" ]] || {
    echo "Missing map: $MAP"
    exit 1
}

[[ -f "$IMAGE" ]] || {
    echo "Missing image: $IMAGE"
    exit 1
}

rm -rf "$OUT"
mkdir -p "$OUT"

echo \
"trial,start_spread,compute_x1_fused,remaining_reduction,total,spread_us,compute_x1_fused_us,remaining_reduction_us,total_us" \
> "$OUT/results.csv"

fetch_symbol() {
    local symbol="$1"
    local destination="$2"
    local expected="$3"
    local trial_dir="$4"

    local tag="${symbol//./_}"
    local zip="$trial_dir/${tag}.zip"
    local directory="$trial_dir/${tag}"

    rm -rf "$directory" "$zip"
    mkdir -p "$directory"

    CSRTSERV="$SERVER" csclient job \
        -bn "$JOB" \
        -r main_compute \
        pause \
        fetch="symbol=$symbol savepath=$zip map=$MAP"

    unzip -oq "$zip" -d "$directory"

    local file
    file="$(find "$directory" -type f -print -quit)"

    [[ -n "$file" ]] || {
        echo "No data returned for $symbol"
        exit 1
    }

    cp "$file" "$destination"

    local actual
    actual="$(wc -c < "$destination" | tr -d '[:space:]')"

    [[ "$actual" -eq "$expected" ]] || {
        echo "$symbol: expected $expected bytes, got $actual"
        exit 1
    }
}

for trial in $(seq 1 "$RUNS"); do
    echo
    echo "========== Trial $trial of $RUNS =========="

    trial_dir="$OUT/trial_${trial}"
    mkdir -p "$trial_dir"

    CSRTSERV="$SERVER" csclient job \
        -bn "$JOB" \
        -r main_compute \
        wipe

    sleep 2

    CSRTSERV="$SERVER" csclient job \
        -bn "$JOB" \
        -r main_compute \
        program="$IMAGE"

    sleep 2

    CSRTSERV="$SERVER" csclient job \
        -bn "$JOB" \
        -r main_compute \
        run wait=1

    fetch_symbol \
        root.phase_timestamps \
        "$trial_dir/root.bin" \
        "$((15 * 2))" \
        "$trial_dir"

    fetch_symbol \
        worker_top.phase_timestamps \
        "$trial_dir/top.bin" \
        "$(((W - 1) * 15 * 2))" \
        "$trial_dir"

    fetch_symbol \
        worker_lower.phase_timestamps \
        "$trial_dir/lower.bin" \
        "$(((H - 1) * W * 15 * 2))" \
        "$trial_dir"

    fetch_symbol \
        root.result \
        "$trial_dir/result-root.bin" \
        4 \
        "$trial_dir"

    fetch_symbol \
        worker_top.result \
        "$trial_dir/result-top.bin" \
        "$(((W - 1) * 4))" \
        "$trial_dir"

    fetch_symbol \
        worker_lower.result \
        "$trial_dir/result-lower.bin" \
        "$(((H - 1) * W * 4))" \
        "$trial_dir"

    fetch_symbol \
        root.value \
        "$trial_dir/value-root.bin" \
        "$((B * 4))" \
        "$trial_dir"

    python3 collect_timings.py \
        --w "$W" \
        --h "$H" \
        --root "$trial_dir/root.bin" \
        --top "$trial_dir/top.bin" \
        --lower "$trial_dir/lower.bin" \
        --summary "$trial_dir/summary.csv" \
        --per-pe "$trial_dir/per-pe.csv" \
        --clock-mhz "$CLOCK_MHZ" \
        --wait-alpha "$WAIT_ALPHA" \
        --counter-direction auto

    row="$(
        python3 - "$trial_dir/summary.csv" <<'PY'
import csv
import sys

with open(sys.argv[1], newline="") as file:
    rows = {
        row["metric"]: row
        for row in csv.DictReader(file)
    }

names = ["start_spread", "max_local_compute_x1_fused", "root_remaining_reduction", "dotprod_total"]

values = [rows[name]["cycles"] for name in names]
values += [rows[name]["microseconds"] for name in names]

print(",".join(values))
PY
    )"

    echo "$trial,$row" >> "$OUT/results.csv"
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

for metric in ("start_spread", "compute_x1_fused", "remaining_reduction", "total"):
    values = [int(row[metric]) for row in rows]

    print()
    print(f"{metric} values = {values}")
    print(f"{metric} mean   = {statistics.mean(values):.3f}")
    print(f"{metric} min    = {min(values)}")
    print(f"{metric} max    = {max(values)}")
    print(
        f"{metric} stddev = "
        f"{statistics.pstdev(values):.3f}"
    )
PY
