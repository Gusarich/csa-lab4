"""ControlUnit integration tests through assembled binary images."""

from __future__ import annotations

from textwrap import dedent
from typing import cast

import pytest

from assembler import assemble
from control_unit import ControlState, ControlUnit, ExecutionMode, SimulationResult, StopReason
from datapath import DataPath
from io_device import InputDevice, InputEvent, InputEventKind, PortController
from isa import Segment, SegmentFlag, decode_binary_image, encode_binary_image, word_to_bytes


def test_runs_simple_port_output_program_to_halt() -> None:
    result = _run_source(
        """
        .section .vectors
        .word _start
        .word 0
        .space 56

        .section .text
        _start:
            li a0, 'A'
            out OUT_DATA, a0
            halt
        """,
    )

    assert result.stdout == "A"
    assert result.stop_reason == StopReason.HALT
    assert result.ticks > 41
    assert any(entry.state == ControlState.RESET_VECTOR and entry.cache is not None for entry in result.log)
    assert any(entry.port_event.startswith("out 0x0011") for entry in result.log)


def test_executes_memory_store_load_through_cache() -> None:
    result = _run_source(
        """
        .section .vectors
        .word _start
        .word 0
        .space 56

        .section .text
        _start:
            li a0, 0x0200
            li t0, 'c'
            sw t0, 0(a0)
            lw a1, 0(a0)
            out OUT_DATA, a1
            halt
        """,
    )

    assert result.stdout == "c"
    assert result.stop_reason == StopReason.HALT
    assert any(entry.state == ControlState.MEM and entry.cache is not None for entry in result.log)


def test_executes_branch_and_jump_control_flow() -> None:
    result = _run_source(
        """
        .section .vectors
        .word _start
        .word 0
        .space 56

        .section .text
        _start:
            li a0, 0
            beq a0, zero, branch_ok
            li a0, 'X'
        branch_ok:
            jal write_y
            j done
        write_y:
            li a0, 'Y'
            out OUT_DATA, a0
            jr ra
        done:
            halt
        """,
    )

    assert result.stdout == "Y"
    assert result.stop_reason == StopReason.HALT
    assert any(
        entry.state == ControlState.EXEC_BRANCH and entry.source == "beq a0, zero, branch_ok" for entry in result.log
    )
    assert any(entry.state == ControlState.EXEC_JUMP and entry.source == "jal write_y" for entry in result.log)
    assert any(entry.state == ControlState.EXEC_JUMP and entry.source == "jr ra" for entry in result.log)
    assert any(entry.state == ControlState.EXEC_JUMP and entry.source == "j done" for entry in result.log)


def test_enters_irq_handler_only_after_instruction_boundary() -> None:
    result = _run_source(
        """
        .section .vectors
        .word _start
        .word irq
        .space 56

        .section .text
        _start:
            ei
        loop:
            j loop
        irq:
            in a0, IN_DATA
            out OUT_DATA, a0
            iret
        """,
        input_events=[InputEvent(100, InputEventKind.BYTE, ord("Q"))],
        max_ticks=180,
    )

    assert result.stdout == "Q"
    assert result.stop_reason == StopReason.STOP_TICK_LIMIT
    assert any(entry.state == ControlState.IRQ_ENTER for entry in result.log)
    assert any(entry.state == ControlState.IRQ_VECTOR for entry in result.log)
    assert any(entry.mode == ExecutionMode.IRQ and entry.port_event.startswith("out 0x0011") for entry in result.log)


def test_pending_input_irq_waits_until_ei_instruction_boundary() -> None:
    result = _run_source(
        """
        .section .vectors
        .word _start
        .word irq
        .space 56

        .section .text
        _start:
            nop
            ei
            halt
        irq:
            in a0, IN_DATA
            out OUT_DATA, a0
            iret
        """,
        input_events=[InputEvent(82, InputEventKind.BYTE, ord("Q"))],
        max_ticks=250,
    )

    input_entry = next(entry for entry in result.log if entry.input_event is not None)
    ei_tick = next(entry.tick for entry in result.log if entry.state == ControlState.EXEC_SYS and entry.source == "ei")
    irq_tick = next(entry.tick for entry in result.log if entry.state == ControlState.IRQ_ENTER)

    assert result.stdout == "Q"
    assert result.stop_reason == StopReason.HALT
    assert input_entry.state == ControlState.EXEC_SYS
    assert input_entry.source == "nop"
    assert input_entry.tick < ei_tick < irq_tick


def test_input_during_cache_wait_is_serviced_after_current_instruction() -> None:
    result = _run_source(
        """
        .section .vectors
        .word _start
        .word irq
        .space 56

        .section .text
        _start:
            ei
            j after_gap

        .org 0x000100
        after_gap:
            li a0, 'M'
            out OUT_DATA, a0
            halt

        irq:
            in a1, IN_DATA
            out OUT_DATA, a1
            iret
        """,
        input_events=[InputEvent(86, InputEventKind.BYTE, ord("Q"))],
        max_ticks=400,
    )

    input_entry = next(entry for entry in result.log if entry.input_event is not None)
    current_instruction_tick = next(
        entry.tick for entry in result.log if entry.state == ControlState.EXEC_ALU and entry.source == "li a0, 'M'"
    )
    irq_tick = next(entry.tick for entry in result.log if entry.state == ControlState.IRQ_ENTER)

    assert result.stdout == "QM"
    assert result.stop_reason == StopReason.HALT
    assert input_entry.state == ControlState.IF
    assert input_entry.cache is not None
    assert input_entry.cache.address == 0x000100
    assert not input_entry.cache.completed
    assert input_entry.tick < current_instruction_tick < irq_tick


def test_irq_repeats_when_handler_does_not_clear_ready() -> None:
    result = _run_source(
        """
        .section .vectors
        .word _start
        .word irq
        .space 56

        .section .text
        _start:
            ei
        loop:
            j loop

        irq:
            li a0, '!'
            out OUT_DATA, a0
            iret
        """,
        input_events=[InputEvent(100, InputEventKind.BYTE, ord("Q"))],
        max_ticks=360,
    )

    irq_entries = [entry for entry in result.log if entry.state == ControlState.IRQ_ENTER]
    iret_entries = [entry for entry in result.log if entry.state == ControlState.EXEC_SYS and entry.source == "iret"]

    assert result.stop_reason == StopReason.STOP_TICK_LIMIT
    assert result.stdout.startswith("!!")
    assert len(irq_entries) >= 2
    assert len(iret_entries) >= 2
    assert all(entry.input_status & 1 for entry in iret_entries[:2])


def test_faults_when_reset_vector_is_zero() -> None:
    program = encode_binary_image([Segment(0, word_to_bytes(0) + bytes(60), SegmentFlag(0))])
    datapath = DataPath.from_segments(decode_binary_image(program))
    result = ControlUnit(datapath).run(max_ticks=50)

    assert result.stop_reason == StopReason.FAULT_NO_RESET_VECTOR
    assert result.ticks == 41


def test_faults_on_unaligned_jump_register_target() -> None:
    result = _run_source(
        """
        .section .vectors
        .word _start
        .word 0
        .space 56

        .section .text
        _start:
            li t0, 0x41
            jr t0
        """,
    )

    assert result.stop_reason == StopReason.FAULT_ADDR
    assert result.log[-1].state == ControlState.EXEC_JUMP


def test_stop_tick_limit_is_visible_on_final_trace_row() -> None:
    result = _run_source(
        """
        .section .vectors
        .word _start
        .word 0
        .space 56

        .section .text
        _start:
            j _start
        """,
        max_ticks=130,
    )

    assert result.stop_reason == StopReason.STOP_TICK_LIMIT
    assert result.ticks == 130
    assert len(result.log) == result.ticks
    assert any(entry.state == ControlState.EXEC_JUMP and entry.source == "j _start" for entry in result.log)
    assert result.log[-1].stop_reason == StopReason.STOP_TICK_LIMIT


def test_cache_completion_ticks_keep_the_state_that_consumed_the_tick() -> None:
    result = _run_source(
        """
        .section .vectors
        .word _start
        .word 0
        .space 56

        .section .text
        _start:
            li a0, 'A'
            out OUT_DATA, a0
            halt
        """,
        max_ticks=160,
    )

    assert any(
        entry.state == ControlState.IF and entry.cache is not None and entry.cache.completed for entry in result.log
    )
    assert not any(entry.state == ControlState.EXEC_ALU and entry.cache is not None for entry in result.log)


def test_instruction_fetch_wait_trace_uses_fetch_source_without_stale_decode() -> None:
    result = _run_source(
        """
        .section .vectors
        .word _start
        .word 0
        .space 56

        .section .text
        _start:
            li a0, 'A'
            j next
        .org 0x000100
        next:
            li a1, 'B'
            halt
        """,
        max_ticks=200,
    )

    wait_entry = next(
        entry
        for entry in result.log
        if entry.state == ControlState.IF
        and entry.cache is not None
        and entry.cache.address == 0x000100
        and not entry.cache.completed
    )
    complete_entry = next(
        entry
        for entry in result.log
        if entry.state == ControlState.IF
        and entry.cache is not None
        and entry.cache.address == 0x000100
        and entry.cache.completed
    )

    assert wait_entry.source == "li a1, 'B'"
    assert wait_entry.decoded == ""
    assert complete_entry.source == "li a1, 'B'"
    assert complete_entry.decoded == "addi a1, zero, 66"


def test_last_word_address_is_valid_but_next_word_faults() -> None:
    valid = _run_source(
        """
        .section .vectors
        .word _start
        .word 0
        .space 56

        .section .text
        _start:
            li a0, 0x00FFFFFC
            lw a1, 0(a0)
            halt
        """,
        max_ticks=300,
    )
    invalid = _run_source(
        """
        .section .vectors
        .word _start
        .word 0
        .space 56

        .section .text
        _start:
            li a0, 0x01000000
            lw a1, 0(a0)
        """,
        max_ticks=300,
    )
    invalid_unaligned = _run_source(
        """
        .section .vectors
        .word _start
        .word 0
        .space 56

        .section .text
        _start:
            li a0, 0x00FFFFFD
            lw a1, 0(a0)
        """,
        max_ticks=300,
    )

    assert valid.stop_reason == StopReason.HALT
    assert invalid.stop_reason == StopReason.FAULT_ADDR
    assert invalid_unaligned.stop_reason == StopReason.FAULT_ADDR


@pytest.mark.parametrize("opcode", ["divu", "remu"])
def test_division_by_zero_stops_with_observable_fault(opcode: str) -> None:
    result = _run_source(
        f"""
        .section .vectors
        .word _start
        .word 0
        .space 56

        .section .text
        _start:
            li a0, 1
            li a1, 0
            {opcode} a2, a0, a1
            halt
        """,
        max_ticks=200,
    )

    assert result.stop_reason == StopReason.FAULT_DIV0
    assert result.log[-1].state == ControlState.EXEC_ALU
    assert result.log[-1].source == f"{opcode} a2, a0, a1"


def _run_source(
    source: str,
    *,
    input_events: list[InputEvent] | None = None,
    max_ticks: int = 1000,
) -> SimulationResult:
    assembly = assemble(dedent(source))
    source_map = {cast(int, entry["address"]): cast(str, entry["source"]) for entry in assembly.source_map}
    ports = PortController(InputDevice(input_events or []))
    datapath = DataPath.from_segments(decode_binary_image(assembly.binary), ports)
    return ControlUnit(datapath, source_map).run(max_ticks)
