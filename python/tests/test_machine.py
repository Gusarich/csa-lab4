"""Tests for the machine CLI layer."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import cast

from assembler import assemble
from control_unit import StopReason
from machine import main, simulate


def test_simulate_runs_binary_and_returns_result() -> None:
    assembly = assemble(_hello_source())
    source_map = {cast(int, entry["address"]): cast(str, entry["source"]) for entry in assembly.source_map}

    result = simulate(assembly.binary, "", max_ticks=200, source_map=source_map)

    assert result.stdout == "A"
    assert result.stop_reason == StopReason.HALT
    assert result.ticks == len(result.log)


def test_main_writes_trace_log_and_prints_summary(tmp_path: Path, capsys) -> None:
    assembly = assemble(_hello_source())
    program = tmp_path / "program.bin"
    schedule = tmp_path / "input.schedule"
    source_map = tmp_path / "program.map.json"
    trace = tmp_path / "trace.log"
    program.write_bytes(assembly.binary)
    schedule.write_text("", encoding="utf-8")
    source_map.write_text(json.dumps(assembly.source_map), encoding="utf-8")

    main(str(program), str(schedule), source_map_file=str(source_map), log_file=str(trace), max_ticks=200)

    stdout = capsys.readouterr().out
    assert stdout.startswith("A\nstop reason: HALT\n")
    match = re.search(r"ticks: (\d+)", stdout)
    assert match is not None
    ticks = int(match.group(1))
    lines = trace.read_text(encoding="utf-8").splitlines()
    assert len(lines) == ticks
    assert any("cache=read:tag" in line and "MISS" in line for line in lines)
    assert any("cache=read:fill" in line for line in lines)
    assert any("src='out OUT_DATA, a0'" in line for line in lines)


def _hello_source() -> str:
    return """
    .section .vectors
    .word _start
    .word 0
    .space 56

    .section .text
    _start:
        li a0, 'A'
        out OUT_DATA, a0
        halt
    """
