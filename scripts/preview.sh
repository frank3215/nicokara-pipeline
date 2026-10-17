#!/usr/bin/env bash
# Snapshot frames with the karaoke ASS burned in, for visual QA.
# -copyts keeps the original PTS so libass sees the real timestamp.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FFMPEG="$ROOT/bin/ffmpeg"
SRC="${1:?source video}"
ASS="${2:?ass subtitle}"
OUTDIR="${3:?out dir}"
shift 3

export XDG_CACHE_HOME="$ROOT/.cache"
mkdir -p "$XDG_CACHE_HOME" "$OUTDIR"

for t in "$@"; do
  name="$(printf '%s' "$t" | tr '.:' '__')"
  "$FFMPEG" -hide_banner -loglevel error -y -copyts -ss "$t" -i "$SRC" -frames:v 1 \
    -vf "scale=1280:720:flags=lanczos,subtitles='${ASS//\'/\\\'}':fontsdir='/System/Library/Fonts':original_size=1280x720" \
    "$OUTDIR/frame_${name}.png"
  echo "wrote $OUTDIR/frame_${name}.png"
done
