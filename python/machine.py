#!/usr/bin/python3
"""Command-line processor model for the lab 4 machine."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import NoReturn, cast

from control_unit import SimulationResult, TraceEntry
from datapath import DataPath
from io_device import InputDevice, PortController, parse_input_schedule
from isa import REGISTER_NAMES, decode_binary_image

DEFAULT_MAX_TICKS = 1_000_000


def simulate(
    program: bytes,
    input_schedule: str,
    *,
    max_ticks: int = DEFAULT_MAX_TICKS,
    source_map: dict[int, str] | None = None,
    keep_log: bool = True,
) -> SimulationResult:
    """Run a binary image with a trap input schedule."""
    segments = decode_binary_image(program)
    ports = PortController(InputDevice(parse_input_schedule(input_schedule)))
    datapath = DataPath.from_segments(segments, ports)
    from control_unit import ControlUnit

    return ControlUnit(datapath, source_map, keep_log=keep_log).run(max_ticks)


def main(
    program_file: str,
    input_schedule_file: str,
    *,
    source_map_file: str | None = None,
    log_file: str | None = None,
    max_ticks: int = DEFAULT_MAX_TICKS,
) -> None:
    """Run a program image from files and print stdout, stop reason, and ticks."""
    source_map = _read_source_map(Path(source_map_file)) if source_map_file is not None else None
    result = simulate(
        Path(program_file).read_bytes(),
        Path(input_schedule_file).read_text(encoding="utf-8"),
        max_ticks=max_ticks,
        source_map=source_map,
        keep_log=log_file is not None,
    )
    if log_file is not None:
        _write_trace(Path(log_file), result.log)
    _write_stdout(result)


def format_trace_entry(entry: TraceEntry) -> str:
    """Format one trace entry as a single log line."""
    fields = [
        "T={:06d}".format(entry.tick),
        "step={}".format(entry.step),
        "mode={}".format(entry.mode.value),
        "state={}".format(entry.state.value),
        "pc={:06X}".format(entry.pc),
        "ir=0x{:08X}".format(entry.ir),
        "alu_out=0x{:08X}".format(entry.alu_out),
        "addr_sel={:06X}".format(entry.selected_address),
        "decoded={}".format(entry.decoded or "-"),
        "epc={:06X}".format(entry.epc),
        "cause={}".format(entry.cause),
        "status={}".format(_format_status(entry.status)),
        "irq={}".format(int(entry.irq_line)),
        "in_status={}".format(_format_input_status(entry.input_status)),
        "out_len={}".format(entry.output_length),
        "stop={}".format(entry.stop_reason.value),
        "regs={}".format(_format_registers(entry.registers)),
    ]
    if entry.source:
        fields.append("src={!r}".format(entry.source))
    if entry.cache is not None:
        fields.append("cache={}".format(_format_cache(entry)))
    if entry.input_event is not None:
        fields.append("input={}".format(_format_input_event(entry)))
    if entry.port_event:
        fields.append("port={}".format(entry.port_event))
    return " ".join(fields)


def _write_trace(path: Path, log: list[TraceEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(format_trace_entry(entry) for entry in log), encoding="utf-8")


def _write_stdout(result: SimulationResult) -> None:
    if result.stdout:
        sys.stdout.write(result.stdout)
        if not result.stdout.endswith("\n"):
            sys.stdout.write("\n")
    print("stop reason:", result.stop_reason.value)
    print("ticks:", result.ticks)


def _read_source_map(path: Path) -> dict[int, str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        _source_map_type_error("source map must be a list")
    source_map: dict[int, str] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            _source_map_type_error("source map entry must be an object")
        address = cast(int, entry["address"])
        source = cast(str, entry["source"])
        source_map[address] = source
    return source_map


def _format_status(status: int) -> str:
    return "IE:{} IN_IRQ:{}".format(status & 1, (status >> 1) & 1)


def _format_input_status(status: int) -> str:
    return "READY:{} EOF:{} OVERRUN:{}".format(status & 1, (status >> 1) & 1, (status >> 2) & 1)


def _format_registers(registers: tuple[int, ...]) -> str:
    return "[" + ",".join("{}={:08X}".format(name, registers[index]) for index, name in enumerate(REGISTER_NAMES)) + "]"


def _format_cache(entry: TraceEntry) -> str:
    assert entry.cache is not None
    cache = entry.cache
    parts = _cache_base_parts(entry)
    if cache.hit:
        parts.append("HIT")
    elif cache.phase.value == "tag":
        parts.append("MISS")
    _append_cache_memory_parts(entry, parts)
    if cache.completed:
        parts.append("ready")
    if cache.value is not None:
        parts.append("value=0x{:08X}".format(cache.value))
    return ":".join(parts)


def _cache_base_parts(entry: TraceEntry) -> list[str]:
    assert entry.cache is not None
    cache = entry.cache
    return [
        cache.operation.value,
        cache.phase.value,
        "addr={:06X}".format(cache.address),
        "index={:02d}".format(cache.index),
        "tag={:06X}".format(cache.tag),
    ]


def _append_cache_memory_parts(entry: TraceEntry, parts: list[str]) -> None:
    assert entry.cache is not None
    cache = entry.cache
    if cache.memory_address is not None:
        parts.append("mem={:06X}".format(cache.memory_address))
    if cache.word_index is not None:
        parts.append("word={}".format(cache.word_index))
    if cache.latency_tick is not None:
        parts.append("lat={}".format(cache.latency_tick))


def _format_input_event(entry: TraceEntry) -> str:
    assert entry.input_event is not None
    event = entry.input_event.event
    if event.value is None:
        token = "EOF"
    else:
        token = repr(chr(event.value))
    return "tick={} token={} ready={} eof={} overrun={}".format(
        event.tick,
        token,
        int(entry.input_event.ready),
        int(entry.input_event.eof),
        int(entry.input_event.overrun),
    )


def _source_map_type_error(message: str) -> NoReturn:
    raise TypeError(message)


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Run a lab 4 L4MC binary image.")
    parser.add_argument("program")
    parser.add_argument("input_schedule")
    parser.add_argument("--map", dest="source_map")
    parser.add_argument("--log", dest="log")
    parser.add_argument("--max-ticks", type=int, default=DEFAULT_MAX_TICKS)
    args = parser.parse_args()
    try:
        main(
            args.program,
            args.input_schedule,
            source_map_file=args.source_map,
            log_file=args.log,
            max_ticks=args.max_ticks,
        )
    except Exception as exc:
        print("machine error:", exc, file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    _cli()
