"""Golden integration tests for assembler output and machine traces."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from assembler import AssemblerError, assemble
from machine import format_trace_entry, simulate

DEFAULT_MAX_TICKS = 1_000_000
GOLDEN_DIR = Path(__file__).parent / "golden"
GOLDEN_CASES = tuple(sorted(GOLDEN_DIR.glob("*.yml")))


@pytest.mark.parametrize("golden_path", GOLDEN_CASES, ids=lambda path: f"golden/{path.name}")
def test_assembler_and_machine_golden(golden_path: Path) -> None:
    """Run one self-contained YAML golden scenario."""
    golden = _load_golden(golden_path)
    source = cast(str, golden["in_source"])
    if golden.get("in_assembler_error") is not None:
        with pytest.raises(AssemblerError) as exc_info:
            assemble(source)
        assert str(exc_info.value) == golden["out_assembler_error"]
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

    assert base64.b64encode(assembly.binary).decode("ascii") == golden["out_code_base64"]
    assert assembly.listing == golden["out_listing"]
    assert result.stdout == golden["out_stdout"]
    assert result.stop_reason.value == golden["out_stop_reason"]
    assert result.ticks == golden["out_ticks"]
    assert _selected_trace(result.log, cast(list[str], golden.get("in_log_patterns", []))) == golden["out_log"]
    _assert_trace_pattern_counts(result.log, cast(dict[str, int], golden.get("out_log_pattern_counts", {})))


def _load_golden(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        message = f"golden file must contain a mapping: {path}"
        raise TypeError(message)
    return cast(dict[str, Any], loaded)


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


def _assert_trace_pattern_counts(log: list[Any], expected_counts: dict[str, int]) -> None:
    lines = [format_trace_entry(entry) for entry in log]
    for pattern, expected in sorted(expected_counts.items()):
        actual = sum(1 for line in lines if pattern in line)
        assert actual == expected, pattern
