"""Passive DataPath signals for the lab 4 processor model."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from cache import ByteAddressableMemory, CacheTick, DirectMappedCache
from io_device import AppliedInputEvent, PortController
from isa import WORD_BYTES, Segment

REGISTER_COUNT = 16
WORD_MASK = 0xFFFFFFFF
SIGN_BIT = 1 << 31


class DataPathError(Exception):
    """Raised when a DataPath signal receives an invalid selector."""


class AluOperation(StrEnum):
    """ALU operation selector."""

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
    PASS = "pass"


class AddressSource(StrEnum):
    """Cache address mux selector."""

    PC = "pc"
    VECTOR = "vector"
    ALU_OUT = "alu_out"


@dataclass(frozen=True)
class DataPathSnapshot:
    """Observable DataPath state for trace logging and tests."""

    registers: tuple[int, ...]
    ir: int
    alu_out: int
    selected_address: int
    input_status: int
    output_length: int
    irq_line: bool


class DataPath:
    """Passive register, ALU, cache, and port block."""

    def __init__(self, memory: ByteAddressableMemory, ports: PortController | None = None) -> None:
        self.registers = [0] * REGISTER_COUNT
        self.ir = 0
        self.alu_out = 0
        self.cache = DirectMappedCache(memory)
        self.ports = ports or PortController()
        self.selected_address = 0

    @classmethod
    def from_segments(cls, segments: list[Segment], ports: PortController | None = None) -> DataPath:
        """Create a DataPath with memory loaded from a binary image."""
        return cls(ByteAddressableMemory.from_segments(segments), ports)

    def latch_ir(self, value: int) -> None:
        """Latch the instruction register."""
        self.ir = value & WORD_MASK

    def latch_alu_out(self, value: int) -> None:
        """Latch ALU_OUT."""
        self.alu_out = value & WORD_MASK

    def read_register(self, register: int) -> int:
        """Read a register; r0 is hardwired to zero."""
        _check_register(register)
        if register == 0:
            return 0
        return self.registers[register]

    def write_register(self, register: int, value: int) -> None:
        """Write a register; writes to r0 are ignored."""
        _check_register(register)
        if register != 0:
            self.registers[register] = value & WORD_MASK

    def select_address_source(self, source: AddressSource, *, pc: int = 0, vector: int = 0) -> int:
        """Select the cache address mux output."""
        if source == AddressSource.PC:
            self.selected_address = pc & WORD_MASK
        elif source == AddressSource.VECTOR:
            self.selected_address = vector & WORD_MASK
        elif source == AddressSource.ALU_OUT:
            self.selected_address = self.alu_out
        else:
            raise DataPathError("unknown address source: {}".format(source))
        return self.selected_address

    def cache_read(self, address: int) -> None:
        """Start a cache read access."""
        self.cache.begin_read(address)

    def cache_write(self, address: int, value: int) -> None:
        """Start a cache write access."""
        self.cache.begin_write(address, value)

    def cache_tick(self) -> CacheTick:
        """Advance an active cache access by one tick."""
        return self.cache.tick()

    def cache_busy(self) -> bool:
        """Return whether the cache has an active access."""
        return self.cache.is_busy()

    def port_read(self, port: int) -> int:
        """Read an I/O port."""
        return self.ports.read(port)

    def port_write(self, port: int, value: int) -> None:
        """Write an I/O port."""
        self.ports.write(port, value)

    def apply_input_tick(self, tick: int) -> AppliedInputEvent | None:
        """Apply scheduled input at the beginning of a model tick."""
        return self.ports.apply_tick(tick)

    def irq_line(self) -> bool:
        """Return the input IRQ line."""
        return self.ports.irq_line()

    def output_text(self) -> str:
        """Return accumulated output."""
        return self.ports.output_text()

    def input_status(self) -> int:
        """Return current input status bits."""
        return self.ports.input_status()

    def output_length(self) -> int:
        """Return output buffer length."""
        return self.ports.output_length()

    def alu_execute(self, operation: AluOperation, lhs: int, rhs: int) -> int:
        """Execute one combinational ALU operation."""
        lhs &= WORD_MASK
        rhs &= WORD_MASK
        operation_func = ALU_FUNCTIONS.get(operation)
        if operation_func is None:
            raise DataPathError("unknown ALU operation: {}".format(operation))
        return operation_func(lhs, rhs)

    def snapshot(self) -> DataPathSnapshot:
        """Return observable state."""
        return DataPathSnapshot(
            registers=tuple(self.read_register(index) for index in range(REGISTER_COUNT)),
            ir=self.ir,
            alu_out=self.alu_out,
            selected_address=self.selected_address,
            input_status=self.input_status(),
            output_length=self.output_length(),
            irq_line=self.irq_line(),
        )


def sign_extend_16(value: int) -> int:
    """Sign-extend a 16-bit value to Python int."""
    value &= 0xFFFF
    if value & 0x8000:
        return value - 0x10000
    return value


def validate_word_address(address: int) -> bool:
    """Return whether an address is a valid aligned word address."""
    return 0 <= address <= 0xFFFFFF - (WORD_BYTES - 1) and address % WORD_BYTES == 0


def _divide_unsigned(lhs: int, rhs: int) -> int:
    if rhs == 0:
        raise ZeroDivisionError
    return lhs // rhs


def _remainder_unsigned(lhs: int, rhs: int) -> int:
    if rhs == 0:
        raise ZeroDivisionError
    return lhs % rhs


AluFunction = Callable[[int, int], int]
ALU_FUNCTIONS: dict[AluOperation, AluFunction] = {
    AluOperation.ADD: lambda lhs, rhs: (lhs + rhs) & WORD_MASK,
    AluOperation.SUB: lambda lhs, rhs: (lhs - rhs) & WORD_MASK,
    AluOperation.MUL: lambda lhs, rhs: (lhs * rhs) & WORD_MASK,
    AluOperation.MULHU: lambda lhs, rhs: ((lhs * rhs) >> 32) & WORD_MASK,
    AluOperation.DIVU: _divide_unsigned,
    AluOperation.REMU: _remainder_unsigned,
    AluOperation.AND: lambda lhs, rhs: lhs & rhs,
    AluOperation.OR: lambda lhs, rhs: lhs | rhs,
    AluOperation.XOR: lambda lhs, rhs: lhs ^ rhs,
    AluOperation.SLL: lambda lhs, rhs: (lhs << (rhs & 31)) & WORD_MASK,
    AluOperation.SRL: lambda lhs, rhs: lhs >> (rhs & 31),
    AluOperation.SRA: lambda lhs, rhs: (_to_signed(lhs) >> (rhs & 31)) & WORD_MASK,
    AluOperation.SLT: lambda lhs, rhs: int(_to_signed(lhs) < _to_signed(rhs)),
    AluOperation.SLTU: lambda lhs, rhs: int(lhs < rhs),
    AluOperation.PASS: lambda lhs, _rhs: lhs,
}


def _to_signed(value: int) -> int:
    value &= WORD_MASK
    if value & SIGN_BIT:
        return value - (1 << 32)
    return value


def _check_register(register: int) -> None:
    if not 0 <= register < REGISTER_COUNT:
        raise DataPathError("register out of range: {}".format(register))
