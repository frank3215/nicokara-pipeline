#!/usr/bin/env python3
"""Whisper (MLX) transcription with word timestamps.

Outputs a JSON blob and a plain lyric-lines text file.
Only aggregate statistics are printed to stdout.
"""
import json
import os
import sys

import mlx_whisper

REPO = os.environ.get("WHISPER_REPO", "mlx-community/whisper-large-v3-turbo")


def main() -> int:
    audio, out_json = sys.argv[1], sys.argv[2]
    res = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=REPO,
        language="ja",
        task="transcribe",
        word_timestamps=True,
        condition_on_previous_text=False,
        temperature=0.0,
        verbose=None,
    )
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)

    segments = res.get("segments", [])
    lines = [s["text"].strip() for s in segments if s["text"].strip()]
    with open(out_json.rsplit(".", 1)[0] + ".txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    words = sum(len(s.get("words", [])) for s in segments)
    chars = sum(len(line) for line in lines)
    dur = segments[-1]["end"] if segments else 0.0
    print(f"model={REPO}")
    print(f"segments={len(segments)} words={words} chars={chars} covered_until={dur:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
