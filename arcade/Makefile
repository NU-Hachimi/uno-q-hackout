.DEFAULT_GOAL := help

# Megalith as an Alia Pad cart, drawn by alia-engine (python/alia_view.py). The engine is
# built from a checkout next to alia-pad; the board build cross-compiles with alia-pad's sysroot.
ALIA_ENGINE ?= $(HOME)/Projects/alia-engine
ALIA_PAD ?= $(HOME)/Projects/alia-pad
ACART ?= $(ALIA_PAD)/tools/acart
PYTHON ?= python3
CMAKE_GEN ?= -G Ninja
CART_ID = com.nuhachimi.megalith

ENGINE_PC = build/engine-pc
ENGINE_BOARD = build/engine-board
CART_DIR = build/cart
CART_PC_DIR = build/cart-pc
CART_FILE = build/megalith.acart
ENGINE_OPTS = -DALIA_BUILD_TESTS=OFF -DALIA_BUILD_APPS=OFF

.PHONY: help run test gen engine-pc engine-board cart cart-pc install launch stop logs clean

help:
	@printf '%s\n' \
	  'make run           Play on the PC (window; keyboard or gamepad)' \
	  'make test          Python tests (in a headless alia-engine built for the PC)' \
	  'make gen           Regenerate python/gen and sketch/gen from assets/' \
	  'make cart          Board cart: build/cart/ and build/megalith.acart' \
	  'make cart-pc       The same cart for the PC (simulator): build/cart-pc/' \
	  'make install       Install build/megalith.acart on the board (acart --board install)' \
	  'make launch        Launch it on the board through alia-session (stops the foreground cart)' \
	  'make stop | logs   Stop it / follow its log on the board' \
	  'make clean         Remove build/' \
	  'Overrides: ALIA_ENGINE=, ALIA_PAD=, ACART=, PYTHON='

$(ENGINE_PC)/build.ninja:
	cmake -S "$(ALIA_ENGINE)" -B $(ENGINE_PC) $(CMAKE_GEN) -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_C_COMPILER=clang \
	  $(ENGINE_OPTS)

$(ENGINE_BOARD)/build.ninja:
	cmake -S "$(ALIA_ENGINE)" -B $(ENGINE_BOARD) $(CMAKE_GEN) \
	  -DCMAKE_TOOLCHAIN_FILE="$(ALIA_ENGINE)/cmake/aarch64-board.cmake" -DALIA_PAD_DIR="$(ALIA_PAD)" $(ENGINE_OPTS)

engine-pc: $(ENGINE_PC)/build.ninja
	cmake --build $(ENGINE_PC)

engine-board: $(ENGINE_BOARD)/build.ninja
	cmake --build $(ENGINE_BOARD)

run: engine-pc
	cd python && PYTHONPATH="$(CURDIR)/$(ENGINE_PC)" "$(PYTHON)" main.py

test: $(ENGINE_PC)/build.ninja
	cmake --build $(ENGINE_PC) --target alia_engine
	PYTHONPATH="$(CURDIR)/$(ENGINE_PC)" "$(PYTHON)" -m pytest -q tests

gen:
	ALIA_ENGINE="$(ALIA_ENGINE)" "$(PYTHON)" tools/mesh_build.py
	ALIA_ENGINE="$(ALIA_ENGINE)" "$(PYTHON)" tools/rig_build.py

cart: engine-board engine-pc
	ALIA_ENGINE="$(ALIA_ENGINE)" "$(PYTHON)" tools/mesh_build.py --check
	ALIA_ENGINE="$(ALIA_ENGINE)" "$(PYTHON)" tools/rig_build.py --check
	PYTHON="$(PYTHON)" sh tools/cart_build.sh $(ENGINE_BOARD) $(ENGINE_PC) $(CART_DIR)
	"$(ACART)" check $(CART_DIR)
	"$(ACART)" pack $(CART_DIR) -o $(CART_FILE)

cart-pc: engine-pc
	PYTHON="$(PYTHON)" sh tools/cart_build.sh $(ENGINE_PC) $(ENGINE_PC) $(CART_PC_DIR)
	"$(ACART)" check $(CART_PC_DIR)

install:
	"$(ACART)" --board install $(CART_FILE)

launch:
	"$(ACART)" --board launch --replace $(CART_ID)

stop:
	"$(ACART)" --board stop

logs:
	adb shell -t 'tail -n 50 -F $$HOME/.local/share/alia/logs/$(CART_ID).log'

clean:
	rm -rf build
