"""Structural tests for the standalone asm examples."""

from __future__ import annotations

from pathlib import Path

import pytest

EXAMPLES = Path(__file__).parents[1] / "examples"
EXAMPLE_SOURCES = sorted(EXAMPLES.glob("*.asm"))
GOLDEN = Path(__file__).parents[1] / "golden"
REQUIRED_GOLDENS = {
    "hello_asm.yml",
    "cat_asm.yml",
    "hello_user_name_asm.yml",
    "hello_user_name_long_asm.yml",
    "sort_asm.yml",
    "sort_invalid_token_asm.yml",
    "double_precision_asm.yml",
    "prob2_100_asm.yml",
    "prob2_zero_asm.yml",
    "prob2_one_asm.yml",
    "prob2_max_asm.yml",
    "prob2_range_asm.yml",
    "prob2_invalid_asm.yml",
    "prob2_empty_asm.yml",
    "prob2_overrun_asm.yml",
    "cache_sequential_asm.yml",
    "cache_conflict_writeback_asm.yml",
    "tick_lw_asm.yml",
    "trap_irq_asm.yml",
    "trap_irq_during_handler_asm.yml",
    "branch_byte_offset_asm.yml",
    "fault_bad_encoding_asm.yml",
    "fault_unaligned_lw_asm.yml",
}
PRIMARY_GOLDEN_EXAMPLES = {
    "hello_asm.yml": "hello.asm",
    "cat_asm.yml": "cat.asm",
    "hello_user_name_asm.yml": "hello_user_name.asm",
    "hello_user_name_long_asm.yml": "hello_user_name.asm",
    "sort_asm.yml": "sort.asm",
    "sort_invalid_token_asm.yml": "sort.asm",
    "double_precision_asm.yml": "double_precision.asm",
    "prob2_100_asm.yml": "prob2.asm",
    "prob2_zero_asm.yml": "prob2.asm",
    "prob2_one_asm.yml": "prob2.asm",
    "prob2_max_asm.yml": "prob2.asm",
    "prob2_range_asm.yml": "prob2.asm",
    "prob2_invalid_asm.yml": "prob2.asm",
    "prob2_empty_asm.yml": "prob2.asm",
    "prob2_overrun_asm.yml": "prob2.asm",
    "cache_sequential_asm.yml": "cache_sequential.asm",
    "cache_conflict_writeback_asm.yml": "cache_conflict.asm",
}


def test_required_integration_scenarios_are_golden_yaml() -> None:
    missing = sorted(name for name in REQUIRED_GOLDENS if not (GOLDEN / name).is_file())

    assert missing == []


def test_primary_goldens_embed_checked_in_example_sources() -> None:
    mismatches = []
    for golden_name, example_name in sorted(PRIMARY_GOLDEN_EXAMPLES.items()):
        golden_source = _golden_source(GOLDEN / golden_name)
        example_source = (EXAMPLES / example_name).read_text(encoding="utf-8")
        if golden_source != example_source:
            mismatches.append(f"{golden_name} != {example_name}")

    assert mismatches == []


@pytest.mark.parametrize("source_path", EXAMPLE_SOURCES)
def test_example_sources_follow_structured_asm_style(source_path: Path) -> None:
    lines = source_path.read_text(encoding="utf-8").splitlines()
    halt_indexes = [index for index, line in enumerate(lines) if line.strip() == "halt"]

    assert "\t" not in "\n".join(lines)
    assert len(halt_indexes) == 1
    assert _previous_code_line(lines, halt_indexes[0]) == "done:"
    assert ".section .vectors" in lines


def _previous_code_line(lines: list[str], index: int) -> str:
    for previous in range(index - 1, -1, -1):
        line = lines[previous].strip()
        if line and not line.startswith(";"):
            return line
    return ""


def _golden_source(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = lines.index("in_source: |") + 1
    source_lines = []
    for line in lines[start:]:
        if line and not line.startswith("  "):
            break
        source_lines.append(line[2:] if line.startswith("  ") else "")
    return "\n".join(source_lines).rstrip() + "\n"
