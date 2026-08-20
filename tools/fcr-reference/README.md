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
