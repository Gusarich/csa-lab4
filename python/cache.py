"""Unified byte-addressed memory and direct-mapped write-back cache."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import NoReturn

from isa import (
    MAX_ADDRESS,
    MAX_WORD_ADDRESS,
    MEMORY_SIZE,
    WORD_BYTES,
    Segment,
    SegmentFlag,
    word_from_bytes,
    word_to_bytes,
)

LINE_WORDS = 4
LINE_SIZE = LINE_WORDS * WORD_BYTES
LINE_COUNT = 16
CACHE_CAPACITY_BYTES = LINE_SIZE * LINE_COUNT
MEMORY_LATENCY_PER_WORD = 10


class MemoryAccessError(Exception):
    """Raised when a memory access violates the architectural address space."""


class CacheAccessError(Exception):
    """Raised when the cache is used out of protocol."""


class CacheOperation(StrEnum):
    """CPU-visible cache access type."""

    READ = "read"
    WRITE = "write"


class CachePhase(StrEnum):
    """One observable phase of a cache access."""

    TAG = "tag"
    WRITE_BACK = "write-back"
    FILL = "fill"


@dataclass(frozen=True)
class CacheTick:
    """Result of one cache-internal tick."""

    phase: CachePhase
    operation: CacheOperation
    address: int
    index: int
    tag: int
    hit: bool = False
    completed: bool = False
    value: int | None = None
    memory_address: int | None = None
    word_index: int | None = None
    latency_tick: int | None = None


@dataclass
class CacheLine:
    """One direct-mapped cache line."""

    valid: bool = False
    dirty: bool = False
    tag: int = 0
    words: list[int] = field(default_factory=lambda: [0] * LINE_WORDS)


@dataclass(frozen=True)
class CacheRequest:
    """A pending CPU access."""

    operation: CacheOperation
    address: int
    value: int = 0


@dataclass
class PendingAccess:
    """Internal state for a multi-tick cache miss."""

    request: CacheRequest
    index: int
    tag: int
    line_base: int
    word_offset: int
    old_tag: int
    old_words: list[int]
    phase: CachePhase
    word_index: int = 0
    latency_tick: int = 0
    fill_words: list[int] = field(default_factory=lambda: [0] * LINE_WORDS)


class ByteAddressableMemory:
    """Architectural 16 MiB byte-addressed memory."""

    def __init__(self) -> None:
        self.bytes = bytearray(MEMORY_SIZE)

    @classmethod
    def from_segments(cls, segments: list[Segment]) -> ByteAddressableMemory:
        """Create memory and load an L4MC segment list."""
        memory = cls()
        memory.load_segments(segments)
        return memory

    def load_segments(self, segments: list[Segment]) -> None:
        """Apply binary image segments to zero-initialized memory."""
        loaded_ranges: list[tuple[int, int]] = []
        for segment in segments:
            self._check_segment(segment)
            start = segment.base_address
            end = start + segment.size
            self._check_overlap(loaded_ranges, start, end)
            loaded_ranges.append((start, end))
            if not segment.flags & SegmentFlag.BSS:
                self.bytes[start:end] = segment.data

    def read_word(self, address: int) -> int:
        """Read one aligned 32-bit big-endian word."""
        self._check_word_address(address)
        return word_from_bytes(bytes(self.bytes[address : address + WORD_BYTES]))

    def write_word(self, address: int, value: int) -> None:
        """Write one aligned 32-bit big-endian word."""
        self._check_word_address(address)
        self.bytes[address : address + WORD_BYTES] = word_to_bytes(value & 0xFFFFFFFF)

    def _check_segment(self, segment: Segment) -> None:
        if segment.size < 0 or segment.base_address < 0:
            _memory_error("segment range is negative")
        if segment.size > 0 and segment.base_address + segment.size - 1 > MAX_ADDRESS:
            _memory_error("segment exceeds address space")
        if segment.flags & SegmentFlag.BSS:
            if len(segment.data) != 0:
                _memory_error("BSS segment must not contain payload")
        elif segment.size != len(segment.data):
            _memory_error("segment payload size mismatch")

    def _check_overlap(self, ranges: list[tuple[int, int]], start: int, end: int) -> None:
        for loaded_start, loaded_end in ranges:
            if start < loaded_end and loaded_start < end:
                _memory_error("overlapping memory segments")

    def _check_word_address(self, address: int) -> None:
        if not 0 <= address <= MAX_WORD_ADDRESS or address % WORD_BYTES != 0:
            raise MemoryAccessError("word address is out of range or unaligned: {}".format(address))


class DirectMappedCache:
    """Unified direct-mapped cache with write-back and write-allocate."""

    def __init__(self, memory: ByteAddressableMemory) -> None:
        self.memory = memory
        self.lines = [CacheLine() for _ in range(LINE_COUNT)]
        self.pending: PendingAccess | None = None

    def begin_read(self, address: int) -> None:
        """Start a CPU read access."""
        self._begin(CacheRequest(CacheOperation.READ, address))

    def begin_write(self, address: int, value: int) -> None:
        """Start a CPU write access."""
        self._begin(CacheRequest(CacheOperation.WRITE, address, value & 0xFFFFFFFF))

    def tick(self) -> CacheTick:
        """Advance the active cache access by exactly one cache tick."""
        if self.pending is None:
            _cache_error("cache has no active access")
        if self.pending.phase == CachePhase.TAG:
            return self._tick_tag()
        if self.pending.phase == CachePhase.WRITE_BACK:
            return self._tick_write_back()
        return self._tick_fill()

    def is_busy(self) -> bool:
        """Return whether a cache access is in progress."""
        return self.pending is not None

    def flush(self) -> list[CacheTick]:
        """Write all dirty cache lines back, one observable tick per memory wait."""
        ticks: list[CacheTick] = []
        for index, line in enumerate(self.lines):
            if line.valid and line.dirty:
                ticks.extend(self._flush_line(index, line))
                line.dirty = False
        return ticks

    def _begin(self, request: CacheRequest) -> None:
        if self.pending is not None:
            _cache_error("cache access already in progress")
        _check_cache_address(request.address)
        index, tag, line_base, word_offset = _decode_address(request.address)
        line = self.lines[index]
        self.pending = PendingAccess(
            request=request,
            index=index,
            tag=tag,
            line_base=line_base,
            word_offset=word_offset,
            old_tag=line.tag,
            old_words=list(line.words),
            phase=CachePhase.TAG,
        )

    def _tick_tag(self) -> CacheTick:
        assert self.pending is not None
        pending = self.pending
        line = self.lines[pending.index]
        hit = line.valid and line.tag == pending.tag
        if hit:
            value = self._complete_hit(pending, line)
            self.pending = None
            return self._tick_result(CachePhase.TAG, pending, hit=True, completed=True, value=value)
        pending.phase = CachePhase.WRITE_BACK if line.valid and line.dirty else CachePhase.FILL
        return self._tick_result(CachePhase.TAG, pending)

    def _complete_hit(self, pending: PendingAccess, line: CacheLine) -> int | None:
        if pending.request.operation == CacheOperation.READ:
            return line.words[pending.word_offset]
        line.words[pending.word_offset] = pending.request.value
        line.dirty = True
        return None

    def _tick_write_back(self) -> CacheTick:
        assert self.pending is not None
        pending = self.pending
        pending.latency_tick += 1
        memory_address = _line_base(pending.old_tag, pending.index) + pending.word_index * WORD_BYTES
        tick = self._tick_result(
            CachePhase.WRITE_BACK,
            pending,
            memory_address=memory_address,
            word_index=pending.word_index,
            latency_tick=pending.latency_tick,
        )
        if pending.latency_tick == MEMORY_LATENCY_PER_WORD:
            self.memory.write_word(memory_address, pending.old_words[pending.word_index])
            self._advance_write_back_word()
        return tick

    def _tick_fill(self) -> CacheTick:
        assert self.pending is not None
        pending = self.pending
        pending.latency_tick += 1
        memory_address = pending.line_base + pending.word_index * WORD_BYTES
        completed = pending.word_index == LINE_WORDS - 1 and pending.latency_tick == MEMORY_LATENCY_PER_WORD
        value = (
            self._completion_value(pending) if completed and pending.request.operation == CacheOperation.READ else None
        )
        tick = self._tick_result(
            CachePhase.FILL,
            pending,
            completed=completed,
            value=value,
            memory_address=memory_address,
            word_index=pending.word_index,
            latency_tick=pending.latency_tick,
        )
        if pending.latency_tick == MEMORY_LATENCY_PER_WORD:
            pending.fill_words[pending.word_index] = self.memory.read_word(memory_address)
            if completed:
                self._complete_fill()
            else:
                self._advance_fill_word()
        return tick

    def _completion_value(self, pending: PendingAccess) -> int:
        if pending.word_index == pending.word_offset and pending.latency_tick == MEMORY_LATENCY_PER_WORD:
            return self.memory.read_word(pending.line_base + pending.word_index * WORD_BYTES)
        return pending.fill_words[pending.word_offset]

    def _complete_fill(self) -> None:
        assert self.pending is not None
        pending = self.pending
        line = self.lines[pending.index]
        line.valid = True
        line.dirty = False
        line.tag = pending.tag
        line.words = list(pending.fill_words)
        if pending.request.operation == CacheOperation.WRITE:
            line.words[pending.word_offset] = pending.request.value
            line.dirty = True
        self.pending = None

    def _advance_write_back_word(self) -> None:
        assert self.pending is not None
        self.pending.word_index += 1
        self.pending.latency_tick = 0
        if self.pending.word_index == LINE_WORDS:
            self.pending.phase = CachePhase.FILL
            self.pending.word_index = 0

    def _advance_fill_word(self) -> None:
        assert self.pending is not None
        self.pending.word_index += 1
        self.pending.latency_tick = 0

    def _tick_result(
        self,
        phase: CachePhase,
        pending: PendingAccess,
        *,
        hit: bool = False,
        completed: bool = False,
        value: int | None = None,
        memory_address: int | None = None,
        word_index: int | None = None,
        latency_tick: int | None = None,
    ) -> CacheTick:
        return CacheTick(
            phase=phase,
            operation=pending.request.operation,
            address=pending.request.address,
            index=pending.index,
            tag=pending.tag,
            hit=hit,
            completed=completed,
            value=value,
            memory_address=memory_address,
            word_index=word_index,
            latency_tick=latency_tick,
        )

    def _flush_line(self, index: int, line: CacheLine) -> list[CacheTick]:
        ticks = []
        for word_index, word in enumerate(line.words):
            address = _line_base(line.tag, index) + word_index * WORD_BYTES
            request = CacheRequest(CacheOperation.WRITE, address, word)
            pending = PendingAccess(
                request=request,
                index=index,
                tag=line.tag,
                line_base=_line_base(line.tag, index),
                word_offset=word_index,
                old_tag=line.tag,
                old_words=[],
                phase=CachePhase.WRITE_BACK,
            )
            for latency_tick in range(1, MEMORY_LATENCY_PER_WORD + 1):
                ticks.append(
                    self._tick_result(
                        CachePhase.WRITE_BACK,
                        pending,
                        memory_address=address,
                        word_index=word_index,
                        latency_tick=latency_tick,
                    )
                )
            self.memory.write_word(address, word)
        return ticks


def _decode_address(address: int) -> tuple[int, int, int, int]:
    line_base = address & ~(LINE_SIZE - 1)
    word_offset = (address // WORD_BYTES) % LINE_WORDS
    index = (address // LINE_SIZE) % LINE_COUNT
    tag = address // CACHE_CAPACITY_BYTES
    return index, tag, line_base, word_offset


def _line_base(tag: int, index: int) -> int:
    return tag * CACHE_CAPACITY_BYTES + index * LINE_SIZE


def _check_cache_address(address: int) -> None:
    if not 0 <= address <= MAX_WORD_ADDRESS or address % WORD_BYTES != 0:
        _cache_error("cache address is out of range or unaligned: {}".format(address))


def _memory_error(message: str) -> NoReturn:
    raise MemoryAccessError(message)


def _cache_error(message: str) -> NoReturn:
    raise CacheAccessError(message)
