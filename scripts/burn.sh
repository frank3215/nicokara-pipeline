#!/usr/bin/env bash
# Burn the karaoke ASS onto the source video, upscaled to 720p for legible text.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FFMPEG="$ROOT/bin/ffmpeg"
SRC="${1:?source video}"
ASS="${2:?ass subtitle}"
OUT="${3:?output mp4}"
FONTS_DIR="${4:-/System/Library/Fonts}"

export XDG_CACHE_HOME="$ROOT/.cache"
mkdir -p "$XDG_CACHE_HOME"

"$FFMPEG" -hide_banner -loglevel warning -stats -y \
  -i "$SRC" \
  -vf "scale=1280:720:flags=lanczos,subtitles='${ASS//\'/\\\'}':fontsdir='${FONTS_DIR}':original_size=1280x720" \
  -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p \
  -c:a aac -b:a 192k \
  -movflags +faststart \
  "$OUT"
