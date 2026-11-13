#!/usr/bin/env bash
set -euo pipefail

W=512
H=512
K_VALUES=(1 2 4 8 16)
B_VALUES="1,4,16,64,256,1024"
LIFETIME="${LIFETIME:-40000}"

STAMP=$(date +%Y%m%d_%H%M%S)
JOB="cg-k-sweep-${STAMP}"
OUT="/projects/cerebras/cg_k_sweep_${STAMP}"

first=1

for K in "${K_VALUES[@]}"; do
    N=$((W * H * K))

    echo "============================================================"
    echo "Running K=${K}, N=${N}, one trial per configuration"
    echo "============================================================"

    args=(
        python3 run_compare_CG-dotprod.py
        --w "$W"
        --h "$H"
        --k "$K"
        --runs 1
        --b-values "$B_VALUES"
        --job "$JOB"
        --lifetime "$LIFETIME"
        --results-dir "${OUT}/K_${K}_N_${N}"
    )

    if (( first )); then
        first=0
    else
        args+=(--skip-queue)
    fi

    "${args[@]}"
done

echo "Sweep complete: ${OUT}"
