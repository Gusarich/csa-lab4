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
            """,
        ),
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

    assert decode_instruction(_word_at(segments, 0x000040)) == Instruction(Opcode.LUI, rd=14, imm16=0x0100)
    assert decode_instruction(_word_at(segments, 0x000044)) == Instruction(Opcode.ORI, rd=14, rs1=14, imm16=0)
    assert decode_instruction(_word_at(segments, 0x000048)) == Instruction(Opcode.LUI, rd=1, imm16=0)
    assert decode_instruction(_word_at(segments, 0x00004C)) == Instruction(Opcode.ORI, rd=1, rs1=1, imm16=0x0060)
    assert decode_instruction(_word_at(segments, 0x000050)) == Instruction(Opcode.JAL, addr24=0x000058)
    assert decode_instruction(_word_at(segments, 0x000058)) == Instruction(Opcode.JR, rs1=15)
    assert decode_instruction(_word_at(segments, 0x00005C)) == Instruction(Opcode.IRET)
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
            """,
        ),
    )

    segments = decode_binary_image(result.binary)
    assert [(segment.base_address, segment.size, segment.flags) for segment in segments] == [
        (0x000040, 20, SegmentFlag.EXEC),
    ]
    assert decode_instruction(_word_at(segments, 0x000040)) == Instruction(Opcode.ADDI, rd=5, rs1=0, imm16=2)
    assert decode_instruction(_word_at(segments, 0x000044)) == Instruction(Opcode.BEQ, rs1=5, rs2=0, imm16=8)
    assert decode_instruction(_word_at(segments, 0x000048)) == Instruction(Opcode.ADDI, rd=5, rs1=5, imm16=0xFFFF)
    assert decode_instruction(_word_at(segments, 0x00004C)) == Instruction(Opcode.J, addr24=0x000044)
    assert decode_instruction(_word_at(segments, 0x000050)) == Instruction(Opcode.HALT)
    assert {entry["address"] for entry in result.source_map} == {0x000040, 0x000044, 0x000048, 0x00004C, 0x000050}


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ('.section .text\n.pstr "x"\n', "line 2: .pstr is allowed only in .rodata or .data"),
        (".section .text\n.org 0x40\nnop\n.org 0x40\nhalt\n", "line 5: byte range overlaps line 3"),
        (
            ".section .text\n.org 0x40\nbeq zero, zero, 0x41\n",
            "line 3: target address is out of range or not word-aligned",
        ),
        (".section .data\n.space 1\n.word 0\n", "line 3: .word address is not word-aligned"),
        (".section .text\nli a0, later\nlater:\n    nop\n", "unknown identifier: later"),
        (".section .text\n.org 0x40\nla a0, 0x01000000\n", "la address is outside 24-bit memory range"),
        (
            ".section .text\nla a0, top + 4\nhalt\n.section .data\n.org 0x00FFFFFC\ntop:\n.word 0\n",
            "line 2: la address is outside 24-bit memory range",
        ),
        (
            ".section .vectors\n.word 0\n.word 0\n.word 1\n",
            "line 4: reserved vector-table entries must be zero",
        ),
        (
            ".section .vectors\n.org 0x000008\nhalt\n",
            "line 3: reserved vector-table entries must be zero",
        ),
        (
            ".section .data\n.word 1\n.section .text\nhalt\n",
            "line 3: sections must follow order: .vectors, .text, .rodata, .data, .bss",
        ),
        ('.section .rodata\n.pstr "é"\n', r"line 2: non-ASCII string bytes must use \xNN escapes"),
    ],
)
def test_rejects_required_assembler_errors(source: str, message: str) -> None:
    with pytest.raises(AssemblerError) as exc_info:
        assemble(source)
    assert str(exc_info.value) == message


def test_pstr_allows_non_ascii_bytes_only_through_hex_escape() -> None:
    result = assemble(
        dedent(
            r"""
            .section .rodata
            msg:
                .pstr "\xE9"
            """,
        ),
    )

    segment = decode_binary_image(result.binary)[0]
    assert word_from_bytes(segment.data[0:WORD_BYTES]) == 1
    assert word_from_bytes(segment.data[WORD_BYTES : WORD_BYTES * 2]) == 0xE9


def test_asm_cli_public_interface_writes_binary_listing_and_map(tmp_path: Path) -> None:
    source = tmp_path / "program.asm"
    target = tmp_path / "program.bin"
    listing = tmp_path / "program.hex"
    source_map = tmp_path / "program.map.json"
    source_text = dedent(
        """\
            .section .vectors
            .word _start
            .word 0
            .space 56

            .section .text
            _start:
                halt
            """
    )
    source.write_text(source_text, encoding="utf-8")

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

    segments = decode_binary_image(target.read_bytes())

    assert completed.stderr == ""
    assert completed.stdout == "source LoC: 8 segments: 2\n"
    assert [(segment.base_address, segment.size, segment.flags) for segment in segments] == [
        (0x000000, 64, SegmentFlag(0)),
        (0x000040, 4, SegmentFlag.EXEC),
    ]
    assert _word_at(segments, 0x000000) == 0x000040
    assert _word_at(segments, 0x000040) == 0x43000000
    assert listing.read_text(encoding="utf-8") == "\n".join(
        [
            "000000 - 0x00000040 - .word 64",
            "000004 - 0x00000000 - .word 0",
            "000008 - 0x00000000 - .word 0",
            "00000C - 0x00000000 - .word 0",
            "000010 - 0x00000000 - .word 0",
            "000014 - 0x00000000 - .word 0",
            "000018 - 0x00000000 - .word 0",
            "00001C - 0x00000000 - .word 0",
            "000020 - 0x00000000 - .word 0",
            "000024 - 0x00000000 - .word 0",
            "000028 - 0x00000000 - .word 0",
            "00002C - 0x00000000 - .word 0",
            "000030 - 0x00000000 - .word 0",
            "000034 - 0x00000000 - .word 0",
            "000038 - 0x00000000 - .word 0",
            "00003C - 0x00000000 - .word 0",
            "000040 - 0x43000000 - halt",
        ],
    )
    assert json.loads(source_map.read_text(encoding="utf-8")) == [
        {"address": 0x000000, "line": 2, "source": ".word _start"},
        {"address": 0x000004, "line": 3, "source": ".word 0"},
        *[{"address": address, "line": 4, "source": ".space 56"} for address in range(0x000008, 0x000040, WORD_BYTES)],
        {"address": 0x000040, "line": 8, "source": "halt"},
    ]


def _word_at(segments: list[Segment], address: int) -> int:
    for segment in segments:
        if segment.flags & SegmentFlag.BSS:
            continue
        start = segment.base_address
        end = start + len(segment.data)
        if start <= address <= end - WORD_BYTES:
            offset = address - start
            return word_from_bytes(segment.data[offset : offset + WORD_BYTES])
    message = f"word not found at 0x{address:06X}"
    raise AssertionError(message)
