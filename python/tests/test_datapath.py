"""Tests for passive DataPath signals."""

from __future__ import annotations

import pytest

from cache import ByteAddressableMemory, CachePhase
from datapath import AddressSource, AluOperation, DataPath, DataPathError, sign_extend_16, validate_word_address
from io_device import InputDevice, InputEvent, InputEventKind, PortController
from isa import IN_DATA, OUT_DATA


def test_register_file_keeps_zero_register_immutable_and_latches_state() -> None:
    datapath = DataPath(ByteAddressableMemory())

    datapath.write_register(0, 0xFFFFFFFF)
    datapath.write_register(1, 0x1_0000_0001)
    datapath.latch_ir(0x1_2345_6789)
    datapath.latch_alu_out(0xFFFF_FFFF_F)

    assert datapath.read_register(0) == 0
    assert datapath.read_register(1) == 1
    assert datapath.ir == 0x23456789
    assert datapath.alu_out == 0xFFFFFFFF
    with pytest.raises(DataPathError):
        datapath.read_register(16)


def test_address_mux_selects_pc_vector_and_alu_out() -> None:
    datapath = DataPath(ByteAddressableMemory())
    datapath.latch_alu_out(0x200)

    assert datapath.select_address_source(AddressSource.PC, pc=0x40) == 0x40
    assert datapath.select_address_source(AddressSource.VECTOR, vector=0x04) == 0x04
    assert datapath.select_address_source(AddressSource.ALU_OUT) == 0x200


@pytest.mark.parametrize(
    ("operation", "lhs", "rhs", "expected"),
    [
        (AluOperation.ADD, 0xFFFFFFFF, 1, 0),
        (AluOperation.SUB, 0, 1, 0xFFFFFFFF),
        (AluOperation.MUL, 0xFFFFFFFF, 0xFFFFFFFF, 1),
        (AluOperation.MULHU, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFE),
        (AluOperation.DIVU, 7, 3, 2),
        (AluOperation.REMU, 7, 3, 1),
        (AluOperation.AND, 0b1100, 0b1010, 0b1000),
        (AluOperation.OR, 0b1100, 0b1010, 0b1110),
        (AluOperation.XOR, 0b1100, 0b1010, 0b0110),
        (AluOperation.SLL, 1, 33, 2),
        (AluOperation.SRL, 0x80000000, 31, 1),
        (AluOperation.SRA, 0x80000000, 31, 0xFFFFFFFF),
        (AluOperation.SLT, 0xFFFFFFFF, 0, 1),
        (AluOperation.SLTU, 0xFFFFFFFF, 0, 0),
        (AluOperation.PASS, 0xABCDEF01, 0, 0xABCDEF01),
    ],
)
def test_alu_operations(operation: AluOperation, lhs: int, rhs: int, expected: int) -> None:
    datapath = DataPath(ByteAddressableMemory())
    assert datapath.alu_execute(operation, lhs, rhs) == expected


def test_alu_division_by_zero_is_observable_fault_input() -> None:
    datapath = DataPath(ByteAddressableMemory())
    with pytest.raises(ZeroDivisionError):
        datapath.alu_execute(AluOperation.DIVU, 1, 0)
    with pytest.raises(ZeroDivisionError):
        datapath.alu_execute(AluOperation.REMU, 1, 0)


def test_cache_and_port_signals_are_forwarded() -> None:
    memory = ByteAddressableMemory()
    memory.write_word(0, 0x12345678)
    ports = PortController(InputDevice([InputEvent(1, InputEventKind.BYTE, ord("A"))]))
    datapath = DataPath(memory, ports)

    datapath.cache_read(0)
    ticks = []
    while datapath.cache_busy():
        ticks.append(datapath.cache_tick())
    assert ticks[-1].phase == CachePhase.FILL
    assert ticks[-1].value == 0x12345678

    assert datapath.apply_input_tick(1) is not None
    assert datapath.irq_line()
    assert datapath.port_read(IN_DATA) == ord("A")
    datapath.port_write(OUT_DATA, ord("B"))
    assert datapath.output_text() == "B"


def test_helpers_for_immediates_and_word_addresses() -> None:
    assert sign_extend_16(0xFFFF) == -1
    assert sign_extend_16(0x7FFF) == 32767
    assert validate_word_address(0xFFFFFC)
    assert not validate_word_address(0xFFFFFF)
    assert not validate_word_address(2)
