"""ControlUnit integration tests through assembled binary images."""

from __future__ import annotations

from textwrap import dedent
from typing import cast

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
        """
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
        """
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
            beq a0, zero, ok
            li a0, 'X'
        ok:
            li a0, 'Y'
            out OUT_DATA, a0
            halt
        """
    )

    assert result.stdout == "Y"
    assert result.stop_reason == StopReason.HALT


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
        """
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
        max_ticks=50,
    )

    assert result.stop_reason == StopReason.STOP_TICK_LIMIT
    assert result.ticks == 50
    assert len(result.log) == result.ticks
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

    assert valid.stop_reason == StopReason.HALT
    assert invalid.stop_reason == StopReason.FAULT_ADDR


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
