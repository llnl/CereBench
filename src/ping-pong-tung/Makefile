BENCH_NAME := latency-test
BENCH_SRC  := $(BENCH_NAME).paint

BENCH_OBJ      := $(BENCH_NAME).obj
BENCH_IMG      := $(BENCH_NAME).img
BENCH_MAP      := $(BENCH_NAME).map
BENCH_NOTE     := $(BENCH_NAME).note
BENCH_ENTRY    := $(BENCH_NAME).entry
BENCH_PS       := $(BENCH_NAME).ps
BENCH_REGION   := $(BENCH_NAME)-region.json
BENCH_LISTING  := $(BENCH_NAME)-listing.json

BENCH_ELF      := $(BENCH_NAME).elf
BENCH_ELF_CORE := $(BENCH_NAME).elf-core
BENCH_CORE     := $(BENCH_NAME).core

MODE ?= sim
ARCH ?= sdr

tensor_size ?= 1
DIST ?= 0
NUM_MSGS ?= 1

SIM_CYCLES ?= 20000
SIM_JSON ?= 0

FETCH_SYMBOL ?= west.a

WSE_JOB      ?= $(BENCH_NAME)-run-$(shell date +%Y%m%d_%H%M%S)
WSE_SERVER   ?= http://localhost:8080
WSE_WAFER    ?= xs20863
WSE_WIDTH    ?= 10
WSE_HEIGHT   ?= 10
WSE_LIFETIME ?= 600

# empty by default: host-toolchain binaries (paint, milink, simfabric,
# ...) run natively inside the cerebras-env nix shell. Set
# CONTAINER_BIN=singularity (with SIF/TOOLS_BIND) to reproduce the old
# kingfisher-cluster container path
CONTAINER_BIN ?=
SIF ?= /projects/cerebras/cs_sdk-1.3.0/cbcore_sdk-1.3.0.sif
TOOLS_BIND ?= /projects/cerebras/sandbox/sysroot-zen4:/tools

SIM_ENV = --bind $(TOOLS_BIND) --env GITTOP=/tools --env PREPEND_PATH=/tools/bin

MAP_SYMS := $(shell awk '/^[A-Za-z0-9_.-]+[[:space:]]+\[/ { print $$1 }' $(BENCH_MAP) 2>/dev/null | sed 's/[[:space:]]*$$//' | sort -u)
DATA_SYMS := $(shell awk '/^(west|east)\.a[[:space:]]+\[/ { print $$1 }' $(BENCH_MAP) 2>/dev/null | sort -u)

.PHONY: all help build sim wse wse-run test clean \
        show-symbols extract-all extract-all-text-img extract-all-text-sim \
        extract-data-text-img extract-data-text-sim

all: test

help:
	@echo "Targets:"
	@echo "  make build"
	@echo "  make sim"
	@echo "  make wse WSE_JOB=<unique-name>"
	@echo "  make test MODE=sim"
	@echo "  make test MODE=wse WSE_JOB=<unique-name>"
	@echo "  make show-symbols"
	@echo "  make extract-all"
	@echo "  make extract-all-text-img"
	@echo "  make extract-all-text-sim"
	@echo "  make extract-data-text-img"
	@echo "  make extract-data-text-sim"
	@echo "  make clean"
	@echo
	@echo "Common overrides:"
	@echo "  FETCH_SYMBOL=west.a"
	@echo "  WSE_JOB=$(BENCH_NAME)-run-$$(date +%s)"
	@echo "  WSE_SERVER=http://IP:PORT"

build: $(BENCH_IMG)

sim: out-sim.bin

wse: out-wse.bin

test: test/$(MODE)

test/sim: out-ref.bin out-sim.bin
	cmp $^

test/wse: out-ref.bin out-wse.bin
	cmp $^

clean:
	rm -f $(BENCH_OBJ) $(BENCH_IMG) $(BENCH_MAP) $(BENCH_NOTE) \
	      $(BENCH_ENTRY) $(BENCH_PS) $(BENCH_REGION) $(BENCH_LISTING) \
	      $(BENCH_ELF) $(BENCH_ELF_CORE) $(BENCH_CORE) \
	      $(BENCH_NAME)-sim.log $(BENCH_NAME)-sim-err.log \
	      out-ref.bin out-sim.bin out-wse.bin result.zip bundle.json \
	      .build-linked
	rm -rf out_hw out_map out_text_img out_text_sim out_data_text_img out_data_text_sim

show-symbols: $(BENCH_MAP)
	@echo "Symbols in $(BENCH_MAP):"
	@awk '/^[A-Za-z0-9_.-]+[[:space:]]+\[/ { print $$1 }' $(BENCH_MAP) | sort -u

$(BENCH_OBJ) $(BENCH_MAP) $(BENCH_NOTE) $(BENCH_ENTRY) $(BENCH_PS) $(BENCH_REGION) $(BENCH_LISTING): $(BENCH_SRC) $(wildcard *.w)
	paint \
		arch=$(ARCH) \
		source=$(BENCH_SRC) \
		image=$(BENCH_OBJ) \
		map=$(BENCH_MAP) \
		note=$(BENCH_NOTE) \
		entrymap=$(BENCH_ENTRY) \
		ps=$(BENCH_PS) \
		regiondump=$(BENCH_REGION) \
		set tensor_size=$(tensor_size) \
		set DIST=$(DIST) \
		set NUM_MSGS=$(NUM_MSGS) \
		annotate listing=$(BENCH_LISTING)

.build-linked: $(BENCH_OBJ) $(BENCH_MAP) $(BENCH_NOTE)
	milink image=$(BENCH_OBJ) out=$(BENCH_OBJ) map=$(BENCH_MAP) note=$(BENCH_NOTE)
	weight image=$(BENCH_OBJ) map=$(BENCH_MAP) note=$(BENCH_NOTE)
	touch $@

$(BENCH_IMG): .build-linked
	cp $(BENCH_OBJ) $(BENCH_IMG)

$(BENCH_ELF): $(BENCH_IMG)
	mielf image=$(BENCH_IMG) elf=$(BENCH_ELF)

$(BENCH_ELF_CORE): $(BENCH_ELF)
	$(if $(CONTAINER_BIN),$(CONTAINER_BIN) exec $(SIM_ENV) $(SIF),) simfabric \
		elf=$(BENCH_ELF) \
		core=$(BENCH_ELF_CORE) \
		json=$(SIM_JSON) \
		cycles=$(SIM_CYCLES) \
		> $(BENCH_NAME)-sim.log 2> $(BENCH_NAME)-sim-err.log

$(BENCH_CORE): $(BENCH_ELF_CORE)
	elfmi image=$(BENCH_CORE) elf=$(BENCH_ELF_CORE)

out-ref.bin:
	python3 ref.py $@ $(tensor_size) $(DIST) $(NUM_MSGS)

out-sim.bin: $(BENCH_CORE) $(BENCH_MAP)
	miget image=$(BENCH_CORE) map=$(BENCH_MAP) symbol=$(FETCH_SYMBOL) data=$@

bundle.json:
	printf '{\n' > $@
	printf '  "lifetime": %s,\n' "$(WSE_LIFETIME)" >> $@
	printf '  "regions": {\n' >> $@
	printf '    "main_compute": {\n' >> $@
	printf '      "wafer": "%s",\n' "$(WSE_WAFER)" >> $@
	printf '      "width": %s,\n' "$(WSE_WIDTH)" >> $@
	printf '      "height": %s\n' "$(WSE_HEIGHT)" >> $@
	printf '    }\n' >> $@
	printf '  }\n' >> $@
	printf '}\n' >> $@

wse-run: $(BENCH_IMG) $(BENCH_MAP) bundle.json
	- CSRTSERV=$(WSE_SERVER) csclient bundle -bn $(WSE_JOB) --queue bundle.json
	sleep 3
	CSRTSERV=$(WSE_SERVER) csclient job -bn $(WSE_JOB) -r main_compute wipe
	CSRTSERV=$(WSE_SERVER) csclient job -bn $(WSE_JOB) -r main_compute program=$(BENCH_IMG)
	CSRTSERV=$(WSE_SERVER) csclient job -bn $(WSE_JOB) -r main_compute run wait=5 pause
	rm -f result.zip
	rm -rf out_hw
	mkdir -p out_hw
	CSRTSERV=$(WSE_SERVER) csclient job -bn $(WSE_JOB) -r main_compute fetch="symbol=$(FETCH_SYMBOL) savepath=result.zip map=$(BENCH_MAP)"
	unzip -o result.zip -d out_hw

out-wse.bin: wse-run
	@f=$$(find out_hw -maxdepth 1 -type f \( -name '$(FETCH_SYMBOL)' -o -name '$(FETCH_SYMBOL).bin' -o -name '*_$(FETCH_SYMBOL).bin' \) | head -n 1); \
	if [ -n "$$f" ]; then \
		echo "Using fetched file: $$f"; \
		cp "$$f" $@; \
	else \
		echo "Could not find fetched WSE output for symbol $(FETCH_SYMBOL) in out_hw"; \
		echo "Contents of out_hw:"; \
		ls -la out_hw; \
		exit 1; \
	fi

extract-all: $(BENCH_IMG) $(BENCH_MAP)
	rm -rf out_map
	mkdir -p out_map
	for s in $(MAP_SYMS); do \
		echo "Extracting $$s from $(BENCH_IMG)"; \
		miget image=$(BENCH_IMG) map=$(BENCH_MAP) symbol=$$s data=out_map/$${s}.bin || true; \
	done

extract-all-text-img: $(BENCH_IMG) $(BENCH_MAP)
	rm -rf out_text_img
	mkdir -p out_text_img
	for s in $(MAP_SYMS); do \
		echo "Extracting $$s from $(BENCH_IMG) as text"; \
		miget image=$(BENCH_IMG) map=$(BENCH_MAP) symbol=$$s text data=out_text_img/$${s}.txt || true; \
	done

extract-all-text-sim: $(BENCH_CORE) $(BENCH_MAP)
	rm -rf out_text_sim
	mkdir -p out_text_sim
	for s in $(MAP_SYMS); do \
		echo "Extracting $$s from $(BENCH_CORE) as text"; \
		miget image=$(BENCH_CORE) map=$(BENCH_MAP) symbol=$$s text data=out_text_sim/$${s}.txt || true; \
	done

extract-data-text-img: $(BENCH_IMG) $(BENCH_MAP)
	rm -rf out_data_text_img
	mkdir -p out_data_text_img
	for s in $(DATA_SYMS); do \
		echo "Extracting $$s from $(BENCH_IMG) as text"; \
		miget image=$(BENCH_IMG) map=$(BENCH_MAP) symbol=$$s text data=out_data_text_img/$${s}.txt; \
	done

extract-data-text-sim: $(BENCH_CORE) $(BENCH_MAP)
	rm -rf out_data_text_sim
	mkdir -p out_data_text_sim
	for s in $(DATA_SYMS); do \
		echo "Extracting $$s from $(BENCH_CORE) as text"; \
		miget image=$(BENCH_CORE) map=$(BENCH_MAP) symbol=$$s text data=out_data_text_sim/$${s}.txt; \
	done
