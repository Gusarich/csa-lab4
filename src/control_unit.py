"""Hardwired tick-accurate Control Unit."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from cache import CacheAccessError, CacheTick, MemoryAccessError
from datapath import AddressSource, AluOperation, DataPath, _to_signed, sign_extend_16, validate_word_address
from io_device import AppliedInputEvent, PortAccessError
from isa import (
    INPUT_VECTOR_ADDRESS,
    RESET_VECTOR_ADDRESS,
    SPEC_BY_OPCODE,
    WORD_BYTES,
    DecodingError,
    Instruction,
    InstructionFormat,
    Opcode,
    decode_instruction,
    disassemble,
)

WORD_MASK = 0xFFFFFFFF
STATUS_IE = 1 << 0
STATUS_IN_IRQ = 1 << 1
CAUSE_INPUT = 1


class ControlState(StrEnum):
    """Hardwired FSM states."""

    RESET_VECTOR = "RESET_VECTOR"
    IF = "IF"
    EXEC_ALU = "EXEC_ALU"
    EXEC_ADDR = "EXEC_ADDR"
    MEM = "MEM"
    EXEC_BRANCH = "EXEC_BRANCH"
    EXEC_JUMP = "EXEC_JUMP"
    EXEC_IO = "EXEC_IO"
    EXEC_SYS = "EXEC_SYS"
    IRQ_ENTER = "IRQ_ENTER"
    IRQ_VECTOR = "IRQ_VECTOR"
    HALTED = "HALTED"
    FAULT = "FAULT"


class StopReason(StrEnum):
    """Machine stop reasons."""

    RUNNING = "RUNNING"
    HALT = "HALT"
    FAULT_NO_RESET_VECTOR = "FAULT_NO_RESET_VECTOR"
    FAULT_NO_IRQ_HANDLER = "FAULT_NO_IRQ_HANDLER"
    FAULT_BAD_OPCODE = "FAULT_BAD_OPCODE"
    FAULT_BAD_ENCODING = "FAULT_BAD_ENCODING"
    FAULT_ADDR = "FAULT_ADDR"
    FAULT_BAD_PORT = "FAULT_BAD_PORT"
    FAULT_DIV0 = "FAULT_DIV0"
    STOP_TICK_LIMIT = "STOP_TICK_LIMIT"


class ExecutionMode(StrEnum):
    """Trace-facing execution mode."""

    RESET = "RESET"
    MAIN = "MAIN"
    IRQ = "IRQ"
    HALTED = "HALTED"
    FAULT = "FAULT"


@dataclass(frozen=True)
class TraceEntry:
    """One tick of observable machine state."""

    tick: int
    step: int
    mode: ExecutionMode
    state: ControlState
    pc: int
    ir: int
    alu_out: int
    selected_address: int
    decoded: str
    source: str
    registers: tuple[int, ...]
    epc: int
    cause: int
    status: int
    irq_line: bool
    input_status: int
    output_length: int
    cache: CacheTick | None
    input_event: AppliedInputEvent | None
    port_event: str
    stop_reason: StopReason


@dataclass(frozen=True)
class SimulationResult:
    """Result of running a ControlUnit."""

    stdout: str
    stop_reason: StopReason
    ticks: int
    log: list[TraceEntry]


class ControlUnit:
    """Hardwired Control Unit that drives a passive DataPath."""

    def __init__(
        self,
        datapath: DataPath,
        source_map: dict[int, str] | None = None,
        *,
        keep_log: bool = True,
    ) -> None:
        self.datapath = datapath
        self.source_map = source_map or {}
        self.keep_log = keep_log
        self.pc = 0
        self.epc = 0
        self.cause = 0
        self.status = 0
        self.state = ControlState.RESET_VECTOR
        self.step = 0
        self.tick_counter = 0
        self.instruction = Instruction(Opcode.NOP)
        self.instruction_address = 0
        self.stop_reason = StopReason.RUNNING
        self.log: list[TraceEntry] = []
        self.port_event = ""

    def tick(self) -> TraceEntry:
        """Advance the processor by exactly one tick."""
        current_state = self.state
        current_step = self.step
        current_mode = self._mode(self.state)
        self.port_event = ""
        input_event = self.datapath.apply_input_tick(self.tick_counter)
        cache_event = self._perform_state_tick()
        entry = self._trace_entry(current_step, current_state, current_mode, input_event, cache_event)
        if self.keep_log:
            self.log.append(entry)
        self._advance_step(current_state)
        self.tick_counter += 1
        return entry

    def run(self, max_ticks: int) -> SimulationResult:
        """Run until halt, fault, or tick limit."""
        while self.stop_reason == StopReason.RUNNING and self.tick_counter < max_ticks:
            self.tick()
        if self.stop_reason == StopReason.RUNNING:
            self._stop(ControlState.FAULT, StopReason.STOP_TICK_LIMIT)
            if self.keep_log and self.log:
                self.log[-1] = replace(self.log[-1], stop_reason=self.stop_reason)
        return SimulationResult(self.datapath.output_text(), self.stop_reason, self.tick_counter, self.log)

    def _perform_state_tick(self) -> CacheTick | None:
        try:
            return self._perform_state_tick_checked()
        except DecodingError as exc:
            if "unknown opcode" in str(exc):
                self._stop(ControlState.FAULT, StopReason.FAULT_BAD_OPCODE)
            else:
                self._stop(ControlState.FAULT, StopReason.FAULT_BAD_ENCODING)
        except (CacheAccessError, MemoryAccessError):
            self._stop(ControlState.FAULT, StopReason.FAULT_ADDR)
        except PortAccessError:
            self._stop(ControlState.FAULT, StopReason.FAULT_BAD_PORT)
        except ZeroDivisionError:
            self._stop(ControlState.FAULT, StopReason.FAULT_DIV0)
        return None

    def _perform_state_tick_checked(self) -> CacheTick | None:
        handlers = {
            ControlState.RESET_VECTOR: self._tick_reset_vector,
            ControlState.IF: self._tick_instruction_fetch,
            ControlState.EXEC_ALU: self._execute_alu_tick,
            ControlState.EXEC_ADDR: self._execute_address_tick,
            ControlState.MEM: self._tick_memory_access,
            ControlState.EXEC_BRANCH: self._execute_branch_tick,
            ControlState.EXEC_JUMP: self._execute_jump_tick,
            ControlState.EXEC_IO: self._execute_io_tick,
            ControlState.EXEC_SYS: self._execute_system_tick,
            ControlState.IRQ_ENTER: self._execute_irq_enter_tick,
            ControlState.IRQ_VECTOR: self._tick_irq_vector,
        }
        handler = handlers.get(self.state)
        if handler is None:
            return None
        return handler()

    def _tick_reset_vector(self) -> CacheTick | None:
        return self._tick_vector_read(RESET_VECTOR_ADDRESS, StopReason.FAULT_NO_RESET_VECTOR)

    def _tick_irq_vector(self) -> CacheTick | None:
        return self._tick_vector_read(INPUT_VECTOR_ADDRESS, StopReason.FAULT_NO_IRQ_HANDLER)

    def _execute_alu_tick(self) -> None:
        self._execute_alu()

    def _execute_address_tick(self) -> None:
        self._execute_address()

    def _execute_branch_tick(self) -> None:
        self._execute_branch()

    def _execute_jump_tick(self) -> None:
        self._execute_jump()

    def _execute_io_tick(self) -> None:
        self._execute_io()

    def _execute_system_tick(self) -> None:
        self._execute_system()

    def _execute_irq_enter_tick(self) -> None:
        self._execute_irq_enter()

    def _tick_vector_read(self, vector_address: int, missing_reason: StopReason) -> CacheTick:
        if not self.datapath.cache_busy():
            self.datapath.select_address_source(AddressSource.VECTOR, vector=vector_address)
            self.datapath.cache_read(vector_address)
        cache_event = self.datapath.cache_tick()
        if cache_event.completed:
            assert cache_event.value is not None
            vector = cache_event.value
            if vector == 0:
                self._stop(ControlState.FAULT, missing_reason)
            elif not validate_word_address(vector):
                self._stop(ControlState.FAULT, StopReason.FAULT_ADDR)
            else:
                self.pc = vector
                self.state = ControlState.IF
        return cache_event

    def _tick_instruction_fetch(self) -> CacheTick:
        if not validate_word_address(self.pc):
            self._stop(ControlState.FAULT, StopReason.FAULT_ADDR)
            raise CacheAccessError
        fetch_address = self.pc
        self.instruction_address = fetch_address
        if not self.datapath.cache_busy():
            self.datapath.select_address_source(AddressSource.PC, pc=fetch_address)
            self.datapath.cache_read(fetch_address)
        cache_event = self.datapath.cache_tick()
        if cache_event.completed:
            assert cache_event.value is not None
            self.datapath.latch_ir(cache_event.value)
            self.instruction = decode_instruction(cache_event.value)
            self.pc = (self.pc + WORD_BYTES) & WORD_MASK
            self.state = _execution_state(self.instruction.opcode)
        return cache_event

    def _execute_alu(self) -> None:
        instruction = self.instruction
        opcode = instruction.opcode
        if opcode == Opcode.LUI:
            result = (instruction.imm16 << 16) & WORD_MASK
        elif opcode in {Opcode.ADDI, Opcode.ANDI, Opcode.ORI, Opcode.XORI}:
            rhs = sign_extend_16(instruction.imm16) if opcode == Opcode.ADDI else instruction.imm16
            result = self.datapath.alu_execute(
                _alu_operation(opcode),
                self.datapath.read_register(instruction.rs1),
                rhs,
            )
        else:
            result = self.datapath.alu_execute(
                _alu_operation(opcode),
                self.datapath.read_register(instruction.rs1),
                self.datapath.read_register(instruction.rs2),
            )
        self.datapath.write_register(instruction.rd, result)
        self._after_instruction()

    def _execute_address(self) -> None:
        base = self.datapath.read_register(self.instruction.rs1)
        address = (base + sign_extend_16(self.instruction.imm16)) & WORD_MASK
        self.datapath.latch_alu_out(address)
        self.state = ControlState.MEM

    def _tick_memory_access(self) -> CacheTick:
        address = self.datapath.alu_out
        if not validate_word_address(address):
            self._stop(ControlState.FAULT, StopReason.FAULT_ADDR)
            raise CacheAccessError
        if not self.datapath.cache_busy():
            self.datapath.select_address_source(AddressSource.ALU_OUT)
            if self.instruction.opcode == Opcode.LW:
                self.datapath.cache_read(address)
            else:
                self.datapath.cache_write(address, self.datapath.read_register(self.instruction.rd))
        cache_event = self.datapath.cache_tick()
        if cache_event.completed:
            if self.instruction.opcode == Opcode.LW:
                assert cache_event.value is not None
                self.datapath.write_register(self.instruction.rd, cache_event.value)
            self._after_instruction()
        return cache_event

    def _execute_branch(self) -> None:
        target = (self.instruction_address + WORD_BYTES + sign_extend_16(self.instruction.imm16)) & WORD_MASK
        if not validate_word_address(target):
            self._stop(ControlState.FAULT, StopReason.FAULT_ADDR)
            return
        if self._branch_taken():
            self.pc = target
        self._after_instruction()

    def _execute_jump(self) -> None:
        opcode = self.instruction.opcode
        if opcode == Opcode.JR:
            target = self.datapath.read_register(self.instruction.rs1)
        else:
            target = self.instruction.addr24
            if opcode == Opcode.JAL:
                self.datapath.write_register(15, self.pc)
        if not validate_word_address(target):
            self._stop(ControlState.FAULT, StopReason.FAULT_ADDR)
            return
        self.pc = target
        self._after_instruction()

    def _execute_io(self) -> None:
        instruction = self.instruction
        if instruction.opcode == Opcode.IN:
            value = self.datapath.port_read(instruction.port16)
            self.datapath.write_register(instruction.rd, value)
            self.port_event = f"in 0x{instruction.port16:04X} -> 0x{value:08X}"
        else:
            value = self.datapath.read_register(instruction.rd)
            self.datapath.port_write(instruction.port16, value)
            self.port_event = f"out 0x{instruction.port16:04X} <- 0x{value:08X}"
        self._after_instruction()

    def _execute_system(self) -> None:
        opcode = self.instruction.opcode
        if opcode == Opcode.HALT:
            self._stop(ControlState.HALTED, StopReason.HALT)
            return
        if opcode == Opcode.EI:
            self.status |= STATUS_IE
        elif opcode == Opcode.DI:
            self.status &= ~STATUS_IE
        elif opcode == Opcode.IRET:
            self.pc = self.epc
            self.status |= STATUS_IE
            self.status &= ~STATUS_IN_IRQ
        self._after_instruction()

    def _execute_irq_enter(self) -> None:
        self.epc = self.pc
        self.cause = CAUSE_INPUT
        self.status &= ~STATUS_IE
        self.status |= STATUS_IN_IRQ
        self.state = ControlState.IRQ_VECTOR

    def _branch_taken(self) -> bool:
        lhs = self.datapath.read_register(self.instruction.rs1)
        rhs = self.datapath.read_register(self.instruction.rs2)
        opcode = self.instruction.opcode
        if opcode == Opcode.BEQ:
            return lhs == rhs
        if opcode == Opcode.BNE:
            return lhs != rhs
        if opcode == Opcode.BLT:
            return _to_signed(lhs) < _to_signed(rhs)
        if opcode == Opcode.BGE:
            return _to_signed(lhs) >= _to_signed(rhs)
        if opcode == Opcode.BLTU:
            return lhs < rhs
        return lhs >= rhs

    def _after_instruction(self) -> None:
        if self.stop_reason != StopReason.RUNNING:
            return
        if self.status & STATUS_IE and not self.status & STATUS_IN_IRQ and self.datapath.irq_line():
            self.state = ControlState.IRQ_ENTER
        else:
            self.state = ControlState.IF

    def _stop(self, state: ControlState, reason: StopReason) -> None:
        self.state = state
        self.stop_reason = reason

    def _advance_step(self, previous_state: ControlState) -> None:
        if self.state == previous_state and self.stop_reason == StopReason.RUNNING:
            self.step += 1
        else:
            self.step = 0

    def _trace_entry(
        self,
        step: int,
        state: ControlState,
        mode: ExecutionMode,
        input_event: AppliedInputEvent | None,
        cache_event: CacheTick | None,
    ) -> TraceEntry:
        snapshot = self.datapath.snapshot()
        return TraceEntry(
            tick=self.tick_counter,
            step=step,
            mode=mode,
            state=state,
            pc=self.pc,
            ir=self.datapath.ir,
            alu_out=snapshot.alu_out,
            selected_address=snapshot.selected_address,
            decoded=self._decoded_text(state),
            source=self.source_map.get(self.instruction_address, ""),
            registers=snapshot.registers,
            epc=self.epc,
            cause=self.cause,
            status=self.status,
            irq_line=snapshot.irq_line,
            input_status=snapshot.input_status,
            output_length=snapshot.output_length,
            cache=cache_event,
            input_event=input_event,
            port_event=self.port_event,
            stop_reason=self.stop_reason,
        )

    def _mode(self, state: ControlState) -> ExecutionMode:
        if state == ControlState.RESET_VECTOR:
            return ExecutionMode.RESET
        if state == ControlState.HALTED:
            return ExecutionMode.HALTED
        if state == ControlState.FAULT:
            return ExecutionMode.FAULT
        if self.status & STATUS_IN_IRQ or state in {ControlState.IRQ_ENTER, ControlState.IRQ_VECTOR}:
            return ExecutionMode.IRQ
        return ExecutionMode.MAIN

    def _decoded_text(self, state: ControlState) -> str:
        if state in {ControlState.RESET_VECTOR, ControlState.FAULT, ControlState.HALTED}:
            return ""
        if state == ControlState.IF and self.state == ControlState.IF:
            return ""
        return disassemble(self.instruction)


def _execution_state(opcode: Opcode) -> ControlState:
    if opcode == Opcode.JR:
        return ControlState.EXEC_JUMP
    if opcode in {Opcode.LW, Opcode.SW}:
        return ControlState.EXEC_ADDR
    return EXECUTION_STATE_BY_FORMAT[SPEC_BY_OPCODE[opcode].instr_format]


EXECUTION_STATE_BY_FORMAT = {
    InstructionFormat.R_TYPE: ControlState.EXEC_ALU,
    InstructionFormat.I_TYPE: ControlState.EXEC_ALU,
    InstructionFormat.B_TYPE: ControlState.EXEC_BRANCH,
    InstructionFormat.J_TYPE: ControlState.EXEC_JUMP,
    InstructionFormat.P_TYPE: ControlState.EXEC_IO,
    InstructionFormat.Z_TYPE: ControlState.EXEC_SYS,
}


def _alu_operation(opcode: Opcode) -> AluOperation:
    mapping = {
        Opcode.ADD: AluOperation.ADD,
        Opcode.SUB: AluOperation.SUB,
        Opcode.MUL: AluOperation.MUL,
        Opcode.MULHU: AluOperation.MULHU,
        Opcode.DIVU: AluOperation.DIVU,
        Opcode.REMU: AluOperation.REMU,
        Opcode.AND: AluOperation.AND,
        Opcode.OR: AluOperation.OR,
        Opcode.XOR: AluOperation.XOR,
        Opcode.SLL: AluOperation.SLL,
        Opcode.SRL: AluOperation.SRL,
        Opcode.SRA: AluOperation.SRA,
        Opcode.SLT: AluOperation.SLT,
        Opcode.SLTU: AluOperation.SLTU,
        Opcode.ADDI: AluOperation.ADD,
        Opcode.ANDI: AluOperation.AND,
        Opcode.ORI: AluOperation.OR,
        Opcode.XORI: AluOperation.XOR,
    }
    return mapping[opcode]
