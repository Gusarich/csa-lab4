#!/usr/bin/python3
"""Assembler for the lab 4 byte-addressed RISC machine."""

from __future__ import annotations

import argparse
import ast
import json
import operator
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from isa import (
    IN_CTRL,
    IN_DATA,
    IN_STATUS,
    MAX_ADDRESS,
    MAX_WORD_ADDRESS,
    OUT_DATA,
    OUT_STATUS,
    WORD_BYTES,
    EncodingError,
    Instruction,
    Opcode,
    Segment,
    SegmentFlag,
    disassemble,
    encode_binary_image,
    encode_instruction,
    encode_signed_16,
    listing_line,
    register_number,
    word_to_bytes,
)

IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
LOCAL_LABEL_RE = re.compile(r"%%[A-Za-z_][A-Za-z0-9_]*")
LABEL_RE = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*):")

SECTION_ORDER = (".vectors", ".text", ".rodata", ".data", ".bss")
SECTION_STARTS = {".vectors": 0x000000, ".text": 0x000040}
SECTION_FLAGS = {
    ".vectors": SegmentFlag(0),
    ".text": SegmentFlag.EXEC,
    ".rodata": SegmentFlag(0),
    ".data": SegmentFlag.WRITE,
    ".bss": SegmentFlag.WRITE | SegmentFlag.BSS,
}
DEFAULT_SECTION = ".text"
MAX_MACRO_DEPTH = 32
VECTOR_RESERVED_START = 0x000008
VECTOR_TABLE_END = 0x000040

BUILTIN_CONSTANTS = {
    "IN_STATUS": IN_STATUS,
    "IN_DATA": IN_DATA,
    "IN_CTRL": IN_CTRL,
    "OUT_STATUS": OUT_STATUS,
    "OUT_DATA": OUT_DATA,
}

R_OPCODES = {
    Opcode.ADD,
    Opcode.SUB,
    Opcode.MUL,
    Opcode.MULHU,
    Opcode.DIVU,
    Opcode.REMU,
    Opcode.AND,
    Opcode.OR,
    Opcode.XOR,
    Opcode.SLL,
    Opcode.SRL,
    Opcode.SRA,
    Opcode.SLT,
    Opcode.SLTU,
}
SIGNED_IMMEDIATE_OPCODES = {Opcode.ADDI}
UNSIGNED_IMMEDIATE_OPCODES = {Opcode.ANDI, Opcode.ORI, Opcode.XORI}
BRANCH_OPCODES = {Opcode.BEQ, Opcode.BNE, Opcode.BLT, Opcode.BGE, Opcode.BLTU, Opcode.BGEU}
ZERO_OPERAND_OPCODES = {Opcode.NOP, Opcode.HALT, Opcode.EI, Opcode.DI, Opcode.IRET}
INSTRUCTION_KINDS = {
    **{opcode: "r" for opcode in R_OPCODES},
    **{opcode: "imm" for opcode in SIGNED_IMMEDIATE_OPCODES | UNSIGNED_IMMEDIATE_OPCODES | {Opcode.LUI}},
    Opcode.LW: "mem",
    Opcode.SW: "mem",
    **{opcode: "branch" for opcode in BRANCH_OPCODES},
    Opcode.J: "jump",
    Opcode.JAL: "jump",
    Opcode.JR: "jr",
    Opcode.IN: "port",
    Opcode.OUT: "port",
    **{opcode: "zero" for opcode in ZERO_OPERAND_OPCODES},
}

BinaryOperator = Callable[[int, int], int]
BINARY_OPERATORS: dict[type[ast.operator], BinaryOperator] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: lambda left, right: _divide(left, right),
    ast.Mod: lambda left, right: _modulo(left, right),
    ast.LShift: operator.lshift,
    ast.RShift: operator.rshift,
    ast.BitAnd: operator.and_,
    ast.BitXor: operator.xor,
    ast.BitOr: operator.or_,
}


class AssemblerError(Exception):
    """Raised when an asm source file cannot be translated."""


@dataclass(frozen=True)
class SourceLine:
    """One source line after preprocessing."""

    number: int
    text: str
    source: str | None = None


@dataclass(frozen=True)
class Macro:
    """A user macro definition."""

    name: str
    params: tuple[str, ...]
    body: tuple[SourceLine, ...]


@dataclass(frozen=True)
class Placement:
    """A source statement placed at an absolute byte address."""

    section: str
    address: int
    statement: str
    line: SourceLine


@dataclass(frozen=True)
class AssemblyResult:
    """All outputs produced by assembling one source file."""

    binary: bytes
    listing: str
    source_map: list[dict[str, object]]
    segments: list[Segment]
    symbols: dict[str, int]


@dataclass
class SectionState:
    """Mutable layout state for one section."""

    cursor: int | None = None
    data: dict[int, int] | None = None
    bss_ranges: list[tuple[int, int]] | None = None

    def __post_init__(self) -> None:
        self.data = {}
        self.bss_ranges = []


class ExpressionEvaluator:
    """Small integer expression evaluator for assembler expressions."""

    def __init__(self, symbols: dict[str, int]):
        self.symbols = symbols

    def evaluate(self, expression: str) -> int:
        """Evaluate one integer expression."""
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError:
            _fail("invalid expression: {}".format(expression))
        return self._eval_node(tree.body)

    def _eval_node(self, node: ast.AST) -> int:
        if isinstance(node, ast.Constant):
            return self._eval_constant(node.value)
        if isinstance(node, ast.Name):
            return self._eval_name(node.id)
        if isinstance(node, ast.UnaryOp):
            return self._eval_unary(node)
        if isinstance(node, ast.BinOp):
            return self._eval_binary(node)
        return _fail("unsupported expression syntax")

    def _eval_constant(self, value: object) -> int:
        if isinstance(value, bool):
            _fail("boolean literals are not assembler integers")
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            if len(value) != 1:
                _fail("character literal must contain one character")
            code = ord(value)
            if code > 0xFF:
                _fail("character literal is out of byte range")
            return code
        return _fail("unsupported literal in expression")

    def _eval_name(self, name: str) -> int:
        try:
            return self.symbols[name]
        except KeyError:
            _fail("unknown identifier: {}".format(name))

    def _eval_unary(self, node: ast.UnaryOp) -> int:
        value = self._eval_node(node.operand)
        if isinstance(node.op, ast.UAdd):
            return value
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.Invert):
            return ~value
        return _fail("unsupported unary operator")

    def _eval_binary(self, node: ast.BinOp) -> int:
        left = self._eval_node(node.left)
        right = self._eval_node(node.right)
        operation = BINARY_OPERATORS.get(type(node.op))
        if operation is None:
            return _fail("unsupported binary operator")
        return operation(left, right)


class Preprocessor:
    """Handle constants, conditionals, macros, and pseudoinstructions."""

    def __init__(self) -> None:
        self.constants = dict(BUILTIN_CONSTANTS)
        self.macros: dict[str, Macro] = {}
        self.expansion_index = 0

    def preprocess(self, text: str) -> tuple[list[SourceLine], dict[str, int]]:
        """Return source lines ready for address assignment."""
        lines = [SourceLine(number, raw_line) for number, raw_line in enumerate(text.splitlines(), 1)]
        return self._process_lines(lines, 0), dict(self.constants)

    def _process_lines(self, lines: list[SourceLine], depth: int) -> list[SourceLine]:
        if depth > MAX_MACRO_DEPTH:
            _fail("macro expansion depth exceeds {}".format(MAX_MACRO_DEPTH))
        result: list[SourceLine] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            text = _meaningful_text(line.text)
            if not text:
                index += 1
                continue
            if text.startswith(".macro"):
                index = self._define_macro(lines, index)
                continue
            if text.startswith(".if"):
                block, index = self._select_conditional_block(lines, index)
                result.extend(self._process_lines(block, depth))
                continue
            if text.startswith(".equ"):
                self._define_constant(text)
                index += 1
                continue
            result.extend(self._expand_statement(line, text, depth))
            index += 1
        return result

    def _define_macro(self, lines: list[SourceLine], index: int) -> int:
        header = _meaningful_text(lines[index].text)
        tokens = _split_words(header)
        if len(tokens) < 2:
            _fail(".macro requires a name")
        name = tokens[1]
        if not IDENTIFIER_RE.fullmatch(name):
            _fail("invalid macro name: {}".format(name))
        params = tuple(_split_operands(" ".join(tokens[2:])))
        self._check_macro_params(params)
        body: list[SourceLine] = []
        index += 1
        while index < len(lines):
            text = _meaningful_text(lines[index].text)
            if text == ".endm":
                if name in self.macros:
                    _fail("duplicate macro: {}".format(name))
                self.macros[name] = Macro(name, params, tuple(body))
                return index + 1
            body.append(lines[index])
            index += 1
        return _fail("unterminated macro: {}".format(name))

    def _check_macro_params(self, params: tuple[str, ...]) -> None:
        seen: set[str] = set()
        for param in params:
            if not IDENTIFIER_RE.fullmatch(param):
                _fail("invalid macro parameter: {}".format(param))
            if param in seen:
                _fail("duplicate macro parameter: {}".format(param))
            seen.add(param)

    def _select_conditional_block(self, lines: list[SourceLine], index: int) -> tuple[list[SourceLine], int]:
        header = _meaningful_text(lines[index].text)
        condition = _after_directive(header, ".if")
        active = _eval_with(self.constants, condition) != 0
        true_block, false_block, next_index = self._collect_conditional(lines, index + 1)
        if active:
            return true_block, next_index
        return false_block, next_index

    def _collect_conditional(
        self, lines: list[SourceLine], index: int
    ) -> tuple[list[SourceLine], list[SourceLine], int]:
        true_block: list[SourceLine] = []
        false_block: list[SourceLine] = []
        current = true_block
        depth = 0
        while index < len(lines):
            text = _meaningful_text(lines[index].text)
            if text.startswith(".if"):
                depth += 1
            if text == ".endif" and depth == 0:
                return true_block, false_block, index + 1
            if text == ".else" and depth == 0:
                current = false_block
                index += 1
                continue
            if text == ".endif":
                depth -= 1
            current.append(lines[index])
            index += 1
        return _fail("unterminated .if")

    def _define_constant(self, text: str) -> None:
        args = _split_operands(_after_directive(text, ".equ"))
        if len(args) != 2:
            _fail(".equ requires name and expression")
        name = args[0]
        if not IDENTIFIER_RE.fullmatch(name):
            _fail("invalid constant name: {}".format(name))
        if name in self.constants:
            _fail("duplicate constant: {}".format(name))
        self.constants[name] = _eval_with(self.constants, args[1])

    def _expand_statement(self, line: SourceLine, text: str, depth: int) -> list[SourceLine]:
        label, statement = _split_label(text)
        if not statement:
            return [SourceLine(line.number, "{}:".format(label))] if label is not None else []
        macro = self.macros.get(_first_word(statement))
        if macro is not None:
            return self._expand_macro_call(line, label, statement, macro, depth)
        return _expand_pseudo(line, label, statement, self.constants)

    def _expand_macro_call(
        self,
        line: SourceLine,
        label: str | None,
        statement: str,
        macro: Macro,
        depth: int,
    ) -> list[SourceLine]:
        args = _split_operands(statement[len(macro.name) :].strip())
        if len(args) != len(macro.params):
            _fail("macro {} expects {} arguments".format(macro.name, len(macro.params)))
        prefix = "__macro_{}_".format(self.expansion_index)
        self.expansion_index += 1
        expanded: list[SourceLine] = []
        if label is not None:
            expanded.append(SourceLine(line.number, "{}:".format(label)))
        for body_line in macro.body:
            expanded.append(SourceLine(body_line.number, _substitute_macro(body_line.text, macro.params, args, prefix)))
        return self._process_lines(expanded, depth + 1)


class Assembler:
    """Two-pass byte-addressed assembler."""

    def __init__(self, constants: dict[str, int]):
        self.constants = constants
        self.labels: dict[str, int] = {}
        self.sections = {name: SectionState() for name in SECTION_ORDER}
        self.current_section = DEFAULT_SECTION
        self.ranges: list[tuple[int, int, SourceLine]] = []
        self.placements: list[Placement] = []
        self.listing: list[str] = []
        self.source_map: list[dict[str, object]] = []
        self.highest_section_index = -1

    def assemble(self, lines: list[SourceLine]) -> AssemblyResult:
        """Assemble preprocessed source lines."""
        self._first_pass(lines)
        self._second_pass()
        segments = self._build_segments()
        symbols = dict(self.constants)
        symbols.update(self.labels)
        return AssemblyResult(
            binary=encode_binary_image(segments),
            listing="\n".join(self.listing),
            source_map=self.source_map,
            segments=segments,
            symbols=symbols,
        )

    def _first_pass(self, lines: list[SourceLine]) -> None:
        for line in lines:
            label, statement = _split_label(_meaningful_text(line.text))
            if label is not None:
                self._define_label(label, line)
            if statement:
                self._place_statement(statement, line)

    def _define_label(self, label: str, line: SourceLine) -> None:
        if label in self.constants or label in self.labels:
            _fail_at(line, "duplicate label: {}".format(label))
        self._enter_current_section(line)
        self.labels[label] = self._cursor()

    def _place_statement(self, statement: str, line: SourceLine) -> None:
        if statement.startswith("."):
            self._place_directive(statement, line)
            return
        self._enter_current_section(line)
        self._require_aligned(line, "instruction")
        address = self._cursor()
        if self.current_section == ".vectors" and VECTOR_RESERVED_START <= address < VECTOR_TABLE_END:
            _fail_at(line, "reserved vector-table entries must be zero")
        self._claim(address, WORD_BYTES, line)
        self.placements.append(Placement(self.current_section, address, statement, line))
        self._advance(WORD_BYTES)

    def _place_directive(self, statement: str, line: SourceLine) -> None:
        directive = _first_word(statement)
        if directive == ".section":
            self._switch_section(statement, line)
        elif directive == ".org":
            self._set_origin(statement, line)
        elif directive == ".word":
            self._place_word(statement, line)
        elif directive == ".space":
            self._place_space(statement, line)
        elif directive == ".pstr":
            self._place_pstr(statement, line)
        else:
            _fail_at(line, "unknown directive: {}".format(directive))

    def _switch_section(self, statement: str, line: SourceLine) -> None:
        args = _split_operands(_after_directive(statement, ".section"))
        if len(args) != 1 or args[0] not in SECTION_ORDER:
            _fail_at(line, "unknown section")
        self.current_section = args[0]
        self._enter_current_section(line)
        self._cursor()

    def _set_origin(self, statement: str, line: SourceLine) -> None:
        self._enter_current_section(line)
        address = self._eval(_after_directive(statement, ".org"))
        _check_address(address, line)
        self.sections[self.current_section].cursor = address

    def _place_word(self, statement: str, line: SourceLine) -> None:
        self._enter_current_section(line)
        operands = _split_operands(_after_directive(statement, ".word"))
        if len(operands) == 0:
            _fail_at(line, ".word requires at least one expression")
        self._require_aligned(line, ".word")
        address = self._cursor()
        size = WORD_BYTES * len(operands)
        self._claim(address, size, line)
        self.placements.append(Placement(self.current_section, address, statement, line))
        self._advance(size)

    def _place_space(self, statement: str, line: SourceLine) -> None:
        self._enter_current_section(line)
        size = self._eval(_after_directive(statement, ".space"))
        if size < 0:
            _fail_at(line, ".space size cannot be negative")
        address = self._cursor()
        self._claim(address, size, line)
        self.placements.append(Placement(self.current_section, address, statement, line))
        self._advance(size)

    def _place_pstr(self, statement: str, line: SourceLine) -> None:
        self._enter_current_section(line)
        if self.current_section not in {".rodata", ".data"}:
            _fail_at(line, ".pstr is allowed only in .rodata or .data")
        text = _parse_string_literal(_after_directive(statement, ".pstr"), line)
        self._require_aligned(line, ".pstr")
        address = self._cursor()
        size = WORD_BYTES * (len(text) + 1)
        self._claim(address, size, line)
        self.placements.append(Placement(self.current_section, address, statement, line))
        self._advance(size)

    def _second_pass(self) -> None:
        for placement in self.placements:
            if placement.statement.startswith(".word"):
                self._emit_word_directive(placement)
            elif placement.statement.startswith(".space"):
                self._emit_space_directive(placement)
            elif placement.statement.startswith(".pstr"):
                self._emit_pstr_directive(placement)
            elif not placement.statement.startswith("."):
                self._emit_instruction(placement)

    def _emit_instruction(self, placement: Placement) -> None:
        self._validate_original_la(placement)
        instruction = self._parse_instruction(placement)
        word = encode_instruction(instruction)
        self._write_word(placement.section, placement.address, word)
        self._record_listing(placement.address, word, disassemble(instruction), placement.line)

    def _emit_word_directive(self, placement: Placement) -> None:
        operands = _split_operands(_after_directive(placement.statement, ".word"))
        for index, operand in enumerate(operands):
            value = self._eval(operand) & 0xFFFFFFFF
            if placement.section == ".bss" and value != 0:
                _fail_at(placement.line, ".word in .bss must be zero")
            address = placement.address + index * WORD_BYTES
            if placement.section == ".vectors" and VECTOR_RESERVED_START <= address < VECTOR_TABLE_END and value != 0:
                _fail_at(placement.line, "reserved vector-table entries must be zero")
            if placement.section != ".bss":
                self._write_word(placement.section, address, value)
            self._record_listing(address, value, ".word {}".format(value), placement.line)

    def _emit_space_directive(self, placement: Placement) -> None:
        size = self._eval(_after_directive(placement.statement, ".space"))
        if placement.section == ".bss":
            return
        state = self.sections[placement.section]
        assert state.data is not None
        for offset in range(size):
            state.data[placement.address + offset] = 0
        self._record_aligned_space(placement, size)

    def _emit_pstr_directive(self, placement: Placement) -> None:
        text = _parse_string_literal(_after_directive(placement.statement, ".pstr"), placement.line)
        self._write_word(placement.section, placement.address, len(text))
        self._record_listing(placement.address, len(text), ".word {}".format(len(text)), placement.line)
        for index, char in enumerate(text, 1):
            address = placement.address + index * WORD_BYTES
            value = ord(char)
            self._write_word(placement.section, address, value)
            self._record_listing(address, value, ".word {}".format(value), placement.line)

    def _parse_instruction(self, placement: Placement) -> Instruction:
        mnemonic = _first_word(placement.statement)
        operands = _split_operands(placement.statement[len(mnemonic) :].strip())
        try:
            opcode = Opcode(mnemonic)
        except ValueError:
            _fail_at(placement.line, "unknown instruction: {}".format(mnemonic))
        return self._build_instruction(opcode, operands, placement)

    def _build_instruction(self, opcode: Opcode, operands: list[str], placement: Placement) -> Instruction:
        builders = {
            "r": self._build_r_instruction,
            "imm": self._build_immediate_instruction,
            "mem": self._build_memory_instruction,
            "branch": self._build_branch_instruction,
            "jump": self._build_jump_instruction,
            "jr": self._build_jr_instruction,
            "port": self._build_port_instruction,
            "zero": self._build_zero_instruction,
        }
        kind = INSTRUCTION_KINDS.get(opcode)
        if kind is None:
            return _fail_at(placement.line, "unsupported instruction: {}".format(opcode.value))
        return builders[kind](opcode, operands, placement)

    def _build_r_instruction(self, opcode: Opcode, operands: list[str], placement: Placement) -> Instruction:
        _require_operand_count(operands, 3, placement.line)
        return Instruction(
            opcode,
            rd=_register(operands[0], placement.line),
            rs1=_register(operands[1], placement.line),
            rs2=_register(operands[2], placement.line),
        )

    def _build_immediate_instruction(self, opcode: Opcode, operands: list[str], placement: Placement) -> Instruction:
        expected_count = 2 if opcode == Opcode.LUI else 3
        _require_operand_count(operands, expected_count, placement.line)
        rd = _register(operands[0], placement.line)
        if opcode == Opcode.LUI:
            return Instruction(opcode, rd=rd, imm16=_unsigned_16(self._eval(operands[1]), placement.line))
        rs1 = _register(operands[1], placement.line)
        value = self._eval(operands[2])
        if opcode in SIGNED_IMMEDIATE_OPCODES:
            return Instruction(opcode, rd=rd, rs1=rs1, imm16=encode_signed_16(value))
        return Instruction(opcode, rd=rd, rs1=rs1, imm16=_unsigned_16(value, placement.line))

    def _build_memory_instruction(self, opcode: Opcode, operands: list[str], placement: Placement) -> Instruction:
        _require_operand_count(operands, 2, placement.line)
        offset, base = _parse_memory_operand(operands[1], placement.line)
        return Instruction(
            opcode,
            rd=_register(operands[0], placement.line),
            rs1=_register(base, placement.line),
            imm16=encode_signed_16(self._eval(offset)),
        )

    def _build_branch_instruction(self, opcode: Opcode, operands: list[str], placement: Placement) -> Instruction:
        _require_operand_count(operands, 3, placement.line)
        target = self._eval(operands[2])
        _check_word_address(target, placement.line)
        offset = target - (placement.address + WORD_BYTES)
        return Instruction(
            opcode,
            rs1=_register(operands[0], placement.line),
            rs2=_register(operands[1], placement.line),
            imm16=encode_signed_16(offset),
        )

    def _build_jump_instruction(self, opcode: Opcode, operands: list[str], placement: Placement) -> Instruction:
        _require_operand_count(operands, 1, placement.line)
        target = self._eval(operands[0])
        _check_word_address(target, placement.line)
        return Instruction(opcode, addr24=target)

    def _build_jr_instruction(self, opcode: Opcode, operands: list[str], placement: Placement) -> Instruction:
        if opcode != Opcode.JR:
            return _fail_at(placement.line, "internal instruction dispatch error")
        _require_operand_count(operands, 1, placement.line)
        return Instruction(Opcode.JR, rs1=_register(operands[0], placement.line))

    def _build_port_instruction(self, opcode: Opcode, operands: list[str], placement: Placement) -> Instruction:
        _require_operand_count(operands, 2, placement.line)
        if opcode == Opcode.IN:
            port = _unsigned_16(self._eval(operands[1]), placement.line)
            return Instruction(
                opcode,
                rd=_register(operands[0], placement.line),
                port16=port,
            )
        port = _unsigned_16(self._eval(operands[0]), placement.line)
        return Instruction(
            opcode,
            rd=_register(operands[1], placement.line),
            port16=port,
        )

    def _build_zero_instruction(self, opcode: Opcode, operands: list[str], placement: Placement) -> Instruction:
        _require_operand_count(operands, 0, placement.line)
        return Instruction(opcode)

    def _write_word(self, section: str, address: int, word: int) -> None:
        state = self.sections[section]
        assert state.data is not None
        for offset, value in enumerate(word_to_bytes(word)):
            state.data[address + offset] = value

    def _record_aligned_space(self, placement: Placement, size: int) -> None:
        if placement.address % WORD_BYTES != 0 or size % WORD_BYTES != 0:
            return
        for offset in range(0, size, WORD_BYTES):
            self._record_listing(placement.address + offset, 0, ".word 0", placement.line)

    def _record_listing(self, address: int, word: int, mnemonic: str, line: SourceLine) -> None:
        self.listing.append(listing_line(address, word, mnemonic))
        self.source_map.append(
            {
                "address": address,
                "line": line.number,
                "source": _source_text(line),
            }
        )

    def _build_segments(self) -> list[Segment]:
        segments: list[Segment] = []
        for section in SECTION_ORDER:
            segments.extend(self._segments_for_section(section))
        return segments

    def _segments_for_section(self, section: str) -> list[Segment]:
        state = self.sections[section]
        flags = SECTION_FLAGS[section]
        if flags & SegmentFlag.BSS:
            assert state.bss_ranges is not None
            return [
                Segment(start, b"", flags, byte_count=end - start) for start, end in _merge_ranges(state.bss_ranges)
            ]
        assert state.data is not None
        return [Segment(start, payload, flags) for start, payload in _contiguous_payloads(state.data)]

    def _eval(self, expression: str) -> int:
        symbols = dict(self.constants)
        symbols.update(self.labels)
        return _eval_with(symbols, expression)

    def _cursor(self) -> int:
        state = self.sections[self.current_section]
        if state.cursor is None:
            state.cursor = self._default_section_start(self.current_section)
        return state.cursor

    def _advance(self, size: int) -> None:
        state = self.sections[self.current_section]
        assert state.cursor is not None
        state.cursor += size

    def _default_section_start(self, section: str) -> int:
        if section in SECTION_STARTS:
            return SECTION_STARTS[section]
        end = 0
        for previous in SECTION_ORDER[: SECTION_ORDER.index(section)]:
            end = max(end, self._section_end(previous))
        return _align_word(end)

    def _section_end(self, section: str) -> int:
        state = self.sections[section]
        end = SECTION_STARTS.get(section, 0)
        if state.cursor is not None:
            end = max(end, state.cursor)
        assert state.data is not None
        assert state.bss_ranges is not None
        if state.data:
            end = max(end, max(state.data) + 1)
        if state.bss_ranges:
            end = max(end, max(range_end for _, range_end in state.bss_ranges))
        return end

    def _claim(self, address: int, size: int, line: SourceLine) -> None:
        if size == 0:
            return
        _check_address(address, line)
        _check_address(address + size - 1, line)
        new_range = (address, address + size)
        for start, end, owner in self.ranges:
            if new_range[0] < end and start < new_range[1]:
                _fail_at(line, "byte range overlaps line {}".format(owner.number))
        self.ranges.append((new_range[0], new_range[1], line))
        state = self.sections[self.current_section]
        if SECTION_FLAGS[self.current_section] & SegmentFlag.BSS:
            assert state.bss_ranges is not None
            state.bss_ranges.append(new_range)

    def _require_aligned(self, line: SourceLine, what: str) -> None:
        if self._cursor() % WORD_BYTES != 0:
            _fail_at(line, "{} address is not word-aligned".format(what))

    def _enter_current_section(self, line: SourceLine) -> None:
        index = SECTION_ORDER.index(self.current_section)
        if index < self.highest_section_index:
            _fail_at(line, "sections must follow order: {}".format(", ".join(SECTION_ORDER)))
        self.highest_section_index = max(self.highest_section_index, index)

    def _validate_original_la(self, placement: Placement) -> None:
        _, statement = _split_label(_source_text(placement.line))
        if not statement or _first_word(statement) != "la":
            return
        operands = _split_operands(statement[len("la") :].strip())
        if len(operands) != 2:
            return
        value = self._eval(operands[1])
        if not 0 <= value <= MAX_ADDRESS:
            _fail_at(placement.line, "la address is outside 24-bit memory range")


def assemble(text: str) -> AssemblyResult:
    """Assemble source text into binary image, listing, and source map."""
    preprocessor = Preprocessor()
    lines, constants = preprocessor.preprocess(text)
    return Assembler(constants).assemble(lines)


def main(source: str, target: str, debug: str | None = None, source_map: str | None = None) -> None:
    """Translate an asm source file to a binary image."""
    source_path = Path(source)
    target_path = Path(target)
    result = assemble(source_path.read_text(encoding="utf-8"))
    _write_file(target_path, result.binary)
    listing_path = Path(debug) if debug is not None else Path(target + ".hex")
    _write_file(listing_path, result.listing.encode("utf-8"))
    if source_map is not None:
        _write_file(Path(source_map), json.dumps(result.source_map, indent=2).encode("utf-8"))
    print("source LoC:", len(source_path.read_text(encoding="utf-8").splitlines()), "segments:", len(result.segments))


def _write_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Assemble lab 4 asm into an L4MC binary image.")
    parser.add_argument("source")
    parser.add_argument("target")
    parser.add_argument("--debug", dest="debug")
    parser.add_argument("--map", dest="source_map")
    args = parser.parse_args()
    try:
        main(args.source, args.target, args.debug, args.source_map)
    except AssemblerError as exc:
        print("assembler error:", exc, file=sys.stderr)
        raise SystemExit(1) from exc


def _expand_pseudo(line: SourceLine, label: str | None, statement: str, constants: dict[str, int]) -> list[SourceLine]:
    mnemonic = _first_word(statement)
    operands = _split_operands(statement[len(mnemonic) :].strip())
    expanded = _pseudo_lines(mnemonic, operands, constants)
    if expanded is None:
        return [SourceLine(line.number, _join_label(label, statement))]
    return [
        SourceLine(
            line.number,
            _join_label(label if index == 0 else None, text),
            _join_label(label if index == 0 else None, statement),
        )
        for index, text in enumerate(expanded)
    ]


def _pseudo_lines(mnemonic: str, operands: list[str], constants: dict[str, int]) -> list[str] | None:
    if mnemonic == "move":
        _require_raw_operand_count(operands, 2, mnemonic)
        return ["add {}, {}, zero".format(operands[0], operands[1])]
    if mnemonic == "ret":
        _require_raw_operand_count(operands, 0, mnemonic)
        return ["jr ra"]
    if mnemonic == "call":
        _require_raw_operand_count(operands, 1, mnemonic)
        return ["jal {}".format(operands[0])]
    if mnemonic == "la":
        _require_raw_operand_count(operands, 2, mnemonic)
        return _expand_la(operands[0], operands[1], constants)
    if mnemonic == "li":
        _require_raw_operand_count(operands, 2, mnemonic)
        return _expand_li(operands[0], operands[1], constants)
    return None


def _expand_li(register: str, expression: str, constants: dict[str, int]) -> list[str]:
    value = _eval_with(constants, expression)
    if -(1 << 15) <= value < (1 << 15):
        return ["addi {}, zero, {}".format(register, value)]
    if 0 <= value <= 0xFFFF:
        return ["ori {}, zero, {}".format(register, value)]
    if not -(1 << 31) <= value <= 0xFFFFFFFF:
        _fail("li immediate is outside 32-bit range")
    encoded = value & 0xFFFFFFFF
    return ["lui {}, {}".format(register, encoded >> 16), "ori {}, {}, {}".format(register, register, encoded & 0xFFFF)]


def _expand_la(register: str, expression: str, constants: dict[str, int]) -> list[str]:
    value = _known_constant_expression_value(expression, constants)
    if value is not None:
        if not 0 <= value <= MAX_ADDRESS:
            _fail("la address is outside 24-bit memory range")
    return [
        "lui {}, (({}) >> 16)".format(register, expression),
        "ori {}, {}, (({}) & 0xFFFF)".format(register, register, expression),
    ]


def _substitute_macro(text: str, params: tuple[str, ...], args: list[str], prefix: str) -> str:
    result = text
    for local in sorted(set(LOCAL_LABEL_RE.findall(result)), key=len, reverse=True):
        result = result.replace(local, prefix + local[2:])
    for param, arg in zip(params, args, strict=True):
        pattern = re.compile(r"(?<![A-Za-z0-9_]){}(?![A-Za-z0-9_])".format(re.escape(param)))
        result = pattern.sub(arg, result)
    return result


def _meaningful_text(text: str) -> str:
    return _strip_comment(text).strip()


def _source_text(line: SourceLine) -> str:
    if line.source is not None:
        return _meaningful_text(line.source)
    return _meaningful_text(line.text)


def _strip_comment(text: str) -> str:  # noqa: C901
    quote: str | None = None
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote is not None:
            escaped = True
            continue
        if char in {"'", '"'}:
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            continue
        if char == ";" and quote is None:
            return text[:index]
    return text


def _split_label(text: str) -> tuple[str | None, str]:
    match = LABEL_RE.match(text)
    if match is None:
        return None, text.strip()
    label = match.group(1)
    return label, text[match.end() :].strip()


def _first_word(text: str) -> str:
    words = _split_words(text)
    if not words:
        _fail("expected statement")
    return words[0]


def _split_words(text: str) -> list[str]:
    return text.split()


def _after_directive(statement: str, directive: str) -> str:
    rest = statement[len(directive) :].strip()
    if not rest:
        _fail("{} requires an argument".format(directive))
    return rest


def _split_operands(text: str) -> list[str]:  # noqa: C901
    if not text:
        return []
    result: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote is not None:
            escaped = True
            continue
        if char in {"'", '"'}:
            quote = _next_quote_state(quote, char)
            continue
        if quote is not None:
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                _fail("unbalanced operand parentheses")
        elif char == "," and depth == 0:
            result.append(text[start:index].strip())
            start = index + 1
    if quote is not None or depth != 0:
        _fail("unterminated operand")
    result.append(text[start:].strip())
    if any(operand == "" for operand in result):
        _fail("empty operand")
    return result


def _next_quote_state(quote: str | None, char: str) -> str | None:
    if quote is None:
        return char
    if quote == char:
        return None
    return quote


def _join_label(label: str | None, statement: str) -> str:
    if label is None:
        return statement
    return "{}: {}".format(label, statement)


def _parse_memory_operand(operand: str, line: SourceLine) -> tuple[str, str]:
    match = re.fullmatch(r"(.+)\(([A-Za-z_][A-Za-z0-9_]*)\)", operand.strip())
    if match is None:
        _fail_at(line, "memory operand must be off16(base)")
    return match.group(1).strip(), match.group(2)


def _parse_string_literal(token: str, line: SourceLine) -> str:
    token = token.strip()
    if len(token) < 2 or token[0] not in {"'", '"'} or token[-1] != token[0]:
        _fail_at(line, ".pstr requires a string literal")
    chars: list[str] = []
    index = 1
    end = len(token) - 1
    quote = token[0]
    while index < end:
        char, index = _parse_string_char(token, index, end, quote, line)
        chars.append(char)
    return "".join(chars)


def _parse_string_char(token: str, index: int, end: int, quote: str, line: SourceLine) -> tuple[str, int]:
    char = token[index]
    if char == quote:
        _fail_at(line, "invalid string literal")
    if char != "\\":
        if ord(char) > 0x7F:
            _fail_at(line, "non-ASCII string bytes must use \\xNN escapes")
        return char, index + 1
    return _parse_string_escape(token, index, end, line)


def _parse_string_escape(token: str, index: int, end: int, line: SourceLine) -> tuple[str, int]:
    if index + 1 >= end:
        _fail_at(line, "invalid string escape")
    escape = token[index + 1]
    if escape == "x":
        return _parse_hex_string_escape(token, index, line)
    escaped_chars = {
        "0": "\0",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "\\": "\\",
        "'": "'",
        '"': '"',
    }
    if escape not in escaped_chars:
        _fail_at(line, "unsupported string escape")
    return escaped_chars[escape], index + 2


def _parse_hex_string_escape(token: str, index: int, line: SourceLine) -> tuple[str, int]:
    hex_digits = token[index + 2 : index + 4]
    if len(hex_digits) != 2 or not re.fullmatch(r"[0-9A-Fa-f]{2}", hex_digits):
        _fail_at(line, "invalid \\xNN string escape")
    return chr(int(hex_digits, 16)), index + 4


def _known_constant_expression_value(expression: str, constants: dict[str, int]) -> int | None:
    try:
        return _eval_with(constants, expression)
    except AssemblerError as exc:
        if str(exc).startswith("unknown identifier:"):
            return None
        raise


def _register(name: str, line: SourceLine) -> int:
    try:
        return register_number(name)
    except EncodingError:
        _fail_at(line, "unknown register: {}".format(name))


def _require_operand_count(operands: list[str], expected: int, line: SourceLine) -> None:
    if len(operands) != expected:
        _fail_at(line, "expected {} operands".format(expected))


def _require_raw_operand_count(operands: list[str], expected: int, mnemonic: str) -> None:
    if len(operands) != expected:
        _fail("{} expects {} operands".format(mnemonic, expected))


def _eval_with(symbols: dict[str, int], expression: str) -> int:
    return ExpressionEvaluator(symbols).evaluate(expression)


def _unsigned_16(value: int, line: SourceLine) -> int:
    if not 0 <= value <= 0xFFFF:
        _fail_at(line, "unsigned 16-bit value out of range")
    return value


def _check_address(address: int, line: SourceLine) -> None:
    if not 0 <= address <= MAX_ADDRESS:
        _fail_at(line, "address out of range: {}".format(address))


def _check_word_address(address: int, line: SourceLine) -> None:
    if not 0 <= address <= MAX_WORD_ADDRESS or address % WORD_BYTES != 0:
        _fail_at(line, "target address is not an aligned word address")


def _align_word(value: int) -> int:
    return (value + WORD_BYTES - 1) // WORD_BYTES * WORD_BYTES


def _divide(left: int, right: int) -> int:
    if right == 0:
        _fail("division by zero in expression")
    return left // right


def _modulo(left: int, right: int) -> int:
    if right == 0:
        _fail("division by zero in expression")
    return left % right


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not ranges:
        return []
    merged = [sorted(ranges)[0]]
    for start, end in sorted(ranges)[1:]:
        previous_start, previous_end = merged[-1]
        if start == previous_end:
            merged[-1] = (previous_start, end)
        else:
            merged.append((start, end))
    return merged


def _contiguous_payloads(data: dict[int, int]) -> list[tuple[int, bytes]]:
    if not data:
        return []
    addresses = sorted(data)
    groups: list[tuple[int, bytearray]] = [(addresses[0], bytearray([data[addresses[0]]]))]
    previous = addresses[0]
    for address in addresses[1:]:
        if address == previous + 1:
            groups[-1][1].append(data[address])
        else:
            groups.append((address, bytearray([data[address]])))
        previous = address
    return [(start, bytes(payload)) for start, payload in groups]


def _fail_at(line: SourceLine, message: str) -> NoReturn:
    _fail("line {}: {}".format(line.number, message))


def _fail(message: str) -> NoReturn:
    raise AssemblerError(message)


if __name__ == "__main__":
    _cli()
