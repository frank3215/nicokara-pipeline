#!/usr/bin/env python3
"""Emit the ruby-annotated LRC that NicoKaraMaker3 / RhythmicaLyrics consume.

This is the format FA-Kara targets in `norm2lrc.py`; the ASS this project
produces for libass burn-in is *not* readable by NicoKaraMaker3, which does its
own layout from a ruby LRC plus the off-vocal track.

    python ruby_lrc.py align_trim.json outdir [shift_ms]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ref" / "FA-Kara"))

from norm2lrc import process_main, process_ruby_V2, process_rlf  # noqa: E402
from utils_basic import (  # noqa: E402
    format_hundredths_to_time_str,
    parse_time_to_hundredths,
)

SHIFT_MS = -150
BPM = 60
BEATS_PER_BAR = 3


def shift(items: list[dict], ms: int) -> list[dict]:
    """Move every stamped time by `ms`, keeping the [MM:SS:CC] wire format."""
    if not ms:
        return items
    delta = round(ms / 10)  # centiseconds
    out = []
    for it in items:
        it = dict(it)
        for key in ("start", "end"):
            if it.get(key):
                cs = max(0, parse_time_to_hundredths(it[key]) + delta)
                it[key] = format_hundredths_to_time_str(cs)
        out.append(it)
    return out


def main() -> int:
    src, outdir = Path(sys.argv[1]), Path(sys.argv[2])
    global SHIFT_MS
    if len(sys.argv) > 3:
        SHIFT_MS = int(sys.argv[3])

    items = shift(json.loads(src.read_text(encoding="utf-8")), SHIFT_MS)
    outdir.mkdir(parents=True, exist_ok=True)

    ruby = process_ruby_V2(items)
    content = f"{process_main(items, SHIFT_MS, BPM, BEATS_PER_BAR)}\n{ruby}"
    (outdir / "o_ruby.lrc").write_text(content, encoding="utf-8")
    (outdir / "o_rlf.lrc").write_text(process_rlf(items), encoding="utf-8")

    lines = content.splitlines()
    print(f"shift={SHIFT_MS:+d} ms")
    print(f"o_ruby.lrc : {len(lines)} lines, {len(content)} chars")
    print(f"o_rlf.lrc  : {len((outdir / 'o_rlf.lrc').read_text(encoding='utf-8').splitlines())} lines")
    print("--- tag lines only (lyric text omitted) ---")
    for l in lines:
        if l.startswith("@") or l.startswith("[ti:") or l.startswith("[ar:"):
            print("   " + l)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
