# Python Implementation

This directory is the executable implementation of the lab 4 architecture. It
uses plain Python modules and `uv`; there is no generated source and no hidden
runtime outside the asm programs themselves.

## Commands

Install dependencies:

```bash
uv sync --all-groups
```

Assemble:

```bash
uv run python asm.py examples/prob2.asm out/prob2.bin \
  --debug out/prob2.hex \
  --map out/prob2.map.json
```

Run:

```bash
uv run python machine.py out/prob2.bin out/prob2.input \
  --map out/prob2.map.json \
  --log out/prob2.trace \
  --max-ticks 2500000
```

Run checks:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy .
uv run coverage run -m pytest .
uv run coverage report -m
```

Update golden files intentionally:

```bash
uv run pytest . -v --update-goldens
```

## Modules

- `isa.py` defines the fixed 32-bit instruction formats, register names,
  opcodes, segment container, encoder, decoder, and disassembler.
- `asm.py` is the public assembler CLI described by the architecture.
- `assembler.py` implements preprocessing, macros, conditionals, sections,
  `.org`, data directives, pseudoinstructions, two-pass address assignment, and
  binary/listing/source-map output.
- `cache.py` contains byte-addressed memory and the direct-mapped write-back
  cache. Cache fill and write-back advance one memory word transaction per ten
  ticks.
- `io_device.py` contains the scheduled input source, the one-register trap
  input device, output buffering, and port access checks.
- `datapath.py` is the passive hardware surface: register file, `IR`,
  `ALU_OUT`, ALU operations, cache requests, port operations, and address-source
  selection.
- `control_unit.py` is the hardwired FSM. It owns `PC`, `EPC`, `CAUSE`,
  `STATUS`, `state`, `step`, interrupt entry, reset-vector fetch, instruction
  decode, and stop reasons.
- `machine.py` loads the L4MC binary image, applies the input schedule, runs the
  Control Unit, writes trace logs, and prints output plus stop reason.

## Examples

The required asm programs live in `examples/`:

- `hello.asm` prints a Pascal string from `.rodata`.
- `cat.asm` echoes trap input through the software ring buffer.
- `hello_user_name.asm` reads a name into a Pascal string and validates capacity.
- `sort.asm` parses and sorts up to 32 unsigned 32-bit numbers.
- `double_precision.asm` demonstrates explicit 64-bit arithmetic over 32-bit
  words.
- `prob2.asm` solves Euler problem 6 for `0 <= n <= 92681`.
- `cache_sequential.asm` and `cache_conflict.asm` demonstrate locality,
  conflict misses, and write-back behavior.

## Tests

Unit tests cover ISA encoding, assembler errors, DataPath signals, cache/memory,
ports, Control Unit transitions, and the machine CLI. Golden tests in `golden/`
are self-contained YAML scenarios that check assembled code, listing output,
stdout, stop reason, and representative trace fragments.

The long `prob2` boundary case (`92681`) is executed through the real
`machine.py` CLI in a subprocess so that coverage tracing does not distort the
processor timing test or exhaust the self-hosted runner.
