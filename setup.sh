#!/usr/bin/env bash
# Bootstrap everything the pipeline needs that is deliberately kept out of git.
#
# Clones the two upstream projects, fetches an ffmpeg that actually has libass,
# creates the venv and pulls the alignment model. Idempotent: re-running skips
# what is already in place.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "== 1/5 ffmpeg with libass =="
if [ -x bin/ffmpeg ] && bin/ffmpeg -hide_banner -filters 2>&1 | awk '{print $2}' | grep -qx subtitles; then
  echo "   already present: $(bin/ffmpeg -hide_banner -version | head -1)"
else
  # Homebrew's ffmpeg bottle is built WITHOUT libass, so it cannot burn subtitles.
  # imageio-ffmpeg ships a static build that has it.
  python3 -m pip install --quiet imageio-ffmpeg
  BIN=$(python3 - <<'PY'
import imageio_ffmpeg, os
print(imageio_ffmpeg.get_ffmpeg_exe())
PY
)
  mkdir -p bin
  cp "$BIN" bin/ffmpeg
  chmod +x bin/ffmpeg
  bin/ffmpeg -hide_banner -filters 2>&1 | awk '{print $2}' | grep -qx subtitles \
    || { echo "fetched ffmpeg still lacks libass"; exit 1; }
  echo "   installed $(bin/ffmpeg -hide_banner -version | head -1)"
fi

echo "== 2/5 upstream checkouts =="
mkdir -p ref
if [ ! -d ref/FA-Kara ]; then
  git clone --depth 1 https://github.com/moriwx/FA-Kara.git ref/FA-Kara
else
  echo "   ref/FA-Kara present"
fi
if [ ! -d ref/kvm ]; then
  git clone --depth 1 https://github.com/Mihaly-Ma/karaoke-video-maker.git ref/kvm
else
  echo "   ref/kvm present"
fi

echo "== 3/5 python venv =="
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --quiet -U pip
.venv/bin/python -m pip install --quiet -r requirements.txt

echo "== 4/5 nltk cmudict =="
export NLTK_DATA="$ROOT/.nltk_data"
.venv/bin/python - <<'PY'
import os, nltk
os.makedirs(os.environ["NLTK_DATA"], exist_ok=True)
nltk.download("cmudict", quiet=True)
from nltk.corpus import cmudict
print("   cmudict entries:", len(cmudict.dict()))
PY

echo "== 5/5 alignment model =="
# NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn: MMS_FA fine-tuned on Japanese
# karaoke data. ~1.2 GB, cached under .hf so it survives a re-clone.
export HF_HOME="$ROOT/.hf"
.venv/bin/python - <<'PY'
from huggingface_hub import snapshot_download
p = snapshot_download("NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn")
print("   model at", p)
PY

cat <<'EOF'

Done. Next:

  1. put the Japanese lyric lines in work/lyrics_ja.txt (one line per sung phrase)
  2. mkdir -p work && echo "<path to source video>" > /tmp/src
  3. run the pipeline -- see README.md "Running" for the exact commands

Note: work/ is gitignored on purpose. The lyrics and any generated subtitle stay
local.
EOF
