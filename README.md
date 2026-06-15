# CSA Lab 4

ФИО: Седов Даниил Борисович

Группа: Р3216

Variant:

```text
asm | risc | neum | hw | tick | binary | trap | port | pstr | prob2 | cache
```

This repository contains a complete Python implementation of the lab 4 machine:
an assembler, binary image format, tick-accurate processor model, unified cache,
trap input device, port-mapped output, demonstration asm programs, and golden
tests. The local design ground truth is `TASK/ARCHITECTURE.md`; the `TASK/`
directory is intentionally ignored by Git because it contains task handoff
materials.

## Quick Start

Install dependencies:

```bash
cd python
uv sync --all-groups
```

Assemble and run `hello`:

```bash
uv run python assembler.py examples/hello.asm out/hello.bin \
  --debug out/hello.hex \
  --map out/hello.map.json
touch out/empty.input
uv run python machine.py out/hello.bin out/empty.input \
  --map out/hello.map.json \
  --log out/hello.trace \
  --max-ticks 1000000
```

Run the local quality gate:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy .
uv run coverage run -m pytest .
uv run coverage report -m
```

## Project Layout

- `python/isa.py` - instruction formats, opcodes, binary image encoding,
  decoding, and disassembly.
- `python/assembler.py` - asm translator that produces an L4MC binary image,
  debug listing, and source map.
- `python/machine.py` - processor CLI and simulator entry point.
- `python/datapath.py` - passive DataPath methods that correspond to hardware
  control signals.
- `python/control_unit.py` - hardwired finite-state Control Unit with `state`
  and `step`.
- `python/cache.py` - unified direct-mapped write-back cache over byte-addressed
  memory.
- `python/io_device.py` - port-mapped input/output and single-register trap
  input device.
- `python/examples/` - required asm programs: `hello`, `cat`,
  `hello_user_name`, `sort`, double precision arithmetic, `prob2`, and cache
  demos.
- `python/golden/` - self-contained golden scenarios for binary output,
  listings, trace fragments, trap behavior, cache timing, and addressing
  corner cases.
- `docs/` - submitted DataPath and Control Unit schemes plus scheme-checking
  notes.

## Architectural Invariants

- Memory is unified, von Neumann, byte-addressed, and one-port.
- `PC` belongs to the Control Unit, not to the DataPath.
- DataPath is passive: it knows signals such as `latch_ir`, `cache_read`, and
  `alu_execute`, not instructions such as `addi`, `jal`, or `iret`.
- One `tick()` advances the machine by exactly one hardware tick.
- Cache misses are logged tick by tick: a clean miss has 41 trace entries for
  that access and a dirty miss has 81.
- Trap input uses one device data register. Software queues are ordinary memory
  structures written by asm handlers.
- Strings are Pascal strings in data sections: one length word followed by one
  word per byte character.

## CI

GitHub Actions runs on the self-hosted `csa-lab4` runner for pushes to `main`.
The Python workflow runs formatting, Ruff, mypy, pytest, golden tests, and a
coverage report. The Markdown workflow checks repository documentation while
ignoring the local `TASK/` handoff directory.
