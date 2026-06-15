"""Tests for memory, cache, and port-mapped I/O devices."""

from __future__ import annotations

import pytest

from cache import (
    ByteAddressableMemory,
    CacheAccessError,
    CachePhase,
    DirectMappedCache,
)
from io_device import (
    EOF_BIT,
    OVERRUN_BIT,
    READY_BIT,
    InputDevice,
    InputEvent,
    InputEventKind,
    InputScheduleError,
    PortAccessError,
    PortController,
    parse_input_schedule,
)
from isa import IN_CTRL, IN_DATA, IN_STATUS, OUT_DATA, OUT_STATUS, Segment, SegmentFlag


def test_memory_loads_payload_and_bss_segments() -> None:
    memory = ByteAddressableMemory.from_segments(
        [
            Segment(0x100, b"\x12\x34\x56\x78", SegmentFlag(0)),
            Segment(0x200, b"", SegmentFlag.WRITE | SegmentFlag.BSS, byte_count=4),
        ]
    )

    assert memory.read_word(0x100) == 0x12345678
    assert memory.read_word(0x200) == 0


def test_cache_clean_miss_then_spatial_hit() -> None:
    memory = ByteAddressableMemory()
    memory.write_word(0x0000, 0x11111111)
    memory.write_word(0x0004, 0x22222222)
    cache = DirectMappedCache(memory)

    cache.begin_read(0x0000)
    miss_ticks = _drain_cache(cache)

    assert len(miss_ticks) == 41
    assert miss_ticks[0].phase == CachePhase.TAG
    assert not miss_ticks[0].hit
    assert miss_ticks[-1].completed
    assert miss_ticks[-1].value == 0x11111111

    cache.begin_read(0x0004)
    hit_ticks = _drain_cache(cache)

    assert len(hit_ticks) == 1
    assert hit_ticks[0].hit
    assert hit_ticks[0].completed
    assert hit_ticks[0].value == 0x22222222


def test_cache_dirty_conflict_miss_writes_back_victim_line() -> None:
    memory = ByteAddressableMemory()
    memory.write_word(0x0000, 0xAAAAAAAA)
    memory.write_word(0x0100, 0xBBBBBBBB)
    cache = DirectMappedCache(memory)

    cache.begin_write(0x0000, 0x12345678)
    write_ticks = _drain_cache(cache)
    assert len(write_ticks) == 41
    assert memory.read_word(0x0000) == 0xAAAAAAAA

    cache.begin_read(0x0100)
    dirty_miss_ticks = _drain_cache(cache)

    assert len(dirty_miss_ticks) == 81
    assert dirty_miss_ticks[0].phase == CachePhase.TAG
    assert dirty_miss_ticks[1].phase == CachePhase.WRITE_BACK
    assert dirty_miss_ticks[-1].phase == CachePhase.FILL
    assert dirty_miss_ticks[-1].completed
    assert dirty_miss_ticks[-1].value == 0xBBBBBBBB
    assert memory.read_word(0x0000) == 0x12345678


def test_cache_rejects_unaligned_access_and_double_begin() -> None:
    cache = DirectMappedCache(ByteAddressableMemory())
    with pytest.raises(CacheAccessError):
        cache.begin_read(2)
    cache.begin_read(0)
    with pytest.raises(CacheAccessError):
        cache.begin_write(4, 1)


def test_input_schedule_and_port_controller() -> None:
    schedule = parse_input_schedule("10 'A'\n20 EOF\n")
    ports = PortController(InputDevice(schedule))

    assert ports.apply_tick(9) is None
    assert ports.apply_tick(10) is not None
    assert ports.irq_line()
    assert ports.read(IN_STATUS) == READY_BIT
    assert ports.read(IN_DATA) == ord("A")
    assert ports.read(IN_STATUS) == 0

    assert ports.apply_tick(20) is not None
    assert ports.read(IN_STATUS) == EOF_BIT
    ports.write(IN_CTRL, 1)
    assert ports.read(IN_STATUS) == 0

    ports.write(OUT_DATA, ord("Z"))
    assert ports.read(OUT_STATUS) == 1
    assert ports.output_text() == "Z"


def test_input_device_records_overrun_without_hidden_queue() -> None:
    device = InputDevice(
        [
            InputEvent(1, InputEventKind.BYTE, ord("A")),
            InputEvent(2, InputEventKind.BYTE, ord("B")),
        ]
    )

    assert device.apply_tick(1) is not None
    assert device.apply_tick(2) is not None
    assert device.read_status() == READY_BIT | OVERRUN_BIT
    assert device.read_data() == ord("A")
    assert device.read_status() == OVERRUN_BIT
    device.write_ctrl(2)
    assert device.read_status() == 0


@pytest.mark.parametrize(
    "schedule",
    [
        "1 'A'\n1 'B'\n",
        "1 EOF\n2 'B'\n",
        "-1 'A'\n",
    ],
)
def test_input_schedule_rejects_invalid_sequences(schedule: str) -> None:
    with pytest.raises(InputScheduleError):
        parse_input_schedule(schedule)


def test_port_controller_rejects_invalid_direction_or_port() -> None:
    ports = PortController()
    with pytest.raises(PortAccessError):
        ports.read(IN_CTRL)
    with pytest.raises(PortAccessError):
        ports.write(IN_STATUS, 1)
    with pytest.raises(PortAccessError):
        ports.read(0x7777)


def _drain_cache(cache: DirectMappedCache) -> list:
    ticks = []
    while cache.is_busy():
        ticks.append(cache.tick())
    return ticks
