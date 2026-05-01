#!/usr/bin/env bash
# Rasterize logo.svg → logo.png for Cognito hosted UI.
# Cognito accepts PNG/JPG/GIF only, 100KB max. SVG is not supported.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src="${here}/logo.svg"
dst="${here}/logo.png"

if [[ ! -f "${src}" ]]; then
  echo "missing: ${src}" >&2
  exit 1
fi

width=480
height=128

if command -v rsvg-convert >/dev/null 2>&1; then
  rsvg-convert -w "${width}" -h "${height}" -o "${dst}" "${src}"
elif command -v magick >/dev/null 2>&1; then
  magick -background none -density 300 "${src}" -resize "${width}x${height}" "${dst}"
elif command -v convert >/dev/null 2>&1; then
  convert -background none -density 300 "${src}" -resize "${width}x${height}" "${dst}"
else
  echo "need rsvg-convert (brew install librsvg) or ImageMagick (brew install imagemagick)" >&2
  exit 2
fi

size=$(wc -c < "${dst}" | tr -d ' ')
if (( size > 100000 )); then
  echo "warning: ${dst} is ${size}B — Cognito rejects >100KB" >&2
fi

echo "wrote ${dst} (${size}B)"
