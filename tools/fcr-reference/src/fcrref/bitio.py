"""MSB-first bit packing.

Bits are written most-significant-first within each byte. The final byte
is zero-padded. This ordering is normative.
"""

from __future__ import annotations


class BitWriter:
    """Accumulates bits MSB-first into a byte buffer."""

    def __init__(self) -> None:
        self._bytes = bytearray()
        self._acc = 0
        self._nbits = 0
        self._total = 0

    def write_bits(self, value: int, count: int) -> None:
        if count < 0 or count > 32:
            raise ValueError(f"count must be 0..32, got {count}")
        if count == 0:
            return
        if value < 0 or value >= (1 << count):
            raise ValueError(f"value {value} does not fit in {count} bits")
        self._acc = (self._acc << count) | value
        self._nbits += count
        self._total += count
        while self._nbits >= 8:
            self._nbits -= 8
            self._bytes.append((self._acc >> self._nbits) & 0xFF)
        self._acc &= (1 << self._nbits) - 1

    def bit_length(self) -> int:
        """Total bits written so far, excluding flush padding."""
        return self._total

    def flush(self) -> bytes:
        """Zero-pad to a byte boundary and return the buffer."""
        if self._nbits:
            self._bytes.append((self._acc << (8 - self._nbits)) & 0xFF)
            self._acc = 0
            self._nbits = 0
        return bytes(self._bytes)


class BitReader:
    """Reads bits MSB-first from a byte buffer."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0  # bit position

    def read_bits(self, count: int) -> int:
        if count < 0 or count > 32:
            raise ValueError(f"count must be 0..32, got {count}")
        if count == 0:
            return 0
        if self._pos + count > len(self._data) * 8:
            raise EOFError("read past end of bitstream")
        value = 0
        remaining = count
        while remaining:
            byte_index = self._pos >> 3
            bit_offset = self._pos & 7
            available = 8 - bit_offset
            take = min(available, remaining)
            byte = self._data[byte_index]
            shift = available - take
            mask = (1 << take) - 1
            value = (value << take) | ((byte >> shift) & mask)
            self._pos += take
            remaining -= take
        return value

    def read_unary(self, limit: int) -> int:
        """Count zeros until a 1 bit. Returns `limit` if that many zeros
        are seen, consuming exactly `limit` bits and no terminator."""
        count = 0
        while count < limit:
            if self.read_bits(1):
                return count
            count += 1
        return limit

    def bit_position(self) -> int:
        return self._pos
