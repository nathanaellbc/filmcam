"""Look LUTs and the false-colour IRE table.

LUTs are Adobe .cube 3-D LUTs, the format the Metal shader in Stage M1
will consume. The false-colour band table is normative and must match
the on-screen key described in spec 7.
"""

from __future__ import annotations

import numpy as np

# (ire_low, ire_high, hex colour). Contiguous, covering 0..100.
FALSE_COLOUR_BANDS: tuple[tuple[float, float, str], ...] = (
    (0.0, 2.5, "#2b2b8f"),    # crush
    (2.5, 20.0, "#1f7fbf"),   # deep shadow
    (20.0, 42.0, "#2f9e4a"),  # shadow
    (42.0, 52.0, "#d8d84a"),  # skin, low
    (52.0, 62.0, "#e08a2a"),  # skin, mid
    (62.0, 75.0, "#c9c9c9"),  # 70 IRE reference grey
    (75.0, 95.0, "#e8437a"),  # skin, high / highlight
    (95.0, 100.0, "#ff2020"), # clip
)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def identity_lut(size: int = 33) -> np.ndarray:
    axis = np.linspace(0.0, 1.0, size)
    r, g, b = np.meshgrid(axis, axis, axis, indexing="ij")
    return np.stack([r, g, b], axis=-1)


def rec709_lut(size: int = 33) -> np.ndarray:
    """Linear light in, Rec.709 OETF out."""
    lut = identity_lut(size)
    v = np.clip(lut, 0.0, 1.0)
    low = v * 4.5
    high = 1.099 * np.power(np.maximum(v, 1e-12), 0.45) - 0.099
    return np.where(v < 0.018, low, high).clip(0.0, 1.0)


def cineon_to_rec709_lut(size: int = 33) -> np.ndarray:
    """Cineon log in (10-bit density, black 95, white 685, gamma 0.6),
    Rec.709 out."""
    lut = identity_lut(size)
    code = lut * 1023.0
    black, white, gamma, density_per_code = 95.0, 685.0, 0.6, 0.002

    def to_linear(c: np.ndarray) -> np.ndarray:
        return np.power(10.0, (c - white) * density_per_code / gamma)

    floor = to_linear(np.array(black))
    linear = (to_linear(code) - floor) / (1.0 - floor)
    linear = np.clip(linear, 0.0, 1.0)

    low = linear * 4.5
    high = 1.099 * np.power(np.maximum(linear, 1e-12), 0.45) - 0.099
    return np.where(linear < 0.018, low, high).clip(0.0, 1.0)


def write_cube(path: str, lut: np.ndarray, title: str) -> None:
    if lut.ndim != 4 or lut.shape[3] != 3 or len({*lut.shape[:3]}) != 1:
        raise ValueError("lut must be (N, N, N, 3)")
    size = lut.shape[0]
    lines = [f'TITLE "{title}"', f"LUT_3D_SIZE {size}", "DOMAIN_MIN 0.0 0.0 0.0",
             "DOMAIN_MAX 1.0 1.0 1.0", ""]
    # .cube order: red varies fastest.
    for b in range(size):
        for g in range(size):
            for r in range(size):
                pixel = lut[r, g, b]
                lines.append(f"{pixel[0]:.6f} {pixel[1]:.6f} {pixel[2]:.6f}")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def read_cube(path: str) -> tuple[np.ndarray, str]:
    title = ""
    size = 0
    values: list[tuple[float, float, float]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("TITLE"):
                title = line.split('"')[1] if '"' in line else line[6:].strip()
            elif line.startswith("LUT_3D_SIZE"):
                size = int(line.split()[1])
            elif line.startswith("DOMAIN_"):
                continue
            else:
                parts = line.split()
                if len(parts) == 3:
                    values.append(tuple(float(p) for p in parts))

    if size == 0 or len(values) != size ** 3:
        raise ValueError(f"{path}: expected {size ** 3} entries, got {len(values)}")

    lut = np.empty((size, size, size, 3), dtype=np.float64)
    index = 0
    for b in range(size):
        for g in range(size):
            for r in range(size):
                lut[r, g, b] = values[index]
                index += 1
    return lut, title


def false_colour(ire: np.ndarray) -> np.ndarray:
    """Map IRE values (0..100) to the normative false-colour palette."""
    values = np.clip(np.asarray(ire, dtype=np.float64), 0.0, 100.0)
    out = np.zeros(values.shape + (3,), dtype=np.uint8)
    for low, high, colour in FALSE_COLOUR_BANDS:
        if high >= 100.0:
            mask = (values >= low) & (values <= high)
        else:
            mask = (values >= low) & (values < high)
        out[mask] = _hex_to_rgb(colour)
    return out
