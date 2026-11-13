# CG_DOT_PRODUCT_PATCH
SHELL := /bin/bash
.RECIPEPREFIX := >
.DELETE_ON_ERROR:

BENCH_NAME := xy-two-phase-allreduce
BENCH_SRC  ?= bench.paint

BENCH_OBJ      := $(BENCH_NAME).obj
BENCH_IMG      := $(BENCH_NAME).img
BENCH_IMG_RUN  := $(BENCH_NAME)-run.img
BENCH_MAP      := $(BENCH_NAME).map
BENCH_NOTE     := $(BENCH_NAME).note
BENCH_ENTRY    := $(BENCH_NAME).entry
BENCH_PS       := $(BENCH_NAME).ps
BENCH_REGION   := $(BENCH_NAME)-region.json
BENCH_LISTING  := $(BENCH_NAME)-listing.json

BENCH_ELF      := $(BENCH_NAME).elf
BENCH_ELF_CORE := $(BENCH_NAME).elf-core
BENCH_CORE     := $(BENCH_NAME).core

CONFIG_STAMP := .build-config
PAINT_STAMP  := .paint-stamp
LINK_STAMP   := .build-linked
COORD_STAMP  := .coords-stamp
INPUT_STAMP  := .dotprod-input

COORD_BINS := coords-root.bin coords-top.bin coords-lower.bin

MODE ?= sim
ARCH ?= sdr

# ------------------------------------------------------------
# GEMV dimensions
#
# global operation:
#     result[M] = matrix[M,N] * vector[N]
#
# PE(x,y) stores:
#     matrix[B,K]
#     xvec[K]
#
# B and K include zero padding where necessary
# ------------------------------------------------------------

W ?= 8
H ?= 8
M ?= 16
N ?= 16

EXPECTED_B = $(M)
EXPECTED_K = $(shell python3 -c \
'print(($(N) + ($(W) * $(H)) - 1) // ($(W) * $(H)))')

B ?= $(EXPECTED_B)
K ?= $(EXPECTED_K)

# two-phase reduction group sizes
SX ?= $(shell python3 -c 'import math; print(max(1,int(math.sqrt($(W)) + 0.5)))')
SY ?= $(shell python3 -c 'import math; print(max(1,int(math.sqrt($(H)) + 0.5)))')

WAIT_ALPHA ?= 1
PROFILE_STAGES ?= 0

INPUT_MODE ?= pattern
INPUT_SEED ?= 1
INPUT_DIR  ?= gemv_input

GENERATE_INPUT ?= 1

MATRIX_GLOBAL_BIN := $(INPUT_DIR)/matrix-global.bin
VECTOR_GLOBAL_BIN := $(INPUT_DIR)/vector-global.bin

MATRIX_ROOT_BIN  := $(INPUT_DIR)/matrix-root.bin
MATRIX_TOP_BIN   := $(INPUT_DIR)/matrix-top.bin
MATRIX_LOWER_BIN := $(INPUT_DIR)/matrix-lower.bin

XVEC_ROOT_BIN  := $(INPUT_DIR)/xvec-root.bin
XVEC_TOP_BIN   := $(INPUT_DIR)/xvec-top.bin
XVEC_LOWER_BIN := $(INPUT_DIR)/xvec-lower.bin

GENERATED_REFERENCE := $(INPUT_DIR)/reference.bin

REFERENCE_BIN ?= out-ref.bin
SIM_OUTPUT    ?= out-sim.bin
WSE_OUTPUT    ?= out-wse.bin

VERIFY_MODE ?= exact
ATOL ?= 0
RTOL ?= 0

RESULT_SYMBOL ?= root.result
DONE_SYMBOL   ?= root.done

TIMING_WORDS := 15
CLOCK_MHZ ?= 850
TIMER_DIRECTION ?= auto

# ------------------------------------------------------------
# simulation configuration
# ------------------------------------------------------------

SIM_CYCLES ?= 200000
SIM_JSON   ?= 0

# empty by default: host-toolchain binaries (paint, milink, simfabric,
# ...) run natively inside the cerebras-env nix shell. Set
# CONTAINER_BIN=singularity (with SIF/TOOLS_BIND) to reproduce the old
# kingfisher-cluster container path
CONTAINER_BIN ?=
SIF ?= /projects/cerebras/cs_sdk-1.3.0/cbcore_sdk-1.3.0.sif
TOOLS_BIND ?= /projects/cerebras/sandbox/sysroot-zen4:/tools

SIM_ENV = \
--bind $(TOOLS_BIND) \
--env GITTOP=/tools \
--env PREPEND_PATH=/tools/bin

# ------------------------------------------------------------
# hardware configuration
# ------------------------------------------------------------

ifeq ($(origin WSE_JOB),undefined)
WSE_JOB := $(BENCH_NAME)-$(shell date +%Y%m%d_%H%M%S)
endif

WSE_SERVER   ?= http://localhost:8080
WSE_WAFER    ?= xs20863
WSE_WIDTH    ?= $(W)
WSE_HEIGHT   ?= $(H)
WSE_LIFETIME ?= 1000
WSE_WAIT_SECONDS ?= 10
WSE_QUEUE_NONFATAL_RC ?= 1

.PHONY: \
all help check-config print-config FORCE \
input reference build build-run load-input \
sim test test/sim \
wse wse-queue wse-program wse-exec wse-run \
fetch-wse-results test/wse verify-wse wse-collect \
show-symbols show-grid-symbols show-result-shape \
extract-all-text-sim csv-sim csv-wse collect-sim \
force-rebuild clean

all: test

help:
>@echo "GEMV targets:"
>@echo "  make input"
>@echo "  make build"
>@echo "  make build-run"
>@echo "  make test MODE=sim"
>@echo "  make test MODE=wse"
>@echo "  make wse-run"
>@echo "  make fetch-wse-results WSE_JOB=<job>"
>@echo
>@echo "Examples:"
>@echo "  make test MODE=sim W=8 H=8 M=16 N=16"
>@echo "  make build-run W=100 H=100 M=100 N=100"
>@echo "  make build-run W=512 H=512 M=1000 N=1000"

check-config:
>@test "$(W)" -ge 2 || { echo "W must be at least 2"; exit 1; }
>@test "$(H)" -ge 2 || { echo "H must be at least 2"; exit 1; }
>@test "$(M)" -ge 1 || { echo "M must be positive"; exit 1; }
>@test "$(N)" -ge 1 || { echo "N must be positive"; exit 1; }
>@test "$(B)" -eq "$(EXPECTED_B)" || { \
echo "B must equal M=$(EXPECTED_B)"; exit 1; }
>@test "$(K)" -eq "$(EXPECTED_K)" || { \
echo "K must equal ceil(N/(W*H))=$(EXPECTED_K)"; exit 1; }
>@test "$(WAIT_ALPHA)" -ge 0 || { \
echo "WAIT_ALPHA must be nonnegative"; exit 1; }
>@test "$(SX)" -ge 1 || { echo "SX must be positive"; exit 1; }
>@test "$(SY)" -ge 1 || { echo "SY must be positive"; exit 1; }
>@test "$(SX)" -le "$(W)" || { echo "SX must not exceed W"; exit 1; }
>@test "$(SY)" -le "$(H)" || { echo "SY must not exceed H"; exit 1; }


print-config:
>@echo "BENCH_SRC=$(BENCH_SRC)"
>@echo "ARCH=$(ARCH)"
>@echo "MODE=$(MODE)"
>@echo "W=$(W)"
>@echo "H=$(H)"
>@echo "M=$(M)"
>@echo "N=$(N)"
>@echo "B=$(B)"
>@echo "K=$(K)"
>@echo "INPUT_MODE=$(INPUT_MODE)"
>@echo "INPUT_SEED=$(INPUT_SEED)"
>@echo "INPUT_DIR=$(INPUT_DIR)"
>@echo "WAIT_ALPHA=$(WAIT_ALPHA)"
>@echo "PROFILE_STAGES=$(PROFILE_STAGES)"
>@echo "SIM_CYCLES=$(SIM_CYCLES)"
>@echo "WSE_JOB=$(WSE_JOB)"
>@echo "WSE_SERVER=$(WSE_SERVER)"
>@echo "SX=$(SX)"
>@echo "SY=$(SY)"


FORCE:

$(CONFIG_STAMP): FORCE
>@$(MAKE) --no-print-directory check-config
>@{ \
echo "ARCH=$(ARCH)"; \
echo "W=$(W)"; \
echo "H=$(H)"; \
echo "M=$(M)"; \
echo "N=$(N)"; \
echo "B=$(B)"; \
echo "K=$(K)"; \
echo "INPUT_MODE=$(INPUT_MODE)"; \
echo "INPUT_SEED=$(INPUT_SEED)"; \
echo "GENERATE_INPUT=$(GENERATE_INPUT)"; \
echo "WAIT_ALPHA=$(WAIT_ALPHA)"; \
echo "PROFILE_STAGES=$(PROFILE_STAGES)"; \
echo "SX=$(SX)"; \
echo "SY=$(SY)"; \
} > $@.tmp
>@if ! cmp -s $@.tmp $@ 2>/dev/null; then \
mv $@.tmp $@; \
else \
rm -f $@.tmp; \
fi

# ------------------------------------------------------------
# coordinate generation
# ------------------------------------------------------------

$(COORD_STAMP): gen_coords.py $(CONFIG_STAMP)
>python3 gen_coords.py --w $(W) --h $(H)
>touch $@

$(COORD_BINS): $(COORD_STAMP)

# ------------------------------------------------------------
# GEMV input generation
# ------------------------------------------------------------

ifeq ($(GENERATE_INPUT),1)

$(INPUT_STAMP): gen_input.py $(CONFIG_STAMP)
>rm -rf "$(INPUT_DIR)"
>python3 gen_input.py \
--w $(W) \
--h $(H) \
--m $(M) \
--n $(N) \
--mode $(INPUT_MODE) \
--seed $(INPUT_SEED) \
--reduction two-phase \
--sx $(SX) \
--sy $(SY) \
--output-dir "$(INPUT_DIR)"
>@set -eu; \
check_size() { \
file="$$1"; expected="$$2"; \
actual=$$(wc -c < "$$file" | tr -d '[:space:]'); \
if [ "$$actual" -ne "$$expected" ]; then \
echo "$$file: expected $$expected bytes, got $$actual"; \
exit 1; \
fi; \
}; \
check_size "$(MATRIX_GLOBAL_BIN)" \
"$$(( $(M) * $(N) * 4 ))"; \
check_size "$(VECTOR_GLOBAL_BIN)" \
"$$(( $(M) * $(N) * 4 ))"; \
check_size "$(MATRIX_ROOT_BIN)" \
"$$(( $(B) * $(K) * 4 ))"; \
check_size "$(MATRIX_TOP_BIN)" \
"$$(( ($(W) - 1) * $(B) * $(K) * 4 ))"; \
check_size "$(MATRIX_LOWER_BIN)" \
"$$(( ($(H) - 1) * $(W) * $(B) * $(K) * 4 ))"; \
check_size "$(XVEC_ROOT_BIN)" \
"$$(( $(B) * $(K) * 4 ))"; \
check_size "$(XVEC_TOP_BIN)" \
"$$(( ($(W) - 1) * $(B) * $(K) * 4 ))"; \
check_size "$(XVEC_LOWER_BIN)" \
"$$(( ($(H) - 1) * $(W) * $(B) * $(K) * 4 ))"; \
check_size "$(GENERATED_REFERENCE)" \
"4"
>touch $@

else

$(INPUT_STAMP): $(CONFIG_STAMP)
>@for file in \
"$(MATRIX_ROOT_BIN)" \
"$(MATRIX_TOP_BIN)" \
"$(MATRIX_LOWER_BIN)" \
"$(XVEC_ROOT_BIN)" \
"$(XVEC_TOP_BIN)" \
"$(XVEC_LOWER_BIN)" \
"$(GENERATED_REFERENCE)"; do \
test -f "$$file" || { echo "Missing $$file"; exit 1; }; \
done
>touch $@

endif

input: $(INPUT_STAMP) $(REFERENCE_BIN)

$(REFERENCE_BIN): $(INPUT_STAMP)
>cp "$(GENERATED_REFERENCE)" "$@.tmp"
>mv "$@.tmp" "$@"

reference: $(REFERENCE_BIN)

# ------------------------------------------------------------
# paint and image construction
# ------------------------------------------------------------

$(PAINT_STAMP): \
$(BENCH_SRC) $(wildcard *.w) $(wildcard *.paint) \
$(CONFIG_STAMP)
>rm -f \
$(BENCH_OBJ) $(BENCH_MAP) $(BENCH_NOTE) \
$(BENCH_ENTRY) $(BENCH_PS) $(BENCH_REGION) \
$(BENCH_LISTING) $(LINK_STAMP) $(BENCH_IMG) \
$(BENCH_IMG_RUN) $(BENCH_ELF) \
$(BENCH_ELF_CORE) $(BENCH_CORE)
>paint \
arch=$(ARCH) \
source=$(BENCH_SRC) \
image=$(BENCH_OBJ) \
map=$(BENCH_MAP) \
note=$(BENCH_NOTE) \
entrymap=$(BENCH_ENTRY) \
ps=$(BENCH_PS) \
regiondump=$(BENCH_REGION) \
set W=$(W) \
set H=$(H) \
set B=$(B) \
set K=$(K) \
>set SX=$(SX) \
>set SY=$(SY) \
set PROFILE_STAGES=$(PROFILE_STAGES) \
set WAIT_ALPHA=$(WAIT_ALPHA) \
annotate listing=$(BENCH_LISTING)
>touch $@

$(BENCH_OBJ): $(PAINT_STAMP)
$(BENCH_MAP): $(PAINT_STAMP)
$(BENCH_NOTE): $(PAINT_STAMP)
$(BENCH_ENTRY): $(PAINT_STAMP)
$(BENCH_PS): $(PAINT_STAMP)
$(BENCH_REGION): $(PAINT_STAMP)
$(BENCH_LISTING): $(PAINT_STAMP)

$(LINK_STAMP): $(BENCH_OBJ) $(BENCH_MAP) $(BENCH_NOTE)
>milink \
image=$(BENCH_OBJ) \
out=$(BENCH_OBJ) \
map=$(BENCH_MAP) \
note=$(BENCH_NOTE)
>weight \
image=$(BENCH_OBJ) \
map=$(BENCH_MAP) \
note=$(BENCH_NOTE)
>touch $@

$(BENCH_IMG): $(LINK_STAMP)
>cp $(BENCH_OBJ) $(BENCH_IMG)

build: $(BENCH_IMG)

# ------------------------------------------------------------
# install matrix, vector and coordinates into the run image
# ------------------------------------------------------------

$(BENCH_IMG_RUN): \
$(BENCH_IMG) $(BENCH_MAP) $(INPUT_STAMP) $(COORD_BINS)
>cp $(BENCH_IMG) $(BENCH_IMG_RUN)
>miset image=$(BENCH_IMG_RUN) out=$(BENCH_IMG_RUN) \
map=$(BENCH_MAP) symbol=root.matrix \
order="n _word" data=$(MATRIX_ROOT_BIN)
>miset image=$(BENCH_IMG_RUN) out=$(BENCH_IMG_RUN) \
map=$(BENCH_MAP) symbol=worker_top.matrix \
order="x n _word" data=$(MATRIX_TOP_BIN)
>miset image=$(BENCH_IMG_RUN) out=$(BENCH_IMG_RUN) \
map=$(BENCH_MAP) symbol=worker_lower.matrix \
order="y x n _word" data=$(MATRIX_LOWER_BIN)
>miset image=$(BENCH_IMG_RUN) out=$(BENCH_IMG_RUN) \
map=$(BENCH_MAP) symbol=root.xvec \
order="n _word" data=$(XVEC_ROOT_BIN)
>miset image=$(BENCH_IMG_RUN) out=$(BENCH_IMG_RUN) \
map=$(BENCH_MAP) symbol=worker_top.xvec \
order="x n _word" data=$(XVEC_TOP_BIN)
>miset image=$(BENCH_IMG_RUN) out=$(BENCH_IMG_RUN) \
map=$(BENCH_MAP) symbol=worker_lower.xvec \
order="y x n _word" data=$(XVEC_LOWER_BIN)
>miset image=$(BENCH_IMG_RUN) out=$(BENCH_IMG_RUN) \
map=$(BENCH_MAP) symbol=root.coord \
order="k" data=coords-root.bin
>miset image=$(BENCH_IMG_RUN) out=$(BENCH_IMG_RUN) \
map=$(BENCH_MAP) symbol=worker_top.coord \
order="x k" data=coords-top.bin
>miset image=$(BENCH_IMG_RUN) out=$(BENCH_IMG_RUN) \
map=$(BENCH_MAP) symbol=worker_lower.coord \
order="y x k" data=coords-lower.bin

build-run: $(BENCH_IMG_RUN)
load-input: build-run

# ------------------------------------------------------------
# simulation
# ------------------------------------------------------------

$(BENCH_ELF): $(BENCH_IMG_RUN)
>mielf image=$(BENCH_IMG_RUN) elf=$(BENCH_ELF)

$(BENCH_ELF_CORE): $(BENCH_ELF)
>$(if $(CONTAINER_BIN),$(CONTAINER_BIN) exec $(SIM_ENV) $(SIF),) simfabric \
>	elf=$(BENCH_ELF) \
>	core=$(BENCH_ELF_CORE) \
>	json=$(SIM_JSON) \
>	cycles=$(SIM_CYCLES) \
>	> $(BENCH_NAME)-sim.log \
>	2> $(BENCH_NAME)-sim-err.log

$(BENCH_CORE): $(BENCH_ELF_CORE)
>elfmi image=$(BENCH_CORE) elf=$(BENCH_ELF_CORE)

$(SIM_OUTPUT): $(BENCH_CORE) $(BENCH_MAP) collect_dot_result.py
>rm -f "$@" "$@.root" "$@.top" "$@.lower"
>miget image=$(BENCH_CORE) map=$(BENCH_MAP) \
symbol=root.result order="n _word" data="$@.root"
>miget image=$(BENCH_CORE) map=$(BENCH_MAP) \
symbol=worker_top.result order="x n _word" data="$@.top"
>miget image=$(BENCH_CORE) map=$(BENCH_MAP) \
symbol=worker_lower.result order="y x n _word" data="$@.lower"
>python3 collect_dot_result.py \
--w $(W) \
--h $(H) \
--root "$@.root" \
--top "$@.top" \
--lower "$@.lower" \
--output "$@"
>rm -f "$@.root" "$@.top" "$@.lower"

sim: $(SIM_OUTPUT)

test: test/$(MODE)

test/sim: $(REFERENCE_BIN) $(SIM_OUTPUT) timings-sim
>python3 verify.py \
--reference $(REFERENCE_BIN) \
--actual $(SIM_OUTPUT) \
--mode $(VERIFY_MODE) \
--atol $(ATOL) \
--rtol $(RTOL)
>@echo "Simulation CG dot product passed"
>@miget image=$(BENCH_CORE) map=$(BENCH_MAP) \
symbol=$(DONE_SYMBOL) text || true

# ------------------------------------------------------------
# hardware bundle and execution
# ------------------------------------------------------------

bundle.json: FORCE
>@printf '{\n' > $@.tmp
>@printf '  "lifetime": %s,\n' "$(WSE_LIFETIME)" >> $@.tmp
>@printf '  "regions": {\n' >> $@.tmp
>@printf '    "main_compute": {\n' >> $@.tmp
>@printf '      "wafer": "%s",\n' "$(WSE_WAFER)" >> $@.tmp
>@printf '      "width": %s,\n' "$(WSE_WIDTH)" >> $@.tmp
>@printf '      "height": %s,\n' "$(WSE_HEIGHT)" >> $@.tmp
>@printf '      "padding": 0\n' >> $@.tmp
>@printf '    }\n' >> $@.tmp
>@printf '  }\n' >> $@.tmp
>@printf '}\n' >> $@.tmp
>@if ! cmp -s $@.tmp $@ 2>/dev/null; then \
mv $@.tmp $@; \
else \
rm -f $@.tmp; \
fi

wse-queue: bundle.json
>@sleep 2
>@rc=0; \
CSRTSERV="$(WSE_SERVER)" csclient bundle \
-bn "$(WSE_JOB)" \
--queue bundle.json \
-v verbose || rc=$$?; \
nonfatal='$(strip $(WSE_QUEUE_NONFATAL_RC))'; \
[ -n "$$nonfatal" ] || nonfatal=1; \
case "$$rc" in \
0) echo "Bundle queued successfully" ;; \
"$$nonfatal") \
echo "Queue returned nonfatal status $$rc; continuing" ;; \
*) echo "Queue failed with status $$rc"; exit "$$rc" ;; \
esac
>@sleep "$(WSE_WAIT_SECONDS)"

wse-program: $(BENCH_IMG_RUN) $(BENCH_MAP) wse-queue
>sleep 2
>CSRTSERV=$(WSE_SERVER) csclient job \
-bn $(WSE_JOB) -r main_compute wipe
>sleep 2
>CSRTSERV=$(WSE_SERVER) csclient job \
-bn $(WSE_JOB) -r main_compute \
program=$(BENCH_IMG_RUN)

wse-exec: wse-program
>sleep 2
>CSRTSERV=$(WSE_SERVER) csclient job \
-bn $(WSE_JOB) -r main_compute run wait=3

wse-run: wse-exec
>@echo "Hardware CG dot product completed for $(WSE_JOB)"

wse: $(WSE_OUTPUT)

$(WSE_OUTPUT): wse-run $(BENCH_MAP) $(REFERENCE_BIN)
>$(MAKE) --no-print-directory fetch-wse-results \
WSE_JOB="$(WSE_JOB)" \
WSE_SERVER="$(WSE_SERVER)" \
WSE_OUTPUT="$(WSE_OUTPUT)"

fetch-wse-results: $(BENCH_MAP) $(REFERENCE_BIN) collect_dot_result.py
>rm -rf out_hw/result
>mkdir -p out_hw/result
>rm -f "$(WSE_OUTPUT)"
>@set -eu; \
fetch_one() { \
symbol="$$1"; output="$$2"; expected="$$3"; \
tag=$$(printf '%s' "$$symbol" | tr './' '__'); \
dir="out_hw/result/$$tag"; \
zip="out_hw/result/$$tag.zip"; \
mkdir -p "$$dir"; \
rm -f "$$zip"; \
echo "Fetching $$symbol"; \
CSRTSERV="$(WSE_SERVER)" csclient job \
-bn "$(WSE_JOB)" \
-r main_compute \
pause \
fetch="symbol=$$symbol savepath=$$zip map=$(BENCH_MAP)"; \
unzip -oq "$$zip" -d "$$dir"; \
file=$$(find "$$dir" -type f -print -quit); \
test -n "$$file" || { \
echo "No data found for $$symbol"; exit 1; \
}; \
cp "$$file" "$$output"; \
actual=$$(wc -c < "$$output" | tr -d '[:space:]'); \
test "$$actual" -eq "$$expected" || { \
echo "$$symbol: expected $$expected bytes, got $$actual"; \
exit 1; \
}; \
}; \
fetch_one root.result out_hw/result/root.bin "4"; \
fetch_one worker_top.result out_hw/result/top.bin \
"$$(( ($(W) - 1) * 4 ))"; \
fetch_one worker_lower.result out_hw/result/lower.bin \
"$$(( ($(H) - 1) * $(W) * 4 ))"
>python3 collect_dot_result.py \
--w $(W) \
--h $(H) \
--root out_hw/result/root.bin \
--top out_hw/result/top.bin \
--lower out_hw/result/lower.bin \
--output "$(WSE_OUTPUT)"
>@actual=$$(wc -c < "$(WSE_OUTPUT)" | tr -d '[:space:]'); \
test "$$actual" -eq 4 || { \
echo "Result: expected 4 bytes, got $$actual"; exit 1; \
}
>@echo "Created scalar dot-product result $(WSE_OUTPUT)"
>$(MAKE) --no-print-directory fetch-wse-timings \
WSE_JOB="$(WSE_JOB)" WSE_SERVER="$(WSE_SERVER)"

test/wse: $(REFERENCE_BIN) $(WSE_OUTPUT)
>python3 verify.py \
--reference $(REFERENCE_BIN) \
--actual $(WSE_OUTPUT) \
--mode $(VERIFY_MODE) \
--atol $(ATOL) \
--rtol $(RTOL)
>@echo "Hardware CG dot product passed"

verify-wse: $(REFERENCE_BIN)
>@test -f "$(WSE_OUTPUT)" || { \
echo "$(WSE_OUTPUT) does not exist"; exit 1; }
>python3 verify.py \
--reference $(REFERENCE_BIN) \
--actual $(WSE_OUTPUT) \
--mode $(VERIFY_MODE) \
--atol $(ATOL) \
--rtol $(RTOL)

wse-collect: fetch-wse-results


# ------------------------------------------------------------
# five-phase timing collection
# ------------------------------------------------------------

.PHONY: timings-sim fetch-wse-timings timings-wse

timings-sim: $(BENCH_CORE) $(BENCH_MAP) collect_timings.py
>rm -rf out_timing_sim
>mkdir -p out_timing_sim
>miget image=$(BENCH_CORE) map=$(BENCH_MAP) \
symbol=root.phase_timestamps order="n" \
data=out_timing_sim/root.bin
>miget image=$(BENCH_CORE) map=$(BENCH_MAP) \
symbol=worker_top.phase_timestamps order="x n" \
data=out_timing_sim/top.bin
>miget image=$(BENCH_CORE) map=$(BENCH_MAP) \
symbol=worker_lower.phase_timestamps order="y x n" \
data=out_timing_sim/lower.bin
>python3 collect_timings.py \
--w $(W) \
--h $(H) \
--root out_timing_sim/root.bin \
--top out_timing_sim/top.bin \
--lower out_timing_sim/lower.bin \
--summary timings-sim.csv \
--per-pe timings-sim-per-pe.csv \
--clock-mhz $(CLOCK_MHZ) \
--counter-direction $(TIMER_DIRECTION) \
--wait-alpha $(WAIT_ALPHA)

fetch-wse-timings: $(BENCH_MAP) collect_timings.py
>rm -rf out_hw/timing
>mkdir -p out_hw/timing
>@set -eu; \
fetch_one() { \
symbol="$$1"; output="$$2"; expected="$$3"; \
tag=$$(printf '%s' "$$symbol" | tr './' '__'); \
dir="out_hw/timing/$$tag"; \
zip="out_hw/timing/$$tag.zip"; \
mkdir -p "$$dir"; \
rm -f "$$zip"; \
echo "Fetching $$symbol"; \
CSRTSERV="$(WSE_SERVER)" csclient job \
-bn "$(WSE_JOB)" \
-r main_compute \
pause \
fetch="symbol=$$symbol savepath=$$zip map=$(BENCH_MAP)"; \
unzip -oq "$$zip" -d "$$dir"; \
file=$$(find "$$dir" -type f -print -quit); \
test -n "$$file" || { \
echo "No data found for $$symbol"; exit 1; \
}; \
cp "$$file" "$$output"; \
actual=$$(wc -c < "$$output" | tr -d '[:space:]'); \
test "$$actual" -eq "$$expected" || { \
echo "$$symbol: expected $$expected bytes, got $$actual"; \
exit 1; \
}; \
}; \
fetch_one root.phase_timestamps \
out_hw/timing/root.bin \
"$$(( $(TIMING_WORDS) * 2 ))"; \
fetch_one worker_top.phase_timestamps \
out_hw/timing/top.bin \
"$$(( ($(W) - 1) * $(TIMING_WORDS) * 2 ))"; \
fetch_one worker_lower.phase_timestamps \
out_hw/timing/lower.bin \
"$$(( ($(H) - 1) * $(W) * $(TIMING_WORDS) * 2 ))"
>python3 collect_timings.py \
--w $(W) \
--h $(H) \
--root out_hw/timing/root.bin \
--top out_hw/timing/top.bin \
--lower out_hw/timing/lower.bin \
--summary timings-wse.csv \
--per-pe timings-wse-per-pe.csv \
--clock-mhz $(CLOCK_MHZ) \
--counter-direction $(TIMER_DIRECTION) \
--wait-alpha $(WAIT_ALPHA)

timings-wse: fetch-wse-timings


# ------------------------------------------------------------
# inspection and CSV output
# ------------------------------------------------------------

show-symbols: $(BENCH_MAP)
>@awk '/^[A-Za-z0-9_.-]+[[:space:]]+\[/ { print $$1 }' \
$(BENCH_MAP) | sort -u

show-grid-symbols: $(BENCH_MAP)
>@awk '/^grid\./ { print $$1 }' $(BENCH_MAP) | sort -u

show-result-shape: $(BENCH_MAP)
>@grep "^$(RESULT_SYMBOL)" $(BENCH_MAP) || true

extract-all-text-sim: $(BENCH_CORE) $(BENCH_MAP)
>rm -rf out_text_sim
>mkdir -p out_text_sim
>@for symbol in $$(awk \
'/^[A-Za-z0-9_.-]+[[:space:]]+\[/ { print $$1 }' \
$(BENCH_MAP) | sort -u); do \
echo "Extracting $$symbol"; \
miget image=$(BENCH_CORE) map=$(BENCH_MAP) \
symbol=$$symbol text \
> out_text_sim/$$symbol.txt || true; \
done

csv-sim: $(REFERENCE_BIN) $(SIM_OUTPUT)
>python3 results_to_csv.py \
--reference $(REFERENCE_BIN) \
--result $(SIM_OUTPUT) \
--output results-sim.csv

csv-wse: $(REFERENCE_BIN) $(WSE_OUTPUT)
>python3 results_to_csv.py \
--reference $(REFERENCE_BIN) \
--result $(WSE_OUTPUT) \
--output results-wse.csv

collect-sim: test/sim extract-all-text-sim csv-sim
>rm -rf collected-sim
>mkdir -p collected-sim
>$(MAKE) --no-print-directory print-config \
> collected-sim/config.txt
>cp $(REFERENCE_BIN) collected-sim/
>cp $(SIM_OUTPUT) collected-sim/
>cp $(BENCH_MAP) collected-sim/
>cp -r $(INPUT_DIR) collected-sim/
>cp results-sim.csv collected-sim/
>cp -r out_text_sim collected-sim/

# ------------------------------------------------------------
# cleanup
# ------------------------------------------------------------

force-rebuild:
>rm -f \
$(CONFIG_STAMP) $(PAINT_STAMP) $(LINK_STAMP) \
$(COORD_STAMP) $(INPUT_STAMP) \
$(BENCH_OBJ) $(BENCH_IMG) $(BENCH_IMG_RUN) \
$(BENCH_MAP) $(BENCH_NOTE) $(BENCH_ENTRY) \
$(BENCH_PS) $(BENCH_REGION) $(BENCH_LISTING) \
$(BENCH_ELF) $(BENCH_ELF_CORE) $(BENCH_CORE) \
$(REFERENCE_BIN) $(SIM_OUTPUT) $(WSE_OUTPUT) \
bundle.json

clean: force-rebuild
>rm -rf \
$(INPUT_DIR) \
out_img out_sim out_text_img out_text_sim \
out_grid_text_img out_grid_text_sim \
out_hw out_timing_sim collected-sim
>rm -f \
coords-root.bin coords-top.bin coords-lower.bin \
results-sim.csv results-wse.csv \
timings-sim.csv timings-sim-per-pe.csv \
timings-wse.csv timings-wse-per-pe.csv \
+timings-sim-extrema.csv timings-wse-extrema.csv \
$(BENCH_NAME)-sim.log $(BENCH_NAME)-sim-err.log \
input.bin input-root.bin input-top.bin input-lower.bin
