"""Port-mapped input/output devices and trap input schedule."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import StrEnum
from typing import NoReturn

from isa import IN_CTRL, IN_DATA, IN_STATUS, OUT_DATA, OUT_STATUS

READY_BIT = 1 << 0
EOF_BIT = 1 << 1
OVERRUN_BIT = 1 << 2

CTRL_CLEAR_EOF = 1 << 0
CTRL_CLEAR_OVERRUN = 1 << 1


class InputScheduleError(Exception):
    """Raised when an input schedule is malformed."""


class PortAccessError(Exception):
    """Raised when software performs an invalid port access."""


class InputEventKind(StrEnum):
    """External input event kind."""

    BYTE = "byte"
    EOF = "eof"


@dataclass(frozen=True)
class InputEvent:
    """One external input event applied at the beginning of a tick."""

    tick: int
    kind: InputEventKind
    value: int | None = None


@dataclass(frozen=True)
class AppliedInputEvent:
    """Observable result of applying one scheduled input event."""

    event: InputEvent
    ready: bool
    eof: bool
    overrun: bool


class InputDevice:
    """Single-register level-triggered trap input device."""

    def __init__(self, schedule: list[InputEvent] | None = None) -> None:
        self.schedule = schedule or []
        _validate_schedule(self.schedule)
        self.next_event = 0
        self.data_register = 0
        self.ready = False
        self.eof = False
        self.overrun = False

    def apply_tick(self, tick: int) -> AppliedInputEvent | None:
        """Apply a scheduled event for the beginning of the given tick."""
        if self.next_event >= len(self.schedule):
            return None
        event = self.schedule[self.next_event]
        if event.tick != tick:
            return None
        self.next_event += 1
        if event.kind == InputEventKind.EOF:
            self.eof = True
        elif self.ready:
            self.overrun = True
        else:
            assert event.value is not None
            self.data_register = event.value
            self.ready = True
        return AppliedInputEvent(event, self.ready, self.eof, self.overrun)

    def read_status(self) -> int:
        """Read IN_STATUS."""
        status = 0
        if self.ready:
            status |= READY_BIT
        if self.eof:
            status |= EOF_BIT
        if self.overrun:
            status |= OVERRUN_BIT
        return status

    def read_data(self) -> int:
        """Read IN_DATA, clearing READY only when data is present."""
        if not self.ready:
            return 0
        value = self.data_register
        self.ready = False
        return value

    def write_ctrl(self, value: int) -> None:
        """Write IN_CTRL known control bits."""
        if value & CTRL_CLEAR_EOF:
            self.eof = False
        if value & CTRL_CLEAR_OVERRUN:
            self.overrun = False

    def irq_line(self) -> bool:
        """Return the level-triggered IRQ line."""
        return self.ready or self.eof or self.overrun


class OutputDevice:
    """Always-ready byte output device."""

    def __init__(self) -> None:
        self.buffer: list[str] = []

    def read_status(self) -> int:
        """Read OUT_STATUS."""
        return 1

    def write_data(self, value: int) -> None:
        """Write OUT_DATA."""
        self.buffer.append(chr(value & 0xFF))

    def text(self) -> str:
        """Return accumulated output text."""
        return "".join(self.buffer)


class PortController:
    """Port address decoder for the two I/O devices."""

    def __init__(self, input_device: InputDevice | None = None, output_device: OutputDevice | None = None) -> None:
        self.input_device = input_device or InputDevice()
        self.output_device = output_device or OutputDevice()

    def read(self, port: int) -> int:
        """Read a 16-bit I/O port."""
        if port == IN_STATUS:
            return self.input_device.read_status()
        if port == IN_DATA:
            return self.input_device.read_data()
        if port == OUT_STATUS:
            return self.output_device.read_status()
        message = f"cannot read port 0x{port:04X}"
        raise PortAccessError(message)

    def write(self, port: int, value: int) -> None:
        """Write a 16-bit I/O port."""
        if port == IN_CTRL:
            self.input_device.write_ctrl(value)
            return
        if port == OUT_DATA:
            self.output_device.write_data(value)
            return
        message = f"cannot write port 0x{port:04X}"
        raise PortAccessError(message)

    def apply_tick(self, tick: int) -> AppliedInputEvent | None:
        """Apply one input event, if scheduled for this tick."""
        return self.input_device.apply_tick(tick)

    def irq_line(self) -> bool:
        """Return the input interrupt request line."""
        return self.input_device.irq_line()

    def output_text(self) -> str:
        """Return accumulated output."""
        return self.output_device.text()

    def input_status(self) -> int:
        """Return the current IN_STATUS bits without changing device state."""
        return self.input_device.read_status()

    def output_length(self) -> int:
        """Return the number of bytes written to OUT_DATA."""
        return len(self.output_device.buffer)


def parse_input_schedule(text: str) -> list[InputEvent]:
    """Parse a trap input schedule file."""
    events: list[InputEvent] = []
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = _strip_schedule_comment(raw_line).strip()
        if not line:
            continue
        events.append(_parse_schedule_line(line, line_number))
    _validate_schedule(events)
    return events


def _strip_schedule_comment(line: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(line):
        if char == ";" and quote is None:
            return line[:index]
        quote, escaped = _next_schedule_quote_state(quote, escaped, char)
    return line


def _next_schedule_quote_state(quote: str | None, escaped: bool, char: str) -> tuple[str | None, bool]:
    if escaped:
        return quote, False
    if char == "\\" and quote is not None:
        return quote, True
    if char in {"'", '"'}:
        if quote is None:
            return char, False
        if quote == char:
            return None, False
    return quote, False


def _parse_schedule_line(line: str, line_number: int) -> InputEvent:
    parts = line.split(maxsplit=1)
    if len(parts) != 2:
        _schedule_error(line_number, "expected tick and input token")
    tick = _parse_tick(parts[0], line_number)
    token = parts[1].strip()
    if token == "EOF":
        return InputEvent(tick, InputEventKind.EOF)
    value = _parse_input_value(token, line_number)
    return InputEvent(tick, InputEventKind.BYTE, value)


def _parse_tick(token: str, line_number: int) -> int:
    try:
        tick = int(token, 0)
    except ValueError as exc:
        message = f"line {line_number}: invalid tick"
        raise InputScheduleError(message) from exc
    if tick < 0:
        _schedule_error(line_number, "tick must be non-negative")
    return tick


def _parse_input_value(token: str, line_number: int) -> int:
    try:
        value = ast.literal_eval(token)
    except (SyntaxError, ValueError) as exc:
        message = f"line {line_number}: invalid input token"
        raise InputScheduleError(message) from exc
    if not isinstance(value, str) or len(value) != 1:
        _schedule_error(line_number, "input token must be one character")
    code = ord(value)
    if code > 0xFF:
        _schedule_error(line_number, "input token is out of byte range")
    return code


def _validate_schedule(events: list[InputEvent]) -> None:
    previous_tick = -1
    eof_seen = False
    for event in events:
        if event.tick <= previous_tick:
            _schedule_global_error("input ticks must be strictly increasing")
        if eof_seen:
            _schedule_global_error("input event appears after EOF")
        if event.kind == InputEventKind.BYTE and event.value is None:
            _schedule_global_error("byte input event has no value")
        if event.kind == InputEventKind.EOF and event.value is not None:
            _schedule_global_error("EOF input event must not have a value")
        previous_tick = event.tick
        eof_seen = event.kind == InputEventKind.EOF


def _schedule_error(line_number: int, message: str) -> None:
    full_message = f"line {line_number}: {message}"
    raise InputScheduleError(full_message)


def _schedule_global_error(message: str) -> NoReturn:
    raise InputScheduleError(message)
