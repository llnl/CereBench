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

CONFIG_STAMP  := .build-config
PAINT_STAMP   := .paint-stamp
LINK_STAMP    := .build-linked

COORD_BINS := coords-root.bin coords-top.bin coords-lower.bin
COORD_STAMP := .coords-stamp

INPUT_ROOT_BIN  := input-root.bin
INPUT_TOP_BIN   := input-top.bin
INPUT_LOWER_BIN := input-lower.bin
INPUT_PARTS_STAMP := .input-parts

MODE ?= sim
ARCH ?= sdr

# ------------------------------------------------------------
# AllReduce parameters
# ------------------------------------------------------------

W ?= 8
H ?= 8
B ?= 16

# Paper choice: group size approximately sqrt(dimension).
SX ?= $(shell python3 -c 'import math; print(max(1,int(math.sqrt($(W)) + 0.5)))')
SY ?= $(shell python3 -c 'import math; print(max(1,int(math.sqrt($(H)) + 0.5)))')

INPUT_BIN  ?= input.bin
INPUT_MODE ?= pattern
INPUT_SEED ?= 1

# Set to zero to provide INPUT_BIN yourself.
GENERATE_INPUT ?= 1

INPUT_SYMBOL  ?= root.value
RESULT_SYMBOL ?= root.result
DONE_SYMBOL   ?= root.done

INPUT_ORDER  ?= y x n _word
RESULT_ORDER ?= n _word

REFERENCE_BIN ?= out-ref.bin
SIM_OUTPUT    ?= out-sim.bin
WSE_OUTPUT    ?= out-wse.bin

VERIFY_MODE ?= exact
ATOL ?= 0
RTOL ?= 0

$(COORD_STAMP): gen_coords.py $(CONFIG_STAMP)
	python3 gen_coords.py --w $(W) --h $(H)
	touch $@

$(COORD_BINS): $(COORD_STAMP)

# ------------------------------------------------------------
# Simulation
# ------------------------------------------------------------

SIM_CYCLES ?= 50000
SIM_JSON   ?= 0

CONTAINER_BIN ?= singularity
SIF ?= /projects/cerebras/cs_sdk-1.3.0/cbcore_sdk-1.3.0.sif
TOOLS_BIND ?= /projects/cerebras/sandbox/sysroot-zen4:/tools

SIM_ENV = \
	--bind $(TOOLS_BIND) \
	--env GITTOP=/tools \
	--env PREPEND_PATH=/tools/bin

# ------------------------------------------------------------
# Hardware
# ------------------------------------------------------------

ifeq ($(origin WSE_JOB),undefined)
WSE_JOB := $(BENCH_NAME)-run-$(shell date +%Y%m%d_%H%M%S)
endif

WSE_SERVER   ?= http://localhost:8080
WSE_WAFER    ?= xs20863
WSE_WIDTH    ?= $(W)
WSE_HEIGHT   ?= $(H)
WSE_X        ?= 100
WSE_Y        ?= 100
WSE_LIFETIME ?= 1000
WSE_WAIT_SECONDS ?= 10
WAIT_ALPHA ?= 1

FETCH_SYMBOL ?= $(RESULT_SYMBOL)

# These are the symbols currently exported by xy_two_phase.w.
WSE_FETCH_SYMBOLS ?= \
	root.result \
	worker_top.result \
	worker_lower.result \
	root.tsc_buffer \
	worker_top.tsc_buffer \
	worker_lower.tsc_buffer

.PHONY: all help build build-run input load-input sim wse test \
	test/sim test/wse check-config print-config show-symbols \
	show-grid-symbols show-result-shape extract-all-img \
	extract-all-sim extract-all-text-img extract-all-text-sim \
	extract-grid-text-img extract-grid-text-sim csv-sim csv-wse \
	collect-sim wse-queue wse-program wse-exec wse-run \
	wse-collect fetch-wse-symbols clean force-rebuild FORCE \
	reference verify-wse fetch-wse-results

all: test

help:
	@echo "Build and execution targets:"
	@echo "  make build"
	@echo "  make build-run"
	@echo "  make input"
	@echo "  make sim"
	@echo "  make test MODE=sim"
	@echo "  make test MODE=wse WSE_SERVER=<server>"
	@echo
	@echo "Inspection targets:"
	@echo "  make print-config"
	@echo "  make show-symbols"
	@echo "  make show-grid-symbols"
	@echo "  make show-result-shape"
	@echo "  make extract-all-text-sim"
	@echo "  make collect-sim"
	@echo "  make csv-sim"
	@echo
	@echo "Hardware targets:"
	@echo "  make wse-run"
	@echo "  make wse-collect"
	@echo "  make fetch-wse-symbols WSE_JOB=<existing-job>"
	@echo
	@echo "Examples:"
	@echo "  make test MODE=sim W=8 H=8 B=32 SX=3 SY=3"
	@echo "  make test MODE=sim W=5 H=7 B=8 SX=2 SY=3"
	@echo "  make test MODE=wse W=8 H=8 B=32 WSE_SERVER=http://host:8080"

check-config:
	@test "$(W)" -ge 2 || { echo "W must be at least 2"; exit 1; }
	@test "$(H)" -ge 2 || { echo "H must be at least 2"; exit 1; }
	@test "$(B)" -ge 1 || { echo "B must be positive"; exit 1; }
	@test "$(SX)" -ge 1 || { echo "SX must be positive"; exit 1; }
	@test "$(SY)" -ge 1 || { echo "SY must be positive"; exit 1; }
	@test "$(SX)" -le "$(W)" || { echo "SX must not exceed W"; exit 1; }
	@test "$(SY)" -le "$(H)" || { echo "SY must not exceed H"; exit 1; }
	@test "$(WAIT_ALPHA)" -ge 0 || { echo "WAIT_ALPHA must be positive"; exit 1; }

print-config:
	@echo "BENCH_SRC=$(BENCH_SRC)"
	@echo "ARCH=$(ARCH)"
	@echo "MODE=$(MODE)"
	@echo "W=$(W)"
	@echo "H=$(H)"
	@echo "B=$(B)"
	@echo "SX=$(SX)"
	@echo "SY=$(SY)"
	@echo "INPUT_BIN=$(INPUT_BIN)"
	@echo "INPUT_MODE=$(INPUT_MODE)"
	@echo "INPUT_SEED=$(INPUT_SEED)"
	@echo "GENERATE_INPUT=$(GENERATE_INPUT)"
	@echo "SIM_CYCLES=$(SIM_CYCLES)"
	@echo "WSE_JOB=$(WSE_JOB)"
	@echo "WSE_SERVER=$(WSE_SERVER)"
	@echo "WSE_WAFER=$(WSE_WAFER)"
	@echo "WSE_WIDTH=$(WSE_WIDTH)"
	@echo "WSE_HEIGHT=$(WSE_HEIGHT)"
	@echo "WSE_X=$(WSE_X)"
	@echo "WSE_Y=$(WSE_Y)"
	@echo "WAIT_ALPHA=$(WAIT_ALPHA)"

FORCE:

$(CONFIG_STAMP): FORCE
	@$(MAKE) --no-print-directory check-config
	@{ \
		echo "ARCH=$(ARCH)"; \
		echo "W=$(W)"; \
		echo "H=$(H)"; \
		echo "B=$(B)"; \
		echo "SX=$(SX)"; \
		echo "SY=$(SY)"; \
		echo "INPUT_MODE=$(INPUT_MODE)"; \
		echo "INPUT_SEED=$(INPUT_SEED)"; \
		echo "GENERATE_INPUT=$(GENERATE_INPUT)"; \
		echo "WAIT_ALPHA=$(WAIT_ALPHA)"; \
	} > $@.tmp
	@if ! cmp -s $@.tmp $@ 2>/dev/null; then \
		mv $@.tmp $@; \
	else \
		rm -f $@.tmp; \
	fi

# ------------------------------------------------------------
# Input and reference generation
# ------------------------------------------------------------

ifeq ($(GENERATE_INPUT),1)

$(INPUT_BIN): gen_input.py $(CONFIG_STAMP)
	python3 gen_input.py \
		--w $(W) \
		--h $(H) \
		--b $(B) \
		--mode $(INPUT_MODE) \
		--seed $(INPUT_SEED) \
		--output $@

else

$(INPUT_BIN):
	@test -f "$@" || { \
		echo "GENERATE_INPUT=0, but $@ does not exist"; \
		exit 1; \
	}

endif

input: $(INPUT_BIN)

$(REFERENCE_BIN): ref.py $(INPUT_BIN) $(CONFIG_STAMP)
	rm -f $@.tmp

	python3 ref.py \
		--w $(W) \
		--h $(H) \
		--b $(B) \
		--input $(INPUT_BIN) \
		--output $@.tmp

	@expected=$$(( $(W) * $(H) * $(B) * 4 )); \
	actual=$$(wc -c < "$@.tmp" | tr -d '[:space:]'); \
	if [ "$$actual" -ne "$$expected" ]; then \
		echo "Reference size mismatch: expected $$expected bytes, got $$actual"; \
		rm -f "$@.tmp"; \
		exit 1; \
	fi

	mv $@.tmp $@

reference: $(REFERENCE_BIN)

$(INPUT_PARTS_STAMP): split_input.py $(INPUT_BIN) $(CONFIG_STAMP)
	python3 split_input.py \
		--w $(W) \
		--h $(H) \
		--b $(B) \
		--input $(INPUT_BIN) \
		--root $(INPUT_ROOT_BIN) \
		--top $(INPUT_TOP_BIN) \
		--lower $(INPUT_LOWER_BIN)
	touch $@

# ------------------------------------------------------------
# Paint and image construction
# ------------------------------------------------------------

$(PAINT_STAMP): $(BENCH_SRC) $(wildcard *.w) $(wildcard *.paint) $(CONFIG_STAMP)
	rm -f \
		$(BENCH_OBJ) $(BENCH_MAP) $(BENCH_NOTE) \
		$(BENCH_ENTRY) $(BENCH_PS) $(BENCH_REGION) \
		$(BENCH_LISTING) $(LINK_STAMP) $(BENCH_IMG) \
		$(BENCH_IMG_RUN) $(BENCH_ELF) $(BENCH_ELF_CORE) \
		$(BENCH_CORE)

	paint \
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
		set SX=$(SX) \
		set SY=$(SY) \
		set WAIT_ALPHA=$(WAIT_ALPHA) \
		annotate listing=$(BENCH_LISTING)

	touch $@

$(BENCH_OBJ): $(PAINT_STAMP)
$(BENCH_MAP): $(PAINT_STAMP)
$(BENCH_NOTE): $(PAINT_STAMP)
$(BENCH_ENTRY): $(PAINT_STAMP)
$(BENCH_PS): $(PAINT_STAMP)
$(BENCH_REGION): $(PAINT_STAMP)
$(BENCH_LISTING): $(PAINT_STAMP)

$(LINK_STAMP): $(BENCH_OBJ) $(BENCH_MAP) $(BENCH_NOTE)
	milink \
		image=$(BENCH_OBJ) \
		out=$(BENCH_OBJ) \
		map=$(BENCH_MAP) \
		note=$(BENCH_NOTE)

	weight \
		image=$(BENCH_OBJ) \
		map=$(BENCH_MAP) \
		note=$(BENCH_NOTE)

	touch $@

$(BENCH_IMG): $(LINK_STAMP)
	cp $(BENCH_OBJ) $(BENCH_IMG)

build: $(BENCH_IMG)

$(BENCH_IMG_RUN): $(BENCH_IMG) $(BENCH_MAP) $(INPUT_PARTS_STAMP) $(COORD_BINS)
	cp $(BENCH_IMG) $(BENCH_IMG_RUN)

	miset \
		image=$(BENCH_IMG_RUN) \
		out=$(BENCH_IMG_RUN) \
		map=$(BENCH_MAP) \
		symbol=root.value \
		order="n _word" \
		data=$(INPUT_ROOT_BIN)

	miset \
		image=$(BENCH_IMG_RUN) \
		out=$(BENCH_IMG_RUN) \
		map=$(BENCH_MAP) \
		symbol=worker_top.value \
		order="x n _word" \
		data=$(INPUT_TOP_BIN)

	miset \
		image=$(BENCH_IMG_RUN) \
		out=$(BENCH_IMG_RUN) \
		map=$(BENCH_MAP) \
		symbol=worker_lower.value \
		order="y x n _word" \
		data=$(INPUT_LOWER_BIN)
		miset image=$(BENCH_IMG_RUN) out=$(BENCH_IMG_RUN) \
		map=$(BENCH_MAP) symbol=root.coord \
		order="k" data=coords-root.bin

	miset image=$(BENCH_IMG_RUN) out=$(BENCH_IMG_RUN) \
		map=$(BENCH_MAP) symbol=worker_top.coord \
		order="x k" data=coords-top.bin

	miset image=$(BENCH_IMG_RUN) out=$(BENCH_IMG_RUN) \
		map=$(BENCH_MAP) symbol=worker_lower.coord \
		order="y x k" data=coords-lower.bin

build-run: $(BENCH_IMG_RUN)
load-input: $(BENCH_IMG_RUN)

# ------------------------------------------------------------
# Simulation
# ------------------------------------------------------------

$(BENCH_ELF): $(BENCH_IMG_RUN)
	mielf image=$(BENCH_IMG_RUN) elf=$(BENCH_ELF)

$(BENCH_ELF_CORE): $(BENCH_ELF)
	$(if $(CONTAINER_BIN),$(CONTAINER_BIN) exec $(SIM_ENV) $(SIF),) simfabric \
		elf=$(BENCH_ELF) \
		core=$(BENCH_ELF_CORE) \
		json=$(SIM_JSON) \
		cycles=$(SIM_CYCLES) \
		> $(BENCH_NAME)-sim.log \
		2> $(BENCH_NAME)-sim-err.log

$(BENCH_CORE): $(BENCH_ELF_CORE)
	elfmi image=$(BENCH_CORE) elf=$(BENCH_ELF_CORE)

$(SIM_OUTPUT): $(BENCH_CORE) $(BENCH_MAP)
	rm -f $@ $@.root $@.top $@.lower

	miget image=$(BENCH_CORE) map=$(BENCH_MAP) \
		symbol=root.result \
		order="n _word" \
		data=$@.root

	miget image=$(BENCH_CORE) map=$(BENCH_MAP) \
		symbol=worker_top.result \
		order="x n _word" \
		data=$@.top

	miget image=$(BENCH_CORE) map=$(BENCH_MAP) \
		symbol=worker_lower.result \
		order="y x n _word" \
		data=$@.lower

	cat $@.root $@.top $@.lower > $@
	rm -f $@.root $@.top $@.lower

sim: $(BENCH_CORE)

test: test/$(MODE)

test/sim: $(REFERENCE_BIN) $(SIM_OUTPUT)
	python3 verify.py \
		--reference $(REFERENCE_BIN) \
		--actual $(SIM_OUTPUT) \
		--mode $(VERIFY_MODE) \
		--atol $(ATOL) \
		--rtol $(RTOL)

	@echo "Simulation AllReduce passed"
	@miget \
		image=$(BENCH_CORE) \
		map=$(BENCH_MAP) \
		symbol=$(DONE_SYMBOL) \
		text || true

# ------------------------------------------------------------
# Hardware bundle and execution
# ------------------------------------------------------------

bundle.json: FORCE
	@printf '{\n' > $@.tmp
	@printf '  "lifetime": %s,\n' "$(WSE_LIFETIME)" >> $@.tmp
	@printf '  "regions": {\n' >> $@.tmp
	@printf '    "main_compute": {\n' >> $@.tmp
	@printf '      "wafer": "%s",\n' "$(WSE_WAFER)" >> $@.tmp
	@printf '      "width": %s,\n' "$(WSE_WIDTH)" >> $@.tmp
	@printf '      "height": %s,\n' "$(WSE_HEIGHT)" >> $@.tmp
	@printf '      "padding": 0\n' >> $@.tmp
	#@printf '      "x": %s,\n' "$(WSE_X)" >> $@.tmp
	#@printf '      "y": %s\n' "$(WSE_Y)" >> $@.tmp
	@printf '    }\n' >> $@.tmp
	@printf '  }\n' >> $@.tmp
	@printf '}\n' >> $@.tmp
	@if ! cmp -s $@.tmp $@ 2>/dev/null; then \
		mv $@.tmp $@; \
	else \
		rm -f $@.tmp; \
	fi

WSE_QUEUE_NONFATAL_RC ?= 1

wse-queue: bundle.json
	@sleep 2
	@rc=0; \
	CSRTSERV="$(WSE_SERVER)" csclient bundle \
		-bn "$(WSE_JOB)" \
		--queue bundle.json \
		-v verbose || rc=$$?; \
	nonfatal='$(strip $(WSE_QUEUE_NONFATAL_RC))'; \
	[ -n "$$nonfatal" ] || nonfatal=1; \
	case "$$rc" in \
		0) \
			echo "Bundle queued successfully"; \
			;; \
		"$$nonfatal") \
			echo "Queue returned nonfatal status $$rc; continuing"; \
			;; \
		*) \
			echo "Queue submission failed with status $$rc"; \
			exit "$$rc"; \
			;; \
	esac
	@sleep "$(WSE_WAIT_SECONDS)"

wse-program: $(BENCH_IMG_RUN) $(BENCH_MAP) wse-queue
	sleep 2
	CSRTSERV=$(WSE_SERVER) csclient job \
		-bn $(WSE_JOB) \
		-r main_compute \
		wipe

	sleep 2
	CSRTSERV=$(WSE_SERVER) csclient job \
		-bn $(WSE_JOB) \
		-r main_compute \
		program=$(BENCH_IMG_RUN)

wse-exec: wse-program
	sleep 2
	CSRTSERV=$(WSE_SERVER) csclient job \
		-bn $(WSE_JOB) \
		-r main_compute \
		run wait=3

wse-run: wse-exec
	@echo "Hardware execution completed for $(WSE_JOB)"


wse: $(WSE_OUTPUT)

$(WSE_OUTPUT): wse-run $(BENCH_MAP)
	$(MAKE) --no-print-directory fetch-wse-results \
		WSE_JOB="$(WSE_JOB)" \
		WSE_SERVER="$(WSE_SERVER)" \
		WSE_OUTPUT="$(WSE_OUTPUT)"

fetch-wse-results: $(BENCH_MAP) $(REFERENCE_BIN)
	rm -rf out_hw/result
	mkdir -p out_hw/result
	rm -f "$(WSE_OUTPUT)" "$(WSE_OUTPUT).tmp"

	@set -eu; \
	fetch_one() { \
		symbol="$$1"; \
		output="$$2"; \
		expected="$$3"; \
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
		if [ -z "$$file" ]; then \
			echo "No data found for $$symbol"; \
			exit 1; \
		fi; \
		cp "$$file" "$$output"; \
		actual=$$(wc -c < "$$output" | tr -d '[:space:]'); \
		if [ "$$actual" -ne "$$expected" ]; then \
			echo "$$symbol size mismatch: expected $$expected bytes, got $$actual"; \
			exit 1; \
		fi; \
	}; \
	fetch_one \
		"root.result" \
		"out_hw/result/root.bin" \
		"$$(( $(B) * 4 ))"; \
	fetch_one \
		"worker_top.result" \
		"out_hw/result/top.bin" \
		"$$(( ($(W) - 1) * $(B) * 4 ))"; \
	fetch_one \
		"worker_lower.result" \
		"out_hw/result/lower.bin" \
		"$$(( $(W) * ($(H) - 1) * $(B) * 4 ))"; \
	cat \
		out_hw/result/root.bin \
		out_hw/result/top.bin \
		out_hw/result/lower.bin \
		> "$(WSE_OUTPUT).tmp"; \
	expected="$$(( $(W) * $(H) * $(B) * 4 ))"; \
	actual=$$(wc -c < "$(WSE_OUTPUT).tmp" | tr -d '[:space:]'); \
	if [ "$$actual" -ne "$$expected" ]; then \
		echo "Combined result size mismatch: expected $$expected bytes, got $$actual"; \
		exit 1; \
	fi; \
	mv "$(WSE_OUTPUT).tmp" "$(WSE_OUTPUT)"; \
	rm -f out_hw/result/*.zip; \
	echo "Created $(WSE_OUTPUT), $$actual bytes"

test/wse: $(REFERENCE_BIN) $(WSE_OUTPUT)
	python3 verify.py \
		--reference $(REFERENCE_BIN) \
		--actual $(WSE_OUTPUT) \
		--mode $(VERIFY_MODE) \
		--atol $(ATOL) \
		--rtol $(RTOL)

	@echo "Hardware AllReduce passed"

# Verify an already-fetched hardware result without launching another job.
verify-wse: $(REFERENCE_BIN)
	@test -f "$(WSE_OUTPUT)" || { \
		echo "$(WSE_OUTPUT) does not exist"; \
		exit 1; \
	}

	@expected=$$(( $(W) * $(H) * $(B) * 4 )); \
	for file in "$(REFERENCE_BIN)" "$(WSE_OUTPUT)"; do \
		actual=$$(wc -c < "$$file" | tr -d '[:space:]'); \
		if [ "$$actual" -ne "$$expected" ]; then \
			echo "$$file: expected $$expected bytes, got $$actual"; \
			exit 1; \
		fi; \
	done

	python3 verify.py \
		--reference $(REFERENCE_BIN) \
		--actual $(WSE_OUTPUT) \
		--mode $(VERIFY_MODE) \
		--atol $(ATOL) \
		--rtol $(RTOL)

wse-collect: wse-run
	$(MAKE) --no-print-directory fetch-wse-symbols \
		WSE_JOB="$(WSE_JOB)" \
		WSE_SERVER="$(WSE_SERVER)"

# ------------------------------------------------------------
# Symbol inspection and extraction
# ------------------------------------------------------------

show-symbols: $(BENCH_MAP)
	@awk '/^[A-Za-z0-9_.-]+[[:space:]]+\[/ { print $$1 }' \
		$(BENCH_MAP) | sort -u

show-grid-symbols: $(BENCH_MAP)
	@awk '/^grid\./ { print $$1 }' $(BENCH_MAP) | sort -u

show-result-shape: $(BENCH_MAP)
	@grep "^$(RESULT_SYMBOL)" $(BENCH_MAP) || true

extract-all-img: $(BENCH_IMG_RUN) $(BENCH_MAP)
	rm -rf out_img
	mkdir -p out_img
	@for s in $$(awk \
		'/^[A-Za-z0-9_.-]+[[:space:]]+\[/ { print $$1 }' \
		$(BENCH_MAP) | sort -u); do \
		echo "Extracting $$s"; \
		miget image=$(BENCH_IMG_RUN) map=$(BENCH_MAP) \
			symbol=$$s data=out_img/$$s.bin || true; \
	done

extract-all-sim: $(BENCH_CORE) $(BENCH_MAP)
	rm -rf out_sim
	mkdir -p out_sim
	@for s in $$(awk \
		'/^[A-Za-z0-9_.-]+[[:space:]]+\[/ { print $$1 }' \
		$(BENCH_MAP) | sort -u); do \
		echo "Extracting $$s"; \
		miget image=$(BENCH_CORE) map=$(BENCH_MAP) \
			symbol=$$s data=out_sim/$$s.bin || true; \
	done

extract-all-text-img: $(BENCH_IMG_RUN) $(BENCH_MAP)
	rm -rf out_text_img
	mkdir -p out_text_img
	@for s in $$(awk \
		'/^[A-Za-z0-9_.-]+[[:space:]]+\[/ { print $$1 }' \
		$(BENCH_MAP) | sort -u); do \
		echo "Extracting $$s"; \
		miget image=$(BENCH_IMG_RUN) map=$(BENCH_MAP) \
			symbol=$$s text > out_text_img/$$s.txt || true; \
	done

extract-all-text-sim: $(BENCH_CORE) $(BENCH_MAP)
	rm -rf out_text_sim
	mkdir -p out_text_sim
	@for s in $$(awk \
		'/^[A-Za-z0-9_.-]+[[:space:]]+\[/ { print $$1 }' \
		$(BENCH_MAP) | sort -u); do \
		echo "Extracting $$s"; \
		miget image=$(BENCH_CORE) map=$(BENCH_MAP) \
			symbol=$$s text > out_text_sim/$$s.txt || true; \
	done

extract-grid-text-img: $(BENCH_IMG_RUN) $(BENCH_MAP)
	rm -rf out_grid_text_img
	mkdir -p out_grid_text_img
	@for s in $$(awk '/^grid\./ { print $$1 }' \
		$(BENCH_MAP) | sort -u); do \
		miget image=$(BENCH_IMG_RUN) map=$(BENCH_MAP) \
			symbol=$$s text > out_grid_text_img/$$s.txt || true; \
	done

extract-grid-text-sim: $(BENCH_CORE) $(BENCH_MAP)
	rm -rf out_grid_text_sim
	mkdir -p out_grid_text_sim
	@for s in $$(awk '/^grid\./ { print $$1 }' \
		$(BENCH_MAP) | sort -u); do \
		miget image=$(BENCH_CORE) map=$(BENCH_MAP) \
			symbol=$$s text > out_grid_text_sim/$$s.txt || true; \
	done

# ------------------------------------------------------------
# CSV and result collection
# ------------------------------------------------------------

csv-sim: $(INPUT_BIN) $(REFERENCE_BIN) $(SIM_OUTPUT)
	python3 results_to_csv.py \
		--w $(W) \
		--h $(H) \
		--b $(B) \
		--input $(INPUT_BIN) \
		--reference $(REFERENCE_BIN) \
		--result $(SIM_OUTPUT) \
		--output results-sim.csv

csv-wse: $(INPUT_BIN) $(REFERENCE_BIN) $(WSE_OUTPUT)
	python3 results_to_csv.py \
		--w $(W) \
		--h $(H) \
		--b $(B) \
		--input $(INPUT_BIN) \
		--reference $(REFERENCE_BIN) \
		--result $(WSE_OUTPUT) \
		--output results-wse.csv

collect-sim: test/sim extract-all-text-sim csv-sim
	rm -rf collected-sim
	mkdir -p collected-sim
	$(MAKE) --no-print-directory print-config > collected-sim/config.txt
	cp $(INPUT_BIN) collected-sim/
	cp $(REFERENCE_BIN) collected-sim/
	cp $(SIM_OUTPUT) collected-sim/
	cp $(BENCH_MAP) collected-sim/
	cp $(BENCH_NAME)-sim.log collected-sim/ 2>/dev/null || true
	cp $(BENCH_NAME)-sim-err.log collected-sim/ 2>/dev/null || true
	cp results-sim.csv collected-sim/
	cp -r out_text_sim collected-sim/

# ------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------

force-rebuild:
	rm -f \
		$(CONFIG_STAMP) $(PAINT_STAMP) $(LINK_STAMP) \
		$(BENCH_OBJ) $(BENCH_IMG) $(BENCH_IMG_RUN) \
		$(BENCH_MAP) $(BENCH_NOTE) $(BENCH_ENTRY) \
		$(BENCH_PS) $(BENCH_REGION) $(BENCH_LISTING) \
		$(BENCH_ELF) $(BENCH_ELF_CORE) $(BENCH_CORE) \
		$(REFERENCE_BIN) $(SIM_OUTPUT) $(WSE_OUTPUT) \
		bundle.json result*.zip

clean: force-rebuild
	rm -rf \
		out_img out_sim out_text_img out_text_sim \
		out_grid_text_img out_grid_text_sim \
		out_hw collected-sim
	rm -f \
		results-sim.csv results-wse.csv \
		$(BENCH_NAME)-sim.log $(BENCH_NAME)-sim-err.log
	rm -f \
	.input-parts \
	input-root.bin input-top.bin input-lower.bin
ifeq ($(GENERATE_INPUT),1)
	rm -f $(INPUT_BIN)
endif
