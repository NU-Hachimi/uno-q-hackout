"""One headless alia-engine for the whole run: the boss's rig and colliders, the shots and the ground
live in its world (conftest.py clears it before every test). Needs alia_engine importable: `make test`
points PYTHONPATH at the engine built for the PC (build/engine-pc)."""

import atexit

import alia_engine as ae

import assets

ENGINE = ae.Engine(headless=True)
assets.load(ENGINE)
W = ENGINE.world
atexit.register(ENGINE.close)
