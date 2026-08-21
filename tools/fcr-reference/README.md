# fcr-reference

Reference implementation of the FilmCam `.fcr` container and its lossless
Rice codec. Platform-agnostic; no Apple dependencies.

## Install

    cd tools/fcr-reference
    python -m pip install -e ".[dev,dng]"

## Measure compression ratio on real footage

    python -m fcrref.analyze --input path/to/clip/*.dng

The bit depth is read from each DNG's white level and printed alongside
the ratio: scoring a 12-bit capture against a 14-bit baseline inflates
the result by ~17%, in the optimistic direction, against a 2.0:1
decision threshold. Headerless inputs cannot say, so declare it:

    python -m fcrref.analyze --input '*.raw16' --raw16 3024x4032 --bit-depth 12

## Regenerate conformance vectors

    python -m fcrref.vectors --out vectors/

Regeneration must be byte-identical. If it is not, that is a bug.

## Supported bit depths

The reference implementation encodes, decodes and measures at **10, 12 and
14-bit**, as a per-clip property. The container header carries `bitDepth`
and is the authority on a clip's depth; the codec and the conformance
vectors follow it.

Sample depth is capped at **14-bit** — the sensor's ceiling. The Rice
escape width `RAW_BITS` is fixed at **15** across all depths (decision D1):
a 14-bit residual zigzags to at most 32766, which is 15 bits, so every
shallower depth fits. Holding it constant costs ~24 bytes per frame on
escaped samples and means the entropy coder never varies with depth.

`bit_depth` parameters throughout the package default to 14
(`constants.BIT_DEPTH`), so existing callers and the original committed
vectors are unchanged. Conformance across depths is asserted by the suite:
`vectors/` holds 10-bit and 12-bit sources, frame payloads and full clips
alongside the 14-bit set, each recorded in `manifest.json` under
`supported_bit_depths`. A port is correct when it reproduces every SHA-256
in the manifest at all three depths.
