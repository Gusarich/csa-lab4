"""Assembler tests for layout, encoding, macros, and required diagnostics."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

from assembler import AssemblerError, assemble
from isa import (
    WORD_BYTES,
    Instruction,
    Opcode,
    Segment,
    SegmentFlag,
    decode_binary_image,
    decode_instruction,
    word_from_bytes,
)


def test_assembles_sections_vectors_pstr_bss_and_listing() -> None:
    result = assemble(
        dedent(
            r"""
            .section .vectors
            .org 0x000000
            .word _start
            .word irq
            .space 56

            .section .text
            _start:
                li sp, 0x01000000
                la a0, msg
                call puts
                halt
            puts:
                ret
            irq:
                iret

            .section .rodata
            msg:
                .pstr "Hi\n"

            .section .data
            counter:
                .word 5, 'A'

            .section .bss
            buf:
                .space 8
            """
        )
    )

    assert result.symbols["_start"] == 0x000040
    assert result.symbols["puts"] == 0x000058
    assert result.symbols["irq"] == 0x00005C
    assert result.symbols["msg"] == 0x000060
    assert result.symbols["counter"] == 0x000070
    assert result.symbols["buf"] == 0x000078

    segments = decode_binary_image(result.binary)
    assert [(segment.base_address, segment.size, segment.flags) for segment in segments] == [
        (0x000000, 64, SegmentFlag(0)),
        (0x000040, 32, SegmentFlag.EXEC),
        (0x000060, 16, SegmentFlag(0)),
        (0x000070, 8, SegmentFlag.WRITE),
        (0x000078, 8, SegmentFlag.WRITE | SegmentFlag.BSS),
    ]

    assert _word_at(segments, 0x000000) == 0x000040
    assert _word_at(segments, 0x000004) == 0x00005C
    assert _word_at(segments, 0x000060) == 3
    assert _word_at(segments, 0x000064) == ord("H")
    assert _word_at(segments, 0x000068) == ord("i")
    assert _word_at(segments, 0x00006C) == ord("\n")
    assert _word_at(segments, 0x000070) == 5
    assert _word_at(segments, 0x000074) == ord("A")

    assert decode_instruction(_word_at(segments, 0x000050)) == Instruction(Opcode.JAL, addr24=0x000058)
    assert decode_instruction(_word_at(segments, 0x000058)) == Instruction(Opcode.JR, rs1=15)
    assert "000050 - 0x41000058 - jal 0x000058" in result.listing
    assert any(entry["address"] == 0x000050 and entry["source"] == "call puts" for entry in result.source_map)


def test_expands_conditionals_macros_and_local_labels() -> None:
    result = assemble(
        dedent(
            """
            .equ USE_LOOP, 1

            .macro dec_until_zero reg
            %%loop:
                beq reg, zero, %%end
                addi reg, reg, -1
                j %%loop
            %%end:
            .endm

            .section .text
            .org 0x000040
            _start:
                li t0, 2
            .if USE_LOOP
                dec_until_zero t0
            .else
                halt
            .endif
                halt
            """
        )
    )

    segments = decode_binary_image(result.binary)
    assert decode_instruction(_word_at(segments, 0x000040)) == Instruction(Opcode.ADDI, rd=5, rs1=0, imm16=2)
    assert decode_instruction(_word_at(segments, 0x000044)) == Instruction(Opcode.BEQ, rs1=5, rs2=0, imm16=8)
    assert decode_instruction(_word_at(segments, 0x000048)) == Instruction(Opcode.ADDI, rd=5, rs1=5, imm16=0xFFFF)
    assert decode_instruction(_word_at(segments, 0x00004C)) == Instruction(Opcode.J, addr24=0x000044)
    assert decode_instruction(_word_at(segments, 0x000050)) == Instruction(Opcode.HALT)


@pytest.mark.parametrize(
    "source",
    [
        '.section .text\n.pstr "x"\n',
        ".section .text\n.org 0x40\nnop\n.org 0x40\nhalt\n",
        ".section .text\n.org 0x40\nbeq zero, zero, 0x41\n",
        ".section .data\n.space 1\n.word 0\n",
        ".section .text\nli a0, later\nlater:\n    nop\n",
        ".section .text\n.org 0x40\nla a0, 0x01000000\n",
        ".section .vectors\n.word 0\n.word 0\n.word 1\n",
        '.section .rodata\n.pstr "é"\n',
    ],
)
def test_rejects_required_assembler_errors(source: str) -> None:
    with pytest.raises(AssemblerError):
        assemble(source)


def test_pstr_allows_non_ascii_bytes_only_through_hex_escape() -> None:
    result = assemble(
        dedent(
            r"""
            .section .rodata
            msg:
                .pstr "\xE9"
            """
        )
    )

    segment = decode_binary_image(result.binary)[0]
    assert word_from_bytes(segment.data[0:WORD_BYTES]) == 1
    assert word_from_bytes(segment.data[WORD_BYTES : WORD_BYTES * 2]) == 0xE9


def test_asm_cli_public_interface_writes_binary_listing_and_map(tmp_path: Path) -> None:
    source = tmp_path / "program.asm"
    target = tmp_path / "program.bin"
    listing = tmp_path / "program.hex"
    source_map = tmp_path / "program.map.json"
    source.write_text(
        dedent(
            """
            .section .vectors
            .word _start
            .word 0
            .space 56

            .section .text
            _start:
                halt
            """
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "asm.py",
            str(source),
            str(target),
            "--debug",
            str(listing),
            "--map",
            str(source_map),
        ],
        check=True,
        capture_output=True,
        cwd=Path(__file__).parents[1],
        text=True,
    )

    assert completed.stderr == ""
    assert target.read_bytes().startswith(b"L4MC")
    assert "000040 - 0x43000000 - halt" in listing.read_text(encoding="utf-8")
    mapped_sources = [entry["source"] for entry in json.loads(source_map.read_text(encoding="utf-8"))]
    assert "halt" in mapped_sources


def _word_at(segments: list[Segment], address: int) -> int:
    for segment in segments:
        if segment.flags & SegmentFlag.BSS:
            continue
        start = segment.base_address
        end = start + len(segment.data)
        if start <= address <= end - WORD_BYTES:
            offset = address - start
            return word_from_bytes(segment.data[offset : offset + WORD_BYTES])
    raise AssertionError("word not found at 0x{:06X}".format(address))
