"""Golden tests for the assembler and machine."""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

import assembler
import machine

DEFAULT_MAX_TICKS = 1_000_000
MAX_LOG = 4000


@pytest.mark.golden_test("golden/*_asm.yml")
def test_assembler_and_machine(golden: Any) -> None:
    """Run one self-contained asm YAML golden scenario."""
    with tempfile.TemporaryDirectory() as tmpdirname:
        workdir = Path(tmpdirname)
        source = workdir / "source.asm"
        input_stream = workdir / "input.txt"
        target = workdir / "target.bin"
        target_hex = workdir / "target.bin.hex"
        target_map = workdir / "target.bin.map.json"
        target_log = workdir / "target.log"

        source.write_text(golden["in_source"], encoding="utf-8")
        input_stream.write_text(golden["in_stdin"], encoding="utf-8")

        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            assembler.main(str(source), str(target), source_map=str(target_map))
            sys.stdout.write("============================================================\n")
            machine.main(
                str(target),
                str(input_stream),
                source_map_file=str(target_map),
                log_file=str(target_log),
                max_ticks=golden.get("in_max_ticks", DEFAULT_MAX_TICKS),
            )

        code = target.read_bytes()
        code_hex = target_hex.read_text(encoding="utf-8")
        log = target_log.read_text(encoding="utf-8")

        assert code == golden.out["out_code"]
        assert code_hex == golden.out["out_code_hex"]
        assert stdout.getvalue() == golden.out["out_stdout"]
        assert log[0:MAX_LOG] + "EOF" == golden.out["out_log"]
