# CSA Lab 4 Python

This directory will contain the Python implementation of the assembler, binary image tooling, and tick-accurate processor model.

The scaffold mirrors the reference Brainfuck project structure while keeping only the Python parts relevant to this architecture.

## Planned Modules

- `isa.py` - opcodes, instruction formats, encoding, decoding, and disassembly.
- `assembler.py` - asm translator producing binary image, listing, and source map.
- `machine.py` - command-line entry point for the processor model.
- `datapath.py` - passive DataPath signals and observable state.
- `control_unit.py` - hardwired Control Unit finite-state machine.
- `cache.py` - unified direct-mapped write-back cache.
- `io_device.py` - port-mapped input/output and trap input device.
- `tests/` - pytest and golden-test scaffolding.
- `golden/` - future self-contained golden scenarios.

No implementation logic is present yet.
