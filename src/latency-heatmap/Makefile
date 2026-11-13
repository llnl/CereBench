BENCH_NAME := latency-test
BENCH_SRC  := $(BENCH_NAME).paint

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

PAINT_STAMP    := .paint-stamp
TARGETS_STAMP  := .targets-stamp
LINK_STAMP     := .build-linked

MODE ?= sim
ARCH ?= sdr

# benchmark geometry / controller placement
W ?= 10
H ?= 10
CX ?= 5
CY ?= 5
NPROBE ?= 16
NWARMUP ?= 16

WSE_FETCH_SYMBOLS := \
		center.target_x \
		center.target_y \
		center.reply_x \
		center.reply_y \
		center.reply_seq \
		center.reply_dbg_row \
		center.t_start \
		center.t_stop \
		center.done \
		center.count \
		center.send_count \
		center.last_sent_x \
		center.last_sent_y

# target generation controls
SCAN_MODE ?= row
X0 ?= 0
Y0 ?= 0
DX ?= 1
DY ?= 1

SIM_CYCLES ?= 50000
SIM_JSON ?= 0

# default fetch symbol, useful for quick sanity checks
FETCH_SYMBOL ?= center.done

TARGETS_X ?= targets_x.bin
TARGETS_Y ?= targets_y.bin

WSE_JOB      ?= $(BENCH_NAME)-run-$(shell date +%Y%m%d_%H%M%S)
WSE_SERVER   ?= http://localhost:8080
WSE_WAFER    ?= xs20863
WSE_WIDTH    ?= $(W)
WSE_HEIGHT   ?= $(H)
WSE_LIFETIME ?= 1000

# empty by default: host-toolchain binaries (paint, milink, simfabric,
# ...) run natively inside the cerebras-env nix shell. Set
# CONTAINER_BIN=singularity (with SIF/TOOLS_BIND) to reproduce the old
# kingfisher-cluster container path
CONTAINER_BIN ?=
SIF ?= /projects/cerebras/cs_sdk-1.3.0/cbcore_sdk-1.3.0.sif
TOOLS_BIND ?= /projects/cerebras/sandbox/sysroot-zen4:/tools

SIM_ENV = --bind $(TOOLS_BIND) --env GITTOP=/tools --env PREPEND_PATH=/tools/bin

MAP_SYMS := $(shell awk '/^[A-Za-z0-9_.-]+[[:space:]]+\[/ { print $$1 }' $(BENCH_MAP) 2>/dev/null | sed 's/[[:space:]]*$$//' | sort -u)
CENTER_SYMS := $(shell awk '/^center\./ { print $$1 }' $(BENCH_MAP) 2>/dev/null | sort -u)

.PHONY: all help build build-run targets load-targets sim wse wse-run \
        wse-queue wse-program wse-exec test clean force-rebuild print-config \
        show-symbols show-center-target-shape extract-all extract-all-text-img \
        extract-all-text-sim extract-center extract-center-text-img \
        extract-center-text-sim fetch-start fetch-stop fetch-replies \
        fetch-targets fetch-targets-img csv fetch-wse-symbols csv-wse

all: test

help:
	@echo "Targets:"
	@echo "  make build"
	@echo "  make build-run"
	@echo "  make targets"
	@echo "  make load-targets"
	@echo "  make sim"
	@echo "  make csv"
	@echo "  make wse-run WSE_JOB=<unique-name>"
	@echo "  make wse-queue WSE_JOB=<unique-name>"
	@echo "  make wse-program WSE_JOB=<unique-name>"
	@echo "  make wse-exec WSE_JOB=<unique-name>"
	@echo "  make test MODE=sim"
	@echo "  make test MODE=wse WSE_JOB=<unique-name>"
	@echo "  make print-config"
	@echo "  make show-symbols"
	@echo "  make show-center-target-shape"
	@echo "  make force-rebuild"
	@echo "  make clean"
	@echo
	@echo "Common overrides:"
	@echo "  W=10 H=10 CX=5 CY=5 NPROBE=16 NWARMUP=0"
	@echo "  SCAN_MODE=row"
	@echo "  SCAN_MODE=column"
	@echo "  SCAN_MODE=box X0=0 Y0=0 DX=2 DY=2"
	@echo "  FETCH_SYMBOL=center.done"
	@echo "  WSE_JOB=$(BENCH_NAME)-run-$$(date +%s)"
	@echo "  WSE_SERVER=http://IP:PORT"

clean:
		find . -mindepth 1 -maxdepth 1 \
					! -name '.' \
							! -name '..' \
									! -name 'Makefile' \
											! -name 'README.md' \
													! -name 'controller.w' \
															! -name 'echo.w' \
																	! -name 'latency-test.paint' \
																			! -name 'plot.py' \
																					! -name 'relay_lib.paint' \
																							! -name 'run_scan.py' \
																									! -name 'scan_workflow.py' \
																											! -name 'targets.py' \
																													-exec rm -rf {} +

print-config:
	@echo "W=$(W)"
	@echo "H=$(H)"
	@echo "CX=$(CX)"
	@echo "CY=$(CY)"
	@echo "NPROBE=$(NPROBE)"
	@echo "NWARMUP=$(NWARMUP)"
	@echo "SCAN_MODE=$(SCAN_MODE)"
	@echo "X0=$(X0)"
	@echo "Y0=$(Y0)"
	@echo "DX=$(DX)"
	@echo "DY=$(DY)"
	@echo "WSE_JOB=$(WSE_JOB)"
	@echo "WSE_SERVER=$(WSE_SERVER)"

build: $(BENCH_IMG)

build-run: $(BENCH_IMG_RUN)

targets: $(TARGETS_X) $(TARGETS_Y)

load-targets: $(BENCH_IMG_RUN)

sim: $(BENCH_CORE)

wse: out-wse.bin

test: test/$(MODE)

test/sim: $(BENCH_CORE)
	@echo "Simulation complete: $(BENCH_CORE)"
	@miget image=$(BENCH_CORE) map=$(BENCH_MAP) symbol=center.done text || true
	@miget image=$(BENCH_CORE) map=$(BENCH_MAP) symbol=center.count text || true

test/wse: out-wse.bin
	@echo "WSE run complete: out-wse.bin"

force-rebuild:
	rm -f $(PAINT_STAMP) $(TARGETS_STAMP) $(LINK_STAMP) \
	      $(BENCH_OBJ) $(BENCH_IMG) $(BENCH_IMG_RUN) $(BENCH_MAP) $(BENCH_NOTE) \
	      $(BENCH_ENTRY) $(BENCH_PS) $(BENCH_REGION) $(BENCH_LISTING) \
	      $(BENCH_ELF) $(BENCH_ELF_CORE) $(BENCH_CORE) \
	      bundle.json out-wse.bin result.zip rtt.csv \
	      $(TARGETS_X) $(TARGETS_Y)


show-symbols: $(BENCH_MAP)
	@echo "Symbols in $(BENCH_MAP):"
	@awk '/^[A-Za-z0-9_.-]+[[:space:]]+\[/ { print $$1 }' $(BENCH_MAP) | sort -u

show-center-target-shape: $(BENCH_MAP)
	@grep "center.target_x" $(BENCH_MAP) || true
	@grep "center.target_y" $(BENCH_MAP) || true

$(PAINT_STAMP): $(BENCH_SRC) $(wildcard *.w)
	rm -f $(BENCH_OBJ) $(BENCH_MAP) $(BENCH_NOTE) $(BENCH_ENTRY) $(BENCH_PS) $(BENCH_REGION) $(BENCH_LISTING)
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
		set CX=$(CX) \
		set CY=$(CY) \
		set NPROBE=$(NPROBE) \
		set NWARMUP=$(NWARMUP) \
		annotate listing=$(BENCH_LISTING)
	touch $@

$(BENCH_OBJ): $(PAINT_STAMP)
$(BENCH_MAP): $(PAINT_STAMP)
$(BENCH_NOTE): $(PAINT_STAMP)
$(BENCH_ENTRY): $(PAINT_STAMP)
$(BENCH_PS): $(PAINT_STAMP)
$(BENCH_REGION): $(PAINT_STAMP)
$(BENCH_LISTING): $(PAINT_STAMP)

$(TARGETS_STAMP): targets.py
	rm -f $(TARGETS_X) $(TARGETS_Y)
	python3 targets.py \
		--mode $(SCAN_MODE) \
		--w $(W) \
		--h $(H) \
		--cx $(CX) \
		--cy $(CY) \
		--nprobe $(NPROBE) \
		--x0 $(X0) \
		--y0 $(Y0) \
		--dx $(DX) \
		--dy $(DY)
	touch $@

$(TARGETS_X): $(TARGETS_STAMP)
$(TARGETS_Y): $(TARGETS_STAMP)

$(LINK_STAMP): $(BENCH_OBJ) $(BENCH_MAP) $(BENCH_NOTE)
	milink image=$(BENCH_OBJ) out=$(BENCH_OBJ) map=$(BENCH_MAP) note=$(BENCH_NOTE)
	weight image=$(BENCH_OBJ) map=$(BENCH_MAP) note=$(BENCH_NOTE)
	touch $@

$(BENCH_IMG): $(LINK_STAMP)
	cp $(BENCH_OBJ) $(BENCH_IMG)

$(BENCH_IMG_RUN): $(BENCH_IMG) $(BENCH_MAP) $(TARGETS_X) $(TARGETS_Y)
	cp $(BENCH_IMG) $(BENCH_IMG_RUN)
	miset image=$(BENCH_IMG_RUN) out=$(BENCH_IMG_RUN) map=$(BENCH_MAP) symbol=center.target_x order="n" data=$(TARGETS_X)
	miset image=$(BENCH_IMG_RUN) out=$(BENCH_IMG_RUN) map=$(BENCH_MAP) symbol=center.target_y order="n" data=$(TARGETS_Y)

$(BENCH_ELF): $(BENCH_IMG_RUN)
	mielf image=$(BENCH_IMG_RUN) elf=$(BENCH_ELF)

$(BENCH_ELF_CORE): $(BENCH_ELF)
	$(if $(CONTAINER_BIN),$(CONTAINER_BIN) exec $(SIM_ENV) $(SIF),) simfabric \
		elf=$(BENCH_ELF) \
		core=$(BENCH_ELF_CORE) \
		json=$(SIM_JSON) \
		cycles=$(SIM_CYCLES) \
		> $(BENCH_NAME)-sim.log 2> $(BENCH_NAME)-sim-err.log

$(BENCH_CORE): $(BENCH_ELF_CORE)
	elfmi image=$(BENCH_CORE) elf=$(BENCH_ELF_CORE)

bundle.json:
	printf '{\n' > $@
	printf '  "lifetime": %s,\n' "$(WSE_LIFETIME)" >> $@
	printf '  "regions": {\n' >> $@
	printf '    "main_compute": {\n' >> $@
	printf '      "wafer": "%s",\n' "$(WSE_WAFER)" >> $@
	printf '      "width": %s,\n' "$(WSE_WIDTH)" >> $@
	printf '      "height": %s,\n' "$(WSE_HEIGHT)" >> $@
	printf '      "padding": 0,\n' >> $@
	printf '      "x": 100,\n' >> $@
	printf '      "y": 100\n' >> $@
	printf '    }\n' >> $@
	printf '  }\n' >> $@
	printf '}\n' >> $@

WSE_WAIT_SECONDS ?= 10

wse-queue: bundle.json
	sleep 2
	CSRTSERV=$(WSE_SERVER) csclient bundle -bn $(WSE_JOB) --queue bundle.json -v verbose
	tail /tmp/csrt_events.log

wse-program: $(BENCH_IMG_RUN) $(BENCH_MAP) wse-queue
	sleep 2
	CSRTSERV=$(WSE_SERVER) csclient job -bn $(WSE_JOB) -r main_compute wipe
	sleep 2
	CSRTSERV=$(WSE_SERVER) csclient job -bn $(WSE_JOB) -r main_compute program=$(BENCH_IMG_RUN)

wse-exec: wse-program
	sleep 2
	CSRTSERV=$(WSE_SERVER) csclient job -bn $(WSE_JOB) -r main_compute run wait=30
	mkdir -p out_hw

wse-run: wse-exec

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

extract-all: $(BENCH_IMG_RUN) $(BENCH_MAP)
	rm -rf out_map
	mkdir -p out_map
	for s in $(MAP_SYMS); do \
		echo "Extracting $$s from $(BENCH_IMG_RUN)"; \
		miget image=$(BENCH_IMG_RUN) map=$(BENCH_MAP) symbol=$$s data=out_map/$${s}.bin || true; \
	done

extract-all-text-img: $(BENCH_IMG_RUN) $(BENCH_MAP)
	rm -rf out_text_img
	mkdir -p out_text_img
	for s in $(MAP_SYMS); do \
		echo "Extracting $$s from $(BENCH_IMG_RUN) as text"; \
		miget image=$(BENCH_IMG_RUN) map=$(BENCH_MAP) symbol=$$s text data=out_text_img/$${s}.txt || true; \
	done

extract-all-text-sim: $(BENCH_CORE) $(BENCH_MAP)
	rm -rf out_text_sim
	mkdir -p out_text_sim
	for s in $(MAP_SYMS); do \
		echo "Extracting $$s from $(BENCH_CORE) as text"; \
		miget image=$(BENCH_CORE) map=$(BENCH_MAP) symbol=$$s text data=out_text_sim/$${s}.txt || true; \
	done

extract-center: $(BENCH_CORE) $(BENCH_MAP)
	rm -rf out_center
	mkdir -p out_center
	for s in $(CENTER_SYMS); do \
		echo "Extracting $$s from $(BENCH_CORE)"; \
		miget image=$(BENCH_CORE) map=$(BENCH_MAP) symbol=$$s data=out_center/$${s}.bin || true; \
	done

extract-center-text-img: $(BENCH_IMG_RUN) $(BENCH_MAP)
	rm -rf out_center_text_img
	mkdir -p out_center_text_img
	for s in $(CENTER_SYMS); do \
		echo "Extracting $$s from $(BENCH_IMG_RUN) as text"; \
		miget image=$(BENCH_IMG_RUN) map=$(BENCH_MAP) symbol=$$s text data=out_center_text_img/$${s}.txt || true; \
	done

extract-center-text-sim: $(BENCH_CORE) $(BENCH_MAP)
	rm -rf out_center_text_sim
	mkdir -p out_center_text_sim
	for s in $(CENTER_SYMS); do \
		echo "Extracting $$s from $(BENCH_CORE) as text"; \
		miget image=$(BENCH_CORE) map=$(BENCH_MAP) symbol=$$s text data=out_center_text_sim/$${s}.txt || true; \
	done

fetch-targets: $(BENCH_CORE) $(BENCH_MAP)
	miget image=$(BENCH_CORE) map=$(BENCH_MAP) symbol=center.target_x text
	miget image=$(BENCH_CORE) map=$(BENCH_MAP) symbol=center.target_y text

fetch-targets-img: $(BENCH_IMG_RUN) $(BENCH_MAP)
	miget image=$(BENCH_IMG_RUN) map=$(BENCH_MAP) symbol=center.target_x text
	miget image=$(BENCH_IMG_RUN) map=$(BENCH_MAP) symbol=center.target_y text

fetch-start: $(BENCH_CORE) $(BENCH_MAP)
	miget image=$(BENCH_CORE) map=$(BENCH_MAP) symbol=center.t_start text

fetch-stop: $(BENCH_CORE) $(BENCH_MAP)
	miget image=$(BENCH_CORE) map=$(BENCH_MAP) symbol=center.t_stop text

fetch-replies: $(BENCH_CORE) $(BENCH_MAP)
	miget image=$(BENCH_CORE) map=$(BENCH_MAP) symbol=center.reply_x text
	miget image=$(BENCH_CORE) map=$(BENCH_MAP) symbol=center.reply_y text
	miget image=$(BENCH_CORE) map=$(BENCH_MAP) symbol=center.count text
	miget image=$(BENCH_CORE) map=$(BENCH_MAP) symbol=center.done text

csv: $(BENCH_CORE) $(BENCH_MAP)
	python3 run_scan.py --csv rtt.csv --core $(BENCH_CORE) --map $(BENCH_MAP)

fetch-wse-symbols: $(BENCH_MAP)
	rm -rf out_hw
	mkdir -p out_hw
	for s in $(WSE_FETCH_SYMBOLS); do \
		echo "Fetching $$s from WSE"; \
		rm -f result.zip; \
		CSRTSERV=$(WSE_SERVER) csclient job -bn $(WSE_JOB) -r main_compute pause \
			fetch="symbol=$$s savepath=result.zip map=$(BENCH_MAP)"; \
		unzip -o result.zip -d out_hw >/dev/null; \
	done

csv-wse: fetch-wse-symbols
	python3 run_scan.py --csv rtt.csv --hwdir out_hw
