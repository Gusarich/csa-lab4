"""Structural tests for the standalone asm examples."""

from __future__ import annotations

from pathlib import Path

import pytest

EXAMPLES = Path(__file__).parents[1] / "examples"
EXAMPLE_SOURCES = sorted(EXAMPLES.glob("*.asm"))
GOLDEN = Path(__file__).parents[1] / "golden"
REQUIRED_GOLDENS = {
    "hello.yml",
    "hello_user_name.yml",
    "hello_user_name_long.yml",
    "sort.yml",
    "sort_invalid_token.yml",
    "double_precision.yml",
    "prob2_100.yml",
    "prob2_max.yml",
    "prob2_range.yml",
    "prob2_invalid.yml",
    "cache_sequential.yml",
    "cache_conflict_writeback.yml",
    "tick_lw.yml",
    "trap_irq.yml",
}


def test_required_integration_scenarios_are_golden_yaml() -> None:
    missing = sorted(name for name in REQUIRED_GOLDENS if not (GOLDEN / name).is_file())

    assert missing == []


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
