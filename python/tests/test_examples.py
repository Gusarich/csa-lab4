"""Executable tests for the standalone asm examples."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from assembler import assemble
from cache import CachePhase
from control_unit import StopReason
from machine import simulate

EXAMPLES = Path(__file__).parents[1] / "examples"
EXAMPLE_SOURCES = sorted(EXAMPLES.glob("*.asm"))


def test_hello_example_outputs_pascal_string() -> None:
    result = _run_example("hello")

    assert result.stop_reason == StopReason.HALT
    assert result.stdout == "hello world\n"


def test_cat_example_uses_trap_input_queue() -> None:
    result = _run_example("cat", _schedule_for_text("foo\n"), max_ticks=50_000)

    assert result.stop_reason == StopReason.HALT
    assert result.stdout == "foo\n"
    assert any(entry.state.value == "IRQ_ENTER" for entry in result.log)
    assert any(entry.port_event.startswith("in 0x0001") for entry in result.log)


def test_hello_user_name_example_builds_pascal_string() -> None:
    result = _run_example("hello_user_name", _schedule_for_text("Alice\n"), max_ticks=60_000)

    assert result.stop_reason == StopReason.HALT
    assert result.stdout == "What is your name?\nHello, Alice!\n"


def test_hello_user_name_reports_long_input() -> None:
    result = _run_example("hello_user_name", _schedule_for_text("x" * 35 + "\n"), max_ticks=120_000)

    assert result.stop_reason == StopReason.HALT
    assert result.stdout == "What is your name?\nERR_INPUT\n"


def test_sort_example_sorts_u32_words() -> None:
    result = _run_example("sort", _schedule_for_text("5 10 2 7 3 1\n"), max_ticks=100_000)

    assert result.stop_reason == StopReason.HALT
    assert result.stdout == "1 2 3 7 10\n"


@pytest.mark.parametrize("source", ["2 1\n", "2 1 x\n", "33 1\n"])
def test_sort_example_reports_invalid_input(source: str) -> None:
    result = _run_example("sort", _schedule_for_text(source), max_ticks=100_000)

    assert result.stop_reason == StopReason.HALT
    assert result.stdout == "ERR_INPUT\n"


def test_double_precision_example_prints_u64_results() -> None:
    result = _run_example("double_precision", max_ticks=20_000)

    assert result.stop_reason == StopReason.HALT
    assert result.stdout == ("0xffffffff + 1 = 4294967296\n0xffffffff * 0xffffffff = 18446744065119617025\n")


@pytest.mark.parametrize(
    ("source", "expected", "max_ticks"),
    [
        ("100\n", "25164150\n", 100_000),
        ("0\n", "0\n", 100_000),
        ("1\n", "0\n", 100_000),
        ("92682\n", "ERR_RANGE\n", 100_000),
        ("abc\n", "ERR_INPUT\n", 100_000),
        ("\n", "ERR_INPUT\n", 100_000),
    ],
)
def test_prob2_example_handles_required_cases(source: str, expected: str, max_ticks: int) -> None:
    result = _run_example("prob2", _schedule_for_text(source), max_ticks=max_ticks)

    assert result.stop_reason == StopReason.HALT
    assert result.stdout == expected


def test_prob2_example_handles_u32_boundary_via_cli(tmp_path: Path) -> None:
    program = tmp_path / "prob2.bin"
    schedule = tmp_path / "prob2.input"
    assembly = assemble((EXAMPLES / "prob2.asm").read_text(encoding="utf-8"))
    program.write_bytes(assembly.binary)
    schedule.write_text(_schedule_for_text("92681\n"), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(EXAMPLES.parent / "machine.py"),
            str(program),
            str(schedule),
            "--max-ticks",
            "2500000",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stderr == ""
    assert completed.stdout.startswith("18446160229542257100\n")
    assert "stop reason: HALT\n" in completed.stdout


def test_cache_examples_show_locality_and_conflicts() -> None:
    sequential = _run_example("cache_sequential", max_ticks=5_000)
    conflict = _run_example("cache_conflict", max_ticks=5_000)

    assert sequential.stop_reason == StopReason.HALT
    assert conflict.stop_reason == StopReason.HALT
    assert sequential.stdout == "A"
    assert conflict.stdout == "Z"
    assert conflict.ticks > sequential.ticks
    assert any(entry.cache is not None and entry.cache.hit for entry in sequential.log)
    assert any(entry.cache is not None and entry.cache.phase == CachePhase.WRITE_BACK for entry in conflict.log)


@pytest.mark.parametrize("source_path", EXAMPLE_SOURCES)
def test_example_sources_follow_structured_asm_style(source_path: Path) -> None:
    lines = source_path.read_text(encoding="utf-8").splitlines()
    halt_indexes = [index for index, line in enumerate(lines) if line.strip() == "halt"]

    assert "\t" not in "\n".join(lines)
    assert len(halt_indexes) == 1
    assert _previous_code_line(lines, halt_indexes[0]) == "done:"
    assert ".section .vectors" in lines


def _run_example(name: str, schedule: str = "", *, max_ticks: int = 200_000):
    assembly = assemble((EXAMPLES / "{}.asm".format(name)).read_text(encoding="utf-8"))
    return simulate(assembly.binary, schedule, max_ticks=max_ticks)


def _previous_code_line(lines: list[str], index: int) -> str:
    for previous in range(index - 1, -1, -1):
        line = lines[previous].strip()
        if line and not line.startswith(";"):
            return line
    return ""


def _schedule_for_text(text: str, *, start: int = 10_000, gap: int = 2_500) -> str:
    lines = []
    for index, char in enumerate(text):
        token = "'\\n'" if char == "\n" else repr(char)
        lines.append("{} {}".format(start + index * gap, token))
    lines.append("{} EOF".format(start + len(text) * gap))
    return "\n".join(lines) + "\n"
