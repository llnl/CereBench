# --- Configuration ---
ARCH           = wse3
LAYOUT         = layout.csl
OUT_DIR        = out
HOST_SCRIPT    = run.py
CMADDR         ?=

# grid size, Tensor size, and Parameters
WIDTH          = 2
HEIGHT         = 2
TENSOR_SIZE    = 100
PARAMS         = width:$(WIDTH),height:$(HEIGHT),tensor_size:$(TENSOR_SIZE)

# automatically add padding for memcpy highways
FABRIC_DIMS    = 9,4
FABRIC_OFFSETS = 4,1

.PHONY: all compile run run-hw clean debug visualize

all: compile run

compile:
	@echo "Compiling $(LAYOUT) for $(ARCH) ($(WIDTH)x$(HEIGHT) grid)..."
	cslc $(LAYOUT) --arch=$(ARCH) --fabric-dims=$(FABRIC_DIMS) --fabric-offsets=$(FABRIC_OFFSETS) --params=$(PARAMS) --memcpy --channels=1 -o $(OUT_DIR)

run:
	@echo "Running Python Host Controller in default mode..."
	cs_python $(HOST_SCRIPT) --name $(OUT_DIR)

run-hw:
	@echo "Running Python Host Controller on hardware at $(CMADDR)..."
	cs_python $(HOST_SCRIPT) --name $(OUT_DIR) --cmaddr $(CMADDR)

clean:
	rm -rf $(OUT_DIR) simfab_traces
	rm -f corefile.cs1* simconfig.json sim.log sim_stats.json

debug:
	csdb

visualize:
	sdk_debug_shell visualize
