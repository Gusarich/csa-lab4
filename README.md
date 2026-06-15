# CSA Lab 4

Python scaffold for ITMO CSA laboratory work 4.

The local design ground truth is `TASK/ARCHITECTURE.md`. The `TASK/` directory is intentionally ignored by Git because it contains task and design handoff materials rather than implementation artifacts.

Planned implementation follows:

```text
asm | risc | neum | hw | tick | binary | trap | port | pstr | prob2 | cache
```

## Layout

- `python/` - translator, ISA, machine model, tests, and golden scenarios.
- `.github/workflows/` - Python and Markdown CI.

No processor or translator implementation is included in this initial scaffold.
