import random

import pytest

from fcrref.bitio import BitReader, BitWriter


def test_write_then_read_single_value():
    w = BitWriter()
    w.write_bits(0b101, 3)
    data = w.flush()
    r = BitReader(data)
    assert r.read_bits(3) == 0b101


def test_msb_first_byte_layout():
    """Bits pack MSB-first: 0b101 in 3 bits then 0b11111 in 5 bits == 0xBF."""
    w = BitWriter()
    w.write_bits(0b101, 3)
    w.write_bits(0b11111, 5)
    assert w.flush() == bytes([0b10111111])


def test_flush_pads_with_zeros():
    w = BitWriter()
    w.write_bits(1, 1)
    assert w.flush() == bytes([0b10000000])


def test_bit_length_tracks_written_bits():
    w = BitWriter()
    w.write_bits(0, 5)
    w.write_bits(0, 7)
    assert w.bit_length() == 12


def test_roundtrip_random_sequence():
    rng = random.Random(20260819)
    values = []
    w = BitWriter()
    for _ in range(2000):
        count = rng.randint(1, 24)
        value = rng.randrange(0, 1 << count)
        values.append((value, count))
        w.write_bits(value, count)
    r = BitReader(w.flush())
    for value, count in values:
        assert r.read_bits(count) == value


def test_read_unary_counts_zeros_before_one():
    w = BitWriter()
    w.write_bits(1, 6)  # five zeros then a one
    r = BitReader(w.flush())
    assert r.read_unary(24) == 5


def test_read_unary_stops_at_limit():
    w = BitWriter()
    w.write_bits(0, 24)
    w.write_bits(0xFF, 8)
    r = BitReader(w.flush())
    assert r.read_unary(24) == 24


def test_write_bits_rejects_out_of_range_value():
    w = BitWriter()
    with pytest.raises(ValueError):
        w.write_bits(4, 2)


def test_read_past_end_raises():
    r = BitReader(bytes([0xFF]))
    r.read_bits(8)
    with pytest.raises(EOFError):
        r.read_bits(1)
