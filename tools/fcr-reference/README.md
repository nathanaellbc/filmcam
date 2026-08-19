# fcr-reference

Reference implementation of the FilmCam `.fcr` container and its lossless
Rice codec. Platform-agnostic; no Apple dependencies.

## Install

    cd tools/fcr-reference
    python -m pip install -e ".[dev,dng]"

## Measure compression ratio on real footage

    python -m fcrref.analyze --input path/to/clip/*.dng

## Regenerate conformance vectors

    python -m fcrref.vectors --out vectors/

Regeneration must be byte-identical. If it is not, that is a bug.
