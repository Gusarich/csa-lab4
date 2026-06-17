"""Golden integration tests for assembler output and machine traces."""

from __future__ import annotations

import base64
from typing import Any, cast

import pytest

from assembler import AssemblerError, assemble
from machine import format_trace_entry, simulate

DEFAULT_MAX_TICKS = 1_000_000


@pytest.mark.golden_test("golden/*.yml")
def test_assembler_and_machine_golden(golden: Any) -> None:
    """Run one self-contained YAML golden scenario."""
    source = cast(str, golden["in_source"])
    if golden.get("in_assembler_error") is not None:
        with pytest.raises(AssemblerError) as exc_info:
            assemble(source)
        assert str(exc_info.value) == golden.out["out_assembler_error"]
        return

    assembly = assemble(source)
    source_map = {cast(int, entry["address"]): cast(str, entry["source"]) for entry in assembly.source_map}
    args = cast(dict[str, int], golden.get("in_args", {}))
    result = simulate(
        assembly.binary,
        cast(str, golden.get("in_input_schedule", "")),
        max_ticks=args.get("max_ticks", DEFAULT_MAX_TICKS),
        source_map=source_map,
    )

    assert base64.b64encode(assembly.binary).decode("ascii") == golden.out["out_code_base64"]
    assert assembly.listing == golden.out["out_listing"]
    assert result.stdout == golden.out["out_stdout"]
    assert result.stop_reason.value == golden.out["out_stop_reason"]
    assert result.ticks == golden.out["out_ticks"]
    assert _selected_trace(result.log, cast(list[str], golden.get("in_log_patterns", []))) == golden.out["out_log"]


def _selected_trace(log: list[Any], patterns: list[str]) -> str:
    lines = [format_trace_entry(entry) for entry in log]
    selected: list[str] = []
    start = 0
    for pattern in patterns:
        for index in range(start, len(lines)):
            if pattern in lines[index]:
                selected.append(lines[index])
                start = index + 1
                break
        else:
            message = f"trace pattern not found in order: {pattern}"
            raise AssertionError(message)
    return "\n".join(selected)
