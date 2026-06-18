"""Tests for instruction encoding and binary image support."""

from __future__ import annotations

import pytest

from isa import (
    BinaryImageError,
    DecodingError,
    EncodingError,
    Instruction,
    Opcode,
    Segment,
    SegmentFlag,
    decode_binary_image,
    decode_instruction,
    disassemble,
    encode_binary_image,
    encode_instruction,
    encode_signed_16,
    listing_line,
    register_name,
    register_number,
    sign_extend,
    word_from_bytes,
    word_to_bytes,
)


def test_register_names_are_canonical() -> None:
    assert register_number("zero") == 0
    assert register_number("r0") == 0
    assert register_number("sp") == 14
    assert register_name(15) == "ra"


def test_register_lookup_rejects_unknown_names() -> None:
    with pytest.raises(EncodingError, match="unknown register"):
        register_number("pc")


def test_encode_decode_r_format() -> None:
    instruction = Instruction(Opcode.ADD, rd=1, rs1=2, rs2=3)
    word = encode_instruction(instruction)

    assert word == 0x01123000
    assert decode_instruction(word) == instruction
    assert disassemble(instruction) == "add a0, a1, a2"


def test_encode_decode_i_format() -> None:
    instruction = Instruction(Opcode.ADDI, rd=5, rs1=14, imm16=encode_signed_16(-4))
    word = encode_instruction(instruction)

    assert word == 0x105EFFFC
    assert decode_instruction(word) == instruction
    assert disassemble(instruction) == "addi t0, sp, -4"


def test_encode_decode_memory_i_format() -> None:
    load = Instruction(Opcode.LW, rd=1, rs1=14, imm16=8)
    store = Instruction(Opcode.SW, rd=5, rs1=14, imm16=encode_signed_16(-4))
    load_word = encode_instruction(load)
    store_word = encode_instruction(store)

    assert load_word == 0x201E0008
    assert store_word == 0x215EFFFC
    assert decode_instruction(load_word) == load
    assert decode_instruction(store_word) == store
    assert disassemble(load) == "lw a0, 8(sp)"
    assert disassemble(store) == "sw t0, -4(sp)"


def test_encode_decode_branch_format() -> None:
    instruction = Instruction(Opcode.BNE, rs1=1, rs2=2, imm16=encode_signed_16(-16))
    word = encode_instruction(instruction)

    assert word == 0x3112FFF0
    assert decode_instruction(word) == instruction
    assert disassemble(instruction) == "bne a0, a1, -16"


def test_encode_decode_jump_format() -> None:
    instruction = Instruction(Opcode.JAL, addr24=0x000080)
    word = encode_instruction(instruction)

    assert word == 0x41000080
    assert decode_instruction(word) == instruction
    assert disassemble(instruction) == "jal 0x000080"


def test_encode_decode_port_format() -> None:
    instruction = Instruction(Opcode.OUT, rd=1, port16=0x0011)
    word = encode_instruction(instruction)

    assert word == 0x51100011
    assert decode_instruction(word) == instruction
    assert disassemble(instruction) == "out 0x0011, a0"


def test_encode_decode_z_format() -> None:
    instruction = Instruction(Opcode.HALT)
    word = encode_instruction(instruction)

    assert word == 0x43000000
    assert decode_instruction(word) == instruction
    assert disassemble(instruction) == "halt"


def test_decode_rejects_reserved_bits() -> None:
    bad_r = 0x01123001
    bad_z = 0x43000001
    bad_p = 0x51110011

    with pytest.raises(DecodingError, match="reserved"):
        decode_instruction(bad_r)
    with pytest.raises(DecodingError, match="reserved"):
        decode_instruction(bad_z)
    with pytest.raises(DecodingError, match="reserved"):
        decode_instruction(bad_p)


def test_decode_rejects_lui_and_jr_bad_encoding() -> None:
    with pytest.raises(DecodingError, match="lui"):
        decode_instruction(0x14110000)
    with pytest.raises(DecodingError, match="jr"):
        decode_instruction(0x42112000)


def test_word_big_endian_roundtrip() -> None:
    assert word_to_bytes(0x12345678) == b"\x12\x34\x56\x78"
    assert word_from_bytes(b"\x12\x34\x56\x78") == 0x12345678


def test_word_from_bytes_requires_exact_word_size() -> None:
    with pytest.raises(BinaryImageError, match="exactly 4"):
        word_from_bytes(b"\x00")


def test_sign_extension_helpers() -> None:
    assert encode_signed_16(-1) == 0xFFFF
    assert sign_extend(0xFFFF, 16) == -1
    assert sign_extend(0x7FFF, 16) == 32767


def test_signed_16_rejects_out_of_range_values() -> None:
    with pytest.raises(EncodingError, match="signed 16-bit"):
        encode_signed_16(32768)


def test_binary_image_roundtrip_with_bss() -> None:
    segments = [
        Segment(0x000000, b"\x00\x00\x00\x40", SegmentFlag.EXEC),
        Segment(0x000200, b"\x12\x34\x56\x78", SegmentFlag.WRITE),
        Segment(0x000300, b"", SegmentFlag.WRITE | SegmentFlag.BSS, byte_count=16),
    ]

    image = encode_binary_image(segments)
    decoded = decode_binary_image(image)

    assert image.hex() == (
        "4c344d43000100030000000000000004000000010000004000000200000000040000000212345678000003000000001000000006"
    )
    assert decoded == segments


def test_binary_image_rejects_overlaps() -> None:
    segments = [
        Segment(0x000100, b"\x00" * 16, SegmentFlag.EXEC),
        Segment(0x00010F, b"\x00" * 4, SegmentFlag.WRITE),
    ]

    with pytest.raises(BinaryImageError, match="overlapping"):
        encode_binary_image(segments)


def test_binary_image_rejects_bss_payload() -> None:
    segment = Segment(0x000100, b"\x00", SegmentFlag.BSS, byte_count=1)

    with pytest.raises(BinaryImageError, match="BSS"):
        encode_binary_image([segment])


def test_binary_image_rejects_bad_magic_and_version() -> None:
    good = bytearray(encode_binary_image([]))
    bad_magic = bytearray(good)
    bad_magic[:4] = b"NOPE"
    bad_version = bytearray(good)
    bad_version[4:6] = b"\x00\x02"

    with pytest.raises(BinaryImageError, match="magic"):
        decode_binary_image(bytes(bad_magic))
    with pytest.raises(BinaryImageError, match="version"):
        decode_binary_image(bytes(bad_version))


def test_listing_line_uses_required_format() -> None:
    assert listing_line(0x40, 0x10100064, "addi a0, zero, 100") == ("000040 - 0x10100064 - addi a0, zero, 100")
