#!/usr/bin/env bash
set -euo pipefail


# CALIBRATION_BUNDLE_RECOVERY
#
# exit status 75 means csclient reported a missing bundle
# the parent recreates the bundle, then restarts the complete
# calibration so partially fetched timestamps are never used

if [[ "${CALIBRATION_RECOVERY_CHILD:-0}" != "1" ]]; then
    while true; do
        set +e
        CALIBRATION_RECOVERY_CHILD=1 bash "$0" "$@"
        child_status=$?
        set -e

        case "$child_status" in
            0|2)
                exit "$child_status"
                ;;

            75)
                if [[ -z "${BUNDLE_CREATE_CMD:-}" ]]; then
                    echo
                    echo "The bundle disappeared, but"
                    echo "BUNDLE_CREATE_CMD is not set."
                    echo
                    echo "Set it to the command used to recreate:"
                    echo '  export BUNDLE_CREATE_CMD='\'''
                    echo '      job-create-command "$JOB"'\'''
                    exit 75
                fi

                retry_seconds="${BUNDLE_RETRY_SECONDS:-30}"
                max_attempts="${BUNDLE_CREATE_RETRIES:-0}"
                create_attempt=1

                while true; do
                    echo
                    echo "Recreating bundle $JOB, attempt $create_attempt"

                    set +e
                    (
                        export JOB
                        export WSE_SERVER="${WSE_SERVER:-http://localhost:8080}"
                        export SERVER="$WSE_SERVER"
                        export CSRTSERV="$WSE_SERVER"

                        bash -c "$BUNDLE_CREATE_CMD"
                    )
                    create_status=$?
                    set -e

                    if (( create_status == 0 )); then
                        echo "Bundle $JOB was recreated."
                        break
                    fi

                    if (( max_attempts > 0 &&
                          create_attempt >= max_attempts )); then
                        echo "Unable to recreate bundle $JOB."
                        exit 75
                    fi

                    echo "Bundle creation failed, likely no WSE capacity."
                    echo "Retrying in $retry_seconds seconds."

                    sleep "$retry_seconds"
                    create_attempt=$((create_attempt + 1))
                done
                ;;

            *)
                exit "$child_status"
                ;;
        esac
    done
fi

# shadow the external csclient command so missing-bundle errors
# can be distinguished from other failures
csclient() {
    local output
    local status
    local missing_regex

    missing_regex="${MISSING_BUNDLE_REGEX:-\
bundle.*(does not exist|doesn't exist|not found|no such|unknown|expired|not active)|\
(does not exist|doesn't exist|not found|no such|unable to find|could not find).*bundle|\
bundle.*404|404.*bundle}"

    set +e
    output="$(
        CSRTSERV="${CSRTSERV:-${WSE_SERVER:-http://localhost:8080}}" command csclient "$@" 2>&1
    )"
    status=$?
    set -e

    printf '%s\n' "$output"

    if (( status != 0 )) &&
       grep -Eiq "$missing_regex" <<< "$output"; then
        echo "Detected missing or expired bundle: $JOB" >&2
        return 75
    fi

    return "$status"
}


JOB="${JOB:?Set JOB to an active bundle name}"
SERVER="${WSE_SERVER:-http://localhost:8080}"

case "$(basename "$PWD")" in
    GEMV-chain-allreduce)
        DEFAULT_MAP="chain-allreduce.map"
        DEFAULT_IMAGE="chain-allreduce-run.img"
        ;;
    GEMV-xy2phase-allreduce)
        DEFAULT_MAP="xy-two-phase-allreduce.map"
        DEFAULT_IMAGE="xy-two-phase-allreduce-run.img"
        ;;
    *)
        echo "Run this script from a GEMV benchmark directory."
        exit 1
        ;;
esac

MAP="${MAP:-$DEFAULT_MAP}"
IMAGE="${IMAGE:-$DEFAULT_IMAGE}"

W="${W:-512}"
H="${H:-512}"
CLOCK_MHZ="${CLOCK_MHZ:-850}"
PROFILE_STAGES="${PROFILE_STAGES:-0}"

ALPHA_START="${ALPHA_START:-0}"
ALPHA_MAX="${ALPHA_MAX:-8}"
ALPHA_STEP="${ALPHA_STEP:-1}"
TARGET_SPREAD="${TARGET_SPREAD:-129}"
RUNS="${RUNS:-5}"

export OUT="${OUT:-calibration_results/$JOB}"
BUILD_CMD="${BUILD_CMD:-}"

if (( RUNS < 1 || ALPHA_STEP < 1 || ALPHA_MAX < ALPHA_START )); then
    echo "Invalid sweep configuration."
    exit 1
fi

[[ -f collect_timings.py ]] || {
    echo "Missing collect_timings.py"
    exit 1
}

mkdir -p "$OUT"
mkdir -p "$OUT"

cat > "$OUT/results.csv" <<'EOF'
alpha,trial,start_spread,local_gemv,reduction,global,spread_us,local_gemv_us,reduction_us,global_us
EOF

cat > "$OUT/alpha_summary.csv" <<'EOF'
alpha,runs,min_start_spread,max_start_spread,mean_start_spread,stddev_start_spread,passed
EOF

build_for_alpha() {
    local alpha="$1"
    local log="$2"

    echo
    echo "Building image with WAIT_ALPHA=$alpha"

    if [[ -n "$BUILD_CMD" ]]; then
        (
            export WAIT_ALPHA="$alpha"
            export W H PROFILE_STAGES
            bash -c "$BUILD_CMD"
        ) 2>&1 | tee "$log"
    else
        make -B \
            W="$W" \
            H="$H" \
            WAIT_ALPHA="$alpha" \
            PROFILE_STAGES="$PROFILE_STAGES" \
            2>&1 | tee "$log"
    fi

    [[ -f "$MAP" ]] || {
        echo "Build did not produce map: $MAP"
        exit 1
    }

    [[ -f "$IMAGE" ]] || {
        echo "Build did not produce image: $IMAGE"
        exit 1
    }
}

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

for ((alpha = ALPHA_START;
      alpha <= ALPHA_MAX;
      alpha += ALPHA_STEP)); do

    echo
    echo "=========================================="
    echo "Testing WAIT_ALPHA=$alpha"
    echo "=========================================="

    alpha_dir="$OUT/alpha_${alpha}"
    mkdir -p "$alpha_dir"

    build_for_alpha "$alpha" "$alpha_dir/build.log"

    spreads=()

    for ((trial = 1; trial <= RUNS; trial++)); do
        echo
        echo "Alpha $alpha, trial $trial of $RUNS"

        trial_dir="$alpha_dir/trial_${trial}"
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

        python3 collect_timings.py \
            --w "$W" \
            --h "$H" \
            --root "$trial_dir/root.bin" \
            --top "$trial_dir/top.bin" \
            --lower "$trial_dir/lower.bin" \
            --summary "$trial_dir/summary.csv" \
            --per-pe "$trial_dir/per-pe.csv" \
            --clock-mhz "$CLOCK_MHZ" \
            --wait-alpha "$alpha" \
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

names = [
    "start_spread",
    "max_local_gemv",
    "root_reduction",
    "gemv_allreduce",
]

values = [rows[name]["cycles"] for name in names]
values += [rows[name]["microseconds"] for name in names]

print(",".join(values))
PY
        )"

        IFS=',' read -r \
            spread \
            local_gemv \
            reduction \
            global \
            spread_us \
            local_gemv_us \
            reduction_us \
            global_us <<< "$row"

        spreads+=("$spread")

        printf '%s,%s,%s\n' \
            "$alpha" \
            "$trial" \
            "$row" >> "$OUT/results.csv"
    done

    stats="$(
        python3 - "${spreads[@]}" <<'PY'
import statistics
import sys

values = [int(value) for value in sys.argv[1:]]

print(
    f"{min(values)},"
    f"{max(values)},"
    f"{statistics.mean(values):.3f},"
    f"{statistics.pstdev(values):.3f}"
)
PY
    )"

    IFS=',' read -r \
        min_spread \
        max_spread \
        mean_spread \
        stddev_spread <<< "$stats"

    passed="no"

    # "Below 129" is treated strictly as spread < 129
    if (( max_spread < TARGET_SPREAD )); then
        passed="yes"
    fi

    printf '%s,%s,%s,%s,%s,%s,%s\n' \
        "$alpha" \
        "$RUNS" \
        "$min_spread" \
        "$max_spread" \
        "$mean_spread" \
        "$stddev_spread" \
        "$passed" >> "$OUT/alpha_summary.csv"

    echo
    echo "WAIT_ALPHA=$alpha"
    echo "Spreads: ${spreads[*]}"
    echo "Minimum: $min_spread cycles"
    echo "Maximum: $max_spread cycles"
    echo "Mean:    $mean_spread cycles"
    echo "Stddev:  $stddev_spread cycles"

    if [[ "$passed" == "yes" ]]; then
        echo "$alpha" > "$OUT/selected_alpha.txt"

        cat > "$OUT/selected.env" <<EOF
WAIT_ALPHA=$alpha
TARGET_SPREAD=$TARGET_SPREAD
MAX_OBSERVED_SPREAD=$max_spread
EOF

        echo
        echo "Calibration succeeded."
        echo "Selected WAIT_ALPHA=$alpha"
        echo "All $RUNS trials had start_spread < $TARGET_SPREAD."
        echo
        column -s, -t "$OUT/alpha_summary.csv" \
            || cat "$OUT/alpha_summary.csv"

        exit 0
    fi
done

echo
echo "No alpha produced start_spread < $TARGET_SPREAD"
echo "for all $RUNS trials."
echo
column -s, -t "$OUT/alpha_summary.csv" \
    || cat "$OUT/alpha_summary.csv"

exit 2
