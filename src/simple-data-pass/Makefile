# --- Configuration ---
ARCH           = wse3
LAYOUT         = layout.csl
OUT_DIR        = out
HOST_SCRIPT    = run.py

# grid size, Tensor size, and Parameters
WIDTH          = 2
HEIGHT         = 2
TENSOR_SIZE    = 100
PARAMS         = width:$(WIDTH),height:$(HEIGHT),tensor_size:$(TENSOR_SIZE)

# automatically add padding for memcpy highways
FABRIC_DIMS    = 9,4
FABRIC_OFFSETS = 4,1

# IP:port for a real CS system; set to run on hardware via `make run-hw`
CMADDR         ?=

.PHONY: all compile run run-hw clean debug visualize

all: compile run

compile:
	@echo "\n========================================"
	@echo "[INFO] Compiling $(LAYOUT) for $(ARCH) ($(WIDTH)x$(HEIGHT) grid)..."
	@echo "========================================"
	cslc $(LAYOUT) --arch=$(ARCH) --fabric-dims=$(FABRIC_DIMS) --fabric-offsets=$(FABRIC_OFFSETS) --params=$(PARAMS) --memcpy --channels=1 -o $(OUT_DIR)

run:
	@echo "\n========================================"
	@echo "[INFO] Running Python Host Controller in default mode..."
	@echo "========================================"
	cs_python $(HOST_SCRIPT) --name $(OUT_DIR)

run-hw:
	@echo "\n========================================"
	@echo "[INFO] Running Python Host Controller on hardware at $(CMADDR)..."
	@echo "========================================"
	cs_python $(HOST_SCRIPT) --name $(OUT_DIR) --cmaddr $(CMADDR)

clean:
	@echo "\n[INFO] Cleaning up build directory, core dumps, and sim logs..."
	rm -rf $(OUT_DIR) simfab_traces
	rm -f corefile.cs1* simconfig.json sim.log sim_stats.json

debug:
	@echo "\n[INFO] Launching Cerebras Debugger..."
	csdb

visualize:
	@echo "\n[INFO] Launching Cerebras Visual Debugger (SDK GUI)..."
	sdk_debug_shell visualize
