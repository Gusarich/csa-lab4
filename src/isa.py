"""Instruction encoding and binary image support for the lab 4 machine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntFlag, StrEnum

WORD_BITS = 32
WORD_BYTES = 4
MEMORY_ADDRESS_BITS = 24
MEMORY_SIZE = 1 << MEMORY_ADDRESS_BITS
MAX_ADDRESS = MEMORY_SIZE - 1
MAX_WORD_ADDRESS = MAX_ADDRESS - (WORD_BYTES - 1)
RESET_VECTOR_ADDRESS = 0x000000
INPUT_VECTOR_ADDRESS = 0x000004

BINARY_MAGIC = b"L4MC"
BINARY_VERSION = 1


class IsaError(Exception):
    """Base class for ISA and binary image errors."""


class EncodingError(IsaError):
    """Raised when an instruction cannot be encoded."""


class DecodingError(IsaError):
    """Raised when a machine word is not a valid instruction."""


class BinaryImageError(IsaError):
    """Raised when a binary image violates the L4MC container format."""


class InstructionFormat(StrEnum):
    """Fixed 32-bit instruction formats."""

    R_TYPE = "R"
    I_TYPE = "I"
    B_TYPE = "B"
    J_TYPE = "J"
    P_TYPE = "P"
    Z_TYPE = "Z"


class Opcode(StrEnum):
    """Instruction mnemonics."""

    NOP = "nop"
    ADD = "add"
    SUB = "sub"
    MUL = "mul"
    MULHU = "mulhu"
    DIVU = "divu"
    REMU = "remu"
    AND = "and"
    OR = "or"
    XOR = "xor"
    SLL = "sll"
    SRL = "srl"
    SRA = "sra"
    SLT = "slt"
    SLTU = "sltu"
    ADDI = "addi"
    ANDI = "andi"
    ORI = "ori"
    XORI = "xori"
    LUI = "lui"
    LW = "lw"
    SW = "sw"
    BEQ = "beq"
    BNE = "bne"
    BLT = "blt"
    BGE = "bge"
    BLTU = "bltu"
    BGEU = "bgeu"
    J = "j"
    JAL = "jal"
    JR = "jr"
    HALT = "halt"
    IN = "in"
    OUT = "out"
    EI = "ei"
    DI = "di"
    IRET = "iret"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class InstructionSpec:
    """Opcode number and structural format for one instruction."""

    opcode: Opcode
    code: int
    instr_format: InstructionFormat


@dataclass(frozen=True)
class Instruction:
    """Decoded instruction fields.

    Field meanings depend on the instruction format. Reserved bits are not
    stored because a successfully decoded instruction always has them cleared.
    """

    opcode: Opcode
    rd: int = 0
    rs1: int = 0
    rs2: int = 0
    imm16: int = 0
    addr24: int = 0
    port16: int = 0


class SegmentFlag(IntFlag):
    """Flags stored in a binary image segment header."""

    EXEC = 1
    WRITE = 2
    BSS = 4


@dataclass(frozen=True)
class Segment:
    """A byte-addressed L4MC binary image segment."""

    base_address: int
    data: bytes
    flags: SegmentFlag
    byte_count: int | None = None

    @property
    def size(self) -> int:
        if self.byte_count is not None:
            return self.byte_count
        return len(self.data)


REGISTER_NAMES = (
    "zero",
    "a0",
    "a1",
    "a2",
    "a3",
    "t0",
    "t1",
    "t2",
    "t3",
    "t4",
    "t5",
    "rv",
    "k0",
    "k1",
    "sp",
    "ra",
)

REGISTER_BY_NAME = {name: number for number, name in enumerate(REGISTER_NAMES)}
REGISTER_BY_NAME.update({f"r{number}": number for number in range(len(REGISTER_NAMES))})

IN_STATUS = 0x0000
IN_DATA = 0x0001
IN_CTRL = 0x0002
OUT_STATUS = 0x0010
OUT_DATA = 0x0011


INSTRUCTION_SPECS = (
    InstructionSpec(Opcode.NOP, 0x00, InstructionFormat.Z_TYPE),
    InstructionSpec(Opcode.ADD, 0x01, InstructionFormat.R_TYPE),
    InstructionSpec(Opcode.SUB, 0x02, InstructionFormat.R_TYPE),
    InstructionSpec(Opcode.MUL, 0x03, InstructionFormat.R_TYPE),
    InstructionSpec(Opcode.MULHU, 0x04, InstructionFormat.R_TYPE),
    InstructionSpec(Opcode.DIVU, 0x05, InstructionFormat.R_TYPE),
    InstructionSpec(Opcode.REMU, 0x06, InstructionFormat.R_TYPE),
    InstructionSpec(Opcode.AND, 0x07, InstructionFormat.R_TYPE),
    InstructionSpec(Opcode.OR, 0x08, InstructionFormat.R_TYPE),
    InstructionSpec(Opcode.XOR, 0x09, InstructionFormat.R_TYPE),
    InstructionSpec(Opcode.SLL, 0x0A, InstructionFormat.R_TYPE),
    InstructionSpec(Opcode.SRL, 0x0B, InstructionFormat.R_TYPE),
    InstructionSpec(Opcode.SRA, 0x0C, InstructionFormat.R_TYPE),
    InstructionSpec(Opcode.SLT, 0x0D, InstructionFormat.R_TYPE),
    InstructionSpec(Opcode.SLTU, 0x0E, InstructionFormat.R_TYPE),
    InstructionSpec(Opcode.ADDI, 0x10, InstructionFormat.I_TYPE),
    InstructionSpec(Opcode.ANDI, 0x11, InstructionFormat.I_TYPE),
    InstructionSpec(Opcode.ORI, 0x12, InstructionFormat.I_TYPE),
    InstructionSpec(Opcode.XORI, 0x13, InstructionFormat.I_TYPE),
    InstructionSpec(Opcode.LUI, 0x14, InstructionFormat.I_TYPE),
    InstructionSpec(Opcode.LW, 0x20, InstructionFormat.I_TYPE),
    InstructionSpec(Opcode.SW, 0x21, InstructionFormat.I_TYPE),
    InstructionSpec(Opcode.BEQ, 0x30, InstructionFormat.B_TYPE),
    InstructionSpec(Opcode.BNE, 0x31, InstructionFormat.B_TYPE),
    InstructionSpec(Opcode.BLT, 0x32, InstructionFormat.B_TYPE),
    InstructionSpec(Opcode.BGE, 0x33, InstructionFormat.B_TYPE),
    InstructionSpec(Opcode.BLTU, 0x34, InstructionFormat.B_TYPE),
    InstructionSpec(Opcode.BGEU, 0x35, InstructionFormat.B_TYPE),
    InstructionSpec(Opcode.J, 0x40, InstructionFormat.J_TYPE),
    InstructionSpec(Opcode.JAL, 0x41, InstructionFormat.J_TYPE),
    InstructionSpec(Opcode.JR, 0x42, InstructionFormat.R_TYPE),
    InstructionSpec(Opcode.HALT, 0x43, InstructionFormat.Z_TYPE),
    InstructionSpec(Opcode.IN, 0x50, InstructionFormat.P_TYPE),
    InstructionSpec(Opcode.OUT, 0x51, InstructionFormat.P_TYPE),
    InstructionSpec(Opcode.EI, 0x60, InstructionFormat.Z_TYPE),
    InstructionSpec(Opcode.DI, 0x61, InstructionFormat.Z_TYPE),
    InstructionSpec(Opcode.IRET, 0x62, InstructionFormat.Z_TYPE),
)

SPEC_BY_OPCODE = {spec.opcode: spec for spec in INSTRUCTION_SPECS}
SPEC_BY_CODE = {spec.code: spec for spec in INSTRUCTION_SPECS}


def register_number(name: str) -> int:
    """Return a register number for an architectural register name."""
    try:
        return REGISTER_BY_NAME[name]
    except KeyError as exc:
        message = f"unknown register: {name}"
        raise EncodingError(message) from exc


def register_name(number: int) -> str:
    """Return the canonical architectural name of a register."""
    _check_u4(number, "register")
    return REGISTER_NAMES[number]


def encode_instruction(instruction: Instruction) -> int:
    """Encode one instruction into a 32-bit machine word."""
    spec = SPEC_BY_OPCODE[instruction.opcode]
    opcode = spec.code << 24
    if spec.instr_format == InstructionFormat.R_TYPE:
        _check_u4(instruction.rd, "rd")
        _check_u4(instruction.rs1, "rs1")
        _check_u4(instruction.rs2, "rs2")
        return opcode | (instruction.rd << 20) | (instruction.rs1 << 16) | (instruction.rs2 << 12)
    if spec.instr_format == InstructionFormat.I_TYPE:
        _check_u4(instruction.rd, "rd")
        _check_u4(instruction.rs1, "rs1")
        _check_u16(instruction.imm16, "imm16")
        return opcode | (instruction.rd << 20) | (instruction.rs1 << 16) | instruction.imm16
    if spec.instr_format == InstructionFormat.B_TYPE:
        _check_u4(instruction.rs1, "rs1")
        _check_u4(instruction.rs2, "rs2")
        _check_u16(instruction.imm16, "off16")
        return opcode | (instruction.rs1 << 20) | (instruction.rs2 << 16) | instruction.imm16
    if spec.instr_format == InstructionFormat.J_TYPE:
        _check_u24(instruction.addr24, "addr24")
        return opcode | instruction.addr24
    if spec.instr_format == InstructionFormat.P_TYPE:
        _check_u4(instruction.rd, "reg")
        _check_u16(instruction.port16, "port16")
        return opcode | (instruction.rd << 20) | instruction.port16
    return opcode


def decode_instruction(word: int) -> Instruction:
    """Decode and validate one 32-bit machine word."""
    _check_u32(word, "word")
    opcode_code = (word >> 24) & 0xFF
    spec = SPEC_BY_CODE.get(opcode_code)
    if spec is None:
        message = f"unknown opcode: 0x{opcode_code:02X}"
        raise DecodingError(message)
    if spec.instr_format == InstructionFormat.R_TYPE:
        _check_reserved(word & 0xFFF)
        rd = (word >> 20) & 0xF
        rs1 = (word >> 16) & 0xF
        rs2 = (word >> 12) & 0xF
        _check_jr_encoding(spec.opcode, rd, rs2)
        return Instruction(spec.opcode, rd=rd, rs1=rs1, rs2=rs2)
    if spec.instr_format == InstructionFormat.I_TYPE:
        rd = (word >> 20) & 0xF
        rs1 = (word >> 16) & 0xF
        _check_lui_encoding(spec.opcode, rs1)
        return Instruction(spec.opcode, rd=rd, rs1=rs1, imm16=word & 0xFFFF)
    if spec.instr_format == InstructionFormat.B_TYPE:
        return Instruction(spec.opcode, rs1=(word >> 20) & 0xF, rs2=(word >> 16) & 0xF, imm16=word & 0xFFFF)
    if spec.instr_format == InstructionFormat.J_TYPE:
        return Instruction(spec.opcode, addr24=word & 0xFFFFFF)
    if spec.instr_format == InstructionFormat.P_TYPE:
        _check_reserved((word >> 16) & 0xF)
        return Instruction(spec.opcode, rd=(word >> 20) & 0xF, port16=word & 0xFFFF)
    _check_reserved(word & 0xFFFFFF)
    return Instruction(spec.opcode)


def instruction_to_bytes(instruction: Instruction) -> bytes:
    """Encode one instruction as a big-endian 32-bit word."""
    return word_to_bytes(encode_instruction(instruction))


def word_to_bytes(word: int) -> bytes:
    """Convert one unsigned 32-bit word to big-endian bytes."""
    _check_u32(word, "word")
    return word.to_bytes(WORD_BYTES, "big")


def word_from_bytes(data: bytes) -> int:
    """Convert exactly four big-endian bytes to one unsigned word."""
    if len(data) != WORD_BYTES:
        message = "word requires exactly 4 bytes"
        raise BinaryImageError(message)
    return int.from_bytes(data, "big")


def sign_extend(value: int, bits: int) -> int:
    """Sign-extend an integer field of the given bit width."""
    sign = 1 << (bits - 1)
    mask = (1 << bits) - 1
    value &= mask
    return (value ^ sign) - sign


def encode_signed_16(value: int) -> int:
    """Encode a signed 16-bit integer as an unsigned field."""
    if not -(1 << 15) <= value < (1 << 15):
        message = f"signed 16-bit value out of range: {value}"
        raise EncodingError(message)
    return value & 0xFFFF


def disassemble(instruction: Instruction) -> str:
    """Return the canonical assembly spelling of a decoded instruction."""
    spec = SPEC_BY_OPCODE[instruction.opcode]
    mnemonic = instruction.opcode.value
    if spec.instr_format == InstructionFormat.R_TYPE:
        return _disassemble_r(instruction)
    if spec.instr_format == InstructionFormat.I_TYPE:
        return _disassemble_i(instruction)
    if spec.instr_format == InstructionFormat.B_TYPE:
        return (
            f"{mnemonic} {register_name(instruction.rs1)}, "
            f"{register_name(instruction.rs2)}, {sign_extend(instruction.imm16, 16)}"
        )
    if spec.instr_format == InstructionFormat.J_TYPE:
        return f"{mnemonic} 0x{instruction.addr24:06X}"
    if spec.instr_format == InstructionFormat.P_TYPE:
        return _disassemble_p(instruction)
    return mnemonic


def encode_binary_image(segments: list[Segment]) -> bytes:
    """Encode segments into the L4MC binary container."""
    validate_segments(segments)
    result = bytearray()
    result.extend(BINARY_MAGIC)
    result.extend(BINARY_VERSION.to_bytes(2, "big"))
    result.extend(len(segments).to_bytes(2, "big"))
    for segment in segments:
        result.extend(segment.base_address.to_bytes(4, "big"))
        result.extend(segment.size.to_bytes(4, "big"))
        result.extend(int(segment.flags).to_bytes(4, "big"))
        if not segment.flags & SegmentFlag.BSS:
            result.extend(segment.data)
    return bytes(result)


def decode_binary_image(data: bytes) -> list[Segment]:
    """Decode and validate an L4MC binary image."""
    segment_count = _decode_binary_header(data)
    offset = 8
    segments = []
    for _ in range(segment_count):
        segment, offset = _decode_segment(data, offset)
        segments.append(segment)
    if offset != len(data):
        message = "trailing bytes after binary image"
        raise BinaryImageError(message)
    validate_segments(segments)
    return segments


def validate_segments(segments: list[Segment]) -> None:
    """Validate segment ranges, payload sizes, flags, and overlaps."""
    ranges = []
    for segment in segments:
        _validate_segment(segment)
        if segment.size > 0:
            ranges.append((segment.base_address, segment.base_address + segment.size - 1))
    for left_index, left in enumerate(ranges):
        for right in ranges[left_index + 1 :]:
            if left[0] <= right[1] and right[0] <= left[1]:
                message = "overlapping binary image segments"
                raise BinaryImageError(message)


def listing_line(address: int, word: int, mnemonic: str) -> str:
    """Format a required debug listing line."""
    _check_address(address)
    _check_u32(word, "word")
    return f"{address:06X} - 0x{word:08X} - {mnemonic}"


def _decode_binary_header(data: bytes) -> int:
    if len(data) < 8:
        message = "binary image is shorter than header"
        raise BinaryImageError(message)
    if data[:4] != BINARY_MAGIC:
        message = "bad binary image magic"
        raise BinaryImageError(message)
    version = int.from_bytes(data[4:6], "big")
    if version != BINARY_VERSION:
        message = f"unsupported binary image version: {version}"
        raise BinaryImageError(message)
    return int.from_bytes(data[6:8], "big")


def _decode_segment(data: bytes, offset: int) -> tuple[Segment, int]:
    if offset + 12 > len(data):
        message = "truncated segment header"
        raise BinaryImageError(message)
    base_address = int.from_bytes(data[offset : offset + 4], "big")
    byte_count = int.from_bytes(data[offset + 4 : offset + 8], "big")
    flags = SegmentFlag(int.from_bytes(data[offset + 8 : offset + 12], "big"))
    offset += 12
    if flags & SegmentFlag.BSS:
        return Segment(base_address, b"", flags, byte_count=byte_count), offset
    if offset + byte_count > len(data):
        message = "truncated segment payload"
        raise BinaryImageError(message)
    payload = data[offset : offset + byte_count]
    return Segment(base_address, payload, flags), offset + byte_count


def _disassemble_r(instruction: Instruction) -> str:
    if instruction.opcode == Opcode.JR:
        return f"jr {register_name(instruction.rs1)}"
    return (
        f"{instruction.opcode.value} {register_name(instruction.rd)}, "
        f"{register_name(instruction.rs1)}, {register_name(instruction.rs2)}"
    )


def _disassemble_i(instruction: Instruction) -> str:
    if instruction.opcode == Opcode.LW:
        return (
            f"lw {register_name(instruction.rd)}, "
            f"{sign_extend(instruction.imm16, 16)}({register_name(instruction.rs1)})"
        )
    if instruction.opcode == Opcode.SW:
        return (
            f"sw {register_name(instruction.rd)}, "
            f"{sign_extend(instruction.imm16, 16)}({register_name(instruction.rs1)})"
        )
    imm = instruction.imm16
    if instruction.opcode == Opcode.ADDI:
        imm = sign_extend(imm, 16)
    if instruction.opcode == Opcode.LUI:
        return f"lui {register_name(instruction.rd)}, {imm}"
    return f"{instruction.opcode.value} {register_name(instruction.rd)}, {register_name(instruction.rs1)}, {imm}"


def _disassemble_p(instruction: Instruction) -> str:
    if instruction.opcode == Opcode.IN:
        return f"in {register_name(instruction.rd)}, 0x{instruction.port16:04X}"
    return f"out 0x{instruction.port16:04X}, {register_name(instruction.rd)}"


def _validate_segment(segment: Segment) -> None:
    flags = int(segment.flags)
    if flags & ~int(SegmentFlag.EXEC | SegmentFlag.WRITE | SegmentFlag.BSS):
        message = f"unknown segment flags: {flags}"
        raise BinaryImageError(message)
    _check_address(segment.base_address)
    if segment.size < 0:
        message = "negative segment size"
        raise BinaryImageError(message)
    if segment.flags & SegmentFlag.BSS and len(segment.data) != 0:
        message = "BSS segment must not contain payload"
        raise BinaryImageError(message)
    if not segment.flags & SegmentFlag.BSS and segment.size != len(segment.data):
        message = "segment payload size mismatch"
        raise BinaryImageError(message)
    if segment.size > 0 and segment.base_address + segment.size - 1 > MAX_ADDRESS:
        message = "segment exceeds address space"
        raise BinaryImageError(message)


def _check_reserved(value: int) -> None:
    if value != 0:
        message = "reserved instruction bits are not zero"
        raise DecodingError(message)


def _check_lui_encoding(opcode: Opcode, rs1: int) -> None:
    if opcode == Opcode.LUI and rs1 != 0:
        message = "lui rs1 field must be zero"
        raise DecodingError(message)


def _check_jr_encoding(opcode: Opcode, rd: int, rs2: int) -> None:
    if opcode == Opcode.JR and (rd != 0 or rs2 != 0):
        message = "jr rd and rs2 fields must be zero"
        raise DecodingError(message)


def _check_address(address: int) -> None:
    if not 0 <= address <= MAX_ADDRESS:
        message = f"address out of range: {address}"
        raise EncodingError(message)


def _check_u4(value: int, field: str) -> None:
    if not 0 <= value <= 0xF:
        message = f"{field} out of range: {value}"
        raise EncodingError(message)


def _check_u16(value: int, field: str) -> None:
    if not 0 <= value <= 0xFFFF:
        message = f"{field} out of range: {value}"
        raise EncodingError(message)


def _check_u24(value: int, field: str) -> None:
    if not 0 <= value <= 0xFFFFFF:
        message = f"{field} out of range: {value}"
        raise EncodingError(message)


def _check_u32(value: int, field: str) -> None:
    if not 0 <= value <= 0xFFFFFFFF:
        message = f"{field} out of range: {value}"
        raise EncodingError(message)
