#!/usr/bin/env python3
"""SUPERSEDED by upstream_ass.py -- kept only as a reference.

This is the hand-written ASS layer that came before the switch to
karaoke-video-maker's AssBuilder. It is *not* on the supported path: its layout
predates the fixes documented in README section "The five things that actually
bite" (slot parity, pre-layout splitting, slot gap). What it still shows
usefully is `calibrate()` -- deriving libass's real font scale by rendering
`彼` x8 and comparing the advance against Pillow's.

Timed lyric structure -> ASS karaoke subtitle (per-syllable \\kf wipe + ruby).

Reads the JSON produced by align.py and writes an .ass laid out for a
1280x720 frame, with furigana positioned above each kanji group.

Font metrics note
-----------------
libass does not render a style's ``Fontsize`` at that pixel em size; on this
build it renders at ~0.81x. Measured with HarfBuzz/PIL (which agree with each
other) versus an actual libass render of the same font:

    harfbuzz / PIL advance for 彼 @ Fontsize 56 -> 56.00 px
    libass    rendered advance for 彼 @ Fontsize 56 -> 45.43 px

The ratio is constant across kanji / kana / latin / digits / punctuation and
across font sizes, so it is a pure scale factor. ``calibrate()`` measures it at
build time by rendering a probe through the very same libass binary, which
keeps the ruby positions correct without hardcoding a magic number.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFont

from utils_shim import parse_time_to_hundredths

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "bin" / "ffmpeg"
WORK = ROOT / "work"

# ---------------------------------------------------------------- layout knobs
PLAY_RES_X, PLAY_RES_Y = 1280, 720
FONT_NAME = "Hiragino Kaku Gothic ProN"
FONT_FILE = "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"
VISUAL_MAIN = 54        # desired on-screen glyph size in px (720p frame)
VISUAL_RUBY = 26
MARGIN_V = 116
RUBY_Y = 543
LEAD_CS = 30            # show a line 300ms before its first syllable
TAIL_CS = 40
SAFE_W = 1180.0
CENTER_X = PLAY_RES_X / 2
CALIB_SIZE = 56         # reference size for measuring the libass scale

# &HAABBGGRR
COL_SUNG = "&H0000C5FF"      # amber
COL_UNSUNG = "&H00FFFFFF"    # white
COL_OUTLINE = "&H00000000"
COL_RUBY = "&H00D9D9D9"      # light grey
COL_RUBY_OUTLINE = "&H00202020"

_font_cache: dict[int, ImageFont.FreeTypeFont] = {}


def font(size: int) -> ImageFont.FreeTypeFont:
    key = max(1, int(round(size)))
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(FONT_FILE, key, index=0)
    return _font_cache[key]


def pil_advance(text: str, size: int) -> float:
    return font(size).getlength(text) if text else 0.0


# ------------------------------------------------------------------ libass cal
def _measure_libass_advance(size: int, n: int = 8) -> float:
    """Render n copies of 彼 through libass and derive its real glyph advance."""
    style = (f"Style: C,{FONT_NAME},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,"
             "&H00000000,-1,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1\n")
    ink = _render_probe(
        _probe_header(style)
        + f"Dialogue: 0,0:00:00.00,0:00:10.00,C,,0,0,0,,{{\\an7\\pos(60,60)}}{'彼' * n}\n"
    )
    xs = np.where(ink.any(0))[0]
    if len(xs) < 2:
        raise RuntimeError("calibration probe produced no ink")
    starts, prev = [xs[0]], xs[0]
    for x in xs[1:]:
        if x - prev > 1:
            starts.append(x)
        prev = x
    if len(starts) < 2:
        raise RuntimeError("calibration probe could not separate glyphs")
    return (starts[-1] - starts[0]) / (len(starts) - 1)


def calibrate() -> float:
    cache = WORK / "_libass_scale.json"
    key = f"{FONT_NAME}|{FONT_FILE}|bold=-1"
    if cache.exists():
        try:
            saved = json.loads(cache.read_text(encoding="utf-8"))
            if saved.get("key") == key:
                return float(saved["scale"])
        except (ValueError, KeyError):
            pass
    measured = _measure_libass_advance(CALIB_SIZE)
    scale = measured / pil_advance("彼", CALIB_SIZE)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"key": key, "scale": scale,
                                 "probe_advance": measured}), encoding="utf-8")
    return scale


def _render_probe(ass_text: str) -> np.ndarray:
    probe = WORK / "_calib_probe.ass"
    png = WORK / "_calib_probe.png"
    probe.write_text(ass_text, encoding="utf-8")
    subprocess.run(
        [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"color=c=black:s={PLAY_RES_X}x{PLAY_RES_Y}:r=1",
         "-vf", f"subtitles={probe}:fontsdir=/System/Library/Fonts",
         "-frames:v", "1", str(png)],
        check=True,
    )
    return np.asarray(Image.open(png).convert("L")) > 40


def _probe_header(styles: str) -> str:
    return (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {PLAY_RES_X}\nPlayResY: {PLAY_RES_Y}\nWrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        f"{styles}[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, "
        "MarginR, MarginV, Effect, Text\n"
    )


def measure_base_rows(main_size: int) -> tuple[int, int]:
    """Where libass actually lands a bottom-aligned Main line with MARGIN_V.

    The margin is measured from the bottom of the full line box, not the ink,
    so the ink sits well above ``PLAY_RES_Y - MARGIN_V``. Measuring beats
    guessing.
    """
    style = (f"Style: Main,{FONT_NAME},{main_size},&H00FFFFFF,&H00FFFFFF,"
             f"&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,2,24,24,"
             f"{MARGIN_V},1\n")
    ink = _render_probe(
        _probe_header(style)
        + "Dialogue: 0,0:00:00.00,0:00:10.00,Main,,0,0,0,,彼こそが我らの\n"
    )
    rows = np.where(ink.any(1))[0]
    if not len(rows):
        raise RuntimeError("base probe produced no ink")
    return int(rows.min()), int(rows.max())


SCALE = calibrate()
MAIN_SIZE = round(VISUAL_MAIN / SCALE)
RUBY_SIZE = round(VISUAL_RUBY / SCALE)
BASE_TOP, BASE_BOTTOM = measure_base_rows(MAIN_SIZE)
# Pin the main line with \an2\pos instead of relying on Alignment+MarginV.
# A bottom-aligned event without \pos is subject to libass collision avoidance:
# whenever two of them are on screen at once (which adjacent lines are, because
# of the lead-in/lead-out padding) libass shoves one upward. \pos is immune.
MAIN_ANCHOR_Y = PLAY_RES_Y - MARGIN_V
RUBY_GAP = 6
RUBY_Y = BASE_TOP - RUBY_GAP - VISUAL_RUBY * 0.46


def text_width(text: str, size: int) -> float:
    """Width libass will actually use, in frame pixels."""
    return pil_advance(text, size) * SCALE


def esc(text: str) -> str:
    return text.replace("\\", "＼").replace("{", "｛").replace("}", "｝")


def ass_time(cs: int) -> str:
    cs = max(0, int(round(cs)))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# ------------------------------------------------------------------- structure
def split_lines(items: list[dict]) -> list[list[dict]]:
    lines, cur = [], []
    for item in items:
        if item.get("type") == 0 and item.get("orig") == "\n":
            if cur:
                lines.append(cur)
            cur = []
        else:
            cur.append(item)
    if cur:
        lines.append(cur)
    return lines


def to_units(line_items: list[dict]) -> list[dict]:
    """Collapse mora-continuation entries into their owning glyph."""
    units: list[dict] = []
    open_kanji: dict | None = None
    for item in line_items:
        kind = item.get("type")
        orig = item.get("orig", "")
        if kind == 2:
            if orig:
                u = {"text": orig, "ruby": [item.get("ruby", "")],
                     "start": item.get("start"), "end": item.get("end"), "kind": 2}
                units.append(u)
                open_kanji = u
            elif open_kanji is not None:
                open_kanji["ruby"].append(item.get("ruby", ""))
                if item.get("end"):
                    open_kanji["end"] = item["end"]
        elif orig:
            units.append({"text": orig, "ruby": [], "start": item.get("start"),
                          "end": item.get("end"), "kind": kind})
            open_kanji = None
    for u in units:
        u["ruby"] = "".join(u["ruby"])
    return units


def render_line(units: list[dict]):
    timed = [u for u in units if u.get("start") and u.get("end")]
    if not timed:
        return None, [], 0, 0, 0.0

    widths = [text_width(u["text"], MAIN_SIZE) for u in units]
    scale = min(1.0, SAFE_W / max(1.0, sum(widths)))
    if scale < 1.0:
        main_size = MAIN_SIZE * scale
        widths = [text_width(u["text"], main_size) for u in units]
    else:
        main_size = MAIN_SIZE

    start_cs = parse_time_to_hundredths(timed[0]["start"]) - LEAD_CS
    end_cs = parse_time_to_hundredths(timed[-1]["end"]) + TAIL_CS
    stamps = [parse_time_to_hundredths(u["start"]) for u in timed]

    shrink = f"\\fs{main_size:.1f}" if scale < 1.0 else ""
    body, k, started = [], 0, False
    for u in units:
        if u.get("start") and u.get("end"):
            nxt = stamps[k + 1] if k + 1 < len(stamps) else parse_time_to_hundredths(u["end"])
            dur = max(1, nxt - stamps[k])
            if not started:
                body.append("{\\kf%d%s}" % (LEAD_CS, shrink))
                started = True
            body.append("{\\kf%d}%s" % (dur, esc(u["text"])))
            k += 1
        else:
            body.append(esc(u["text"]))
    if not started:
        return None, [], 0, 0, 0.0
    body.append("{\\kf%d}" % TAIL_CS)

    total = sum(widths)
    x = CENTER_X - total / 2
    rubies = []
    for u, w in zip(units, widths):
        if u["kind"] == 2 and u["ruby"] and u["ruby"] != u["text"]:
            rubies.append({"x": x + w / 2, "text": esc(u["ruby"]),
                           "size": RUBY_SIZE * scale if scale < 1.0 else None})
        x += w
    return "".join(body), rubies, start_cs, end_cs, scale


HEADER = f"""[Script Info]
Title: nicokara
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: {PLAY_RES_X}
PlayResY: {PLAY_RES_Y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{FONT_NAME},{MAIN_SIZE},{COL_SUNG},{COL_UNSUNG},{COL_OUTLINE},&H64000000,-1,0,0,0,100,100,0,0,1,3.2,1.6,2,24,24,{MARGIN_V},1
Style: Ruby,{FONT_NAME},{RUBY_SIZE},{COL_RUBY},{COL_RUBY},{COL_RUBY_OUTLINE},&H64000000,-1,0,0,0,100,100,0,0,1,2.0,0.8,2,24,24,{RUBY_Y},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    items = json.loads(src.read_text(encoding="utf-8"))

    events, n_ruby, shrunk, lines = [], 0, 0, 0
    prev_end = None
    for line_items in split_lines(items):
        text, rubies, start_cs, end_cs, sc = render_line(to_units(line_items))
        if not text:
            continue
        # the lead-in/out padding makes adjacent windows overlap; close each
        # line at the previous one's end so two lyrics are never on screen
        if prev_end is not None and start_cs < prev_end:
            start_cs = prev_end
        if end_cs <= start_cs:
            end_cs = start_cs + 10
        prev_end = end_cs

        lines += 1
        shrunk += sc < 1.0
        events.append(
            f"Dialogue: 0,{ass_time(start_cs)},{ass_time(end_cs)},Main,,0,0,0,,"
            f"{{\\an2\\pos({CENTER_X:.0f},{MAIN_ANCHOR_Y})}}{text}"
        )
        for r in rubies:
            n_ruby += 1
            fs = f"\\fs{r['size']:.1f}" if r["size"] else ""
            events.append(
                f"Dialogue: 0,{ass_time(start_cs)},{ass_time(end_cs)},Ruby,,0,0,0,,"
                f"{{\\an5\\pos({r['x']:.1f},{RUBY_Y:.1f}){fs}}}{r['text']}"
            )

    dst.write_text(HEADER + "\n".join(events) + "\n", encoding="utf-8")
    print(f"libass scale={SCALE:.4f}  Main={MAIN_SIZE}px Ruby={RUBY_SIZE}px "
          f"(visual {VISUAL_MAIN}/{VISUAL_RUBY})")
    print(f"base ink top={BASE_TOP}  main anchor y={MAIN_ANCHOR_Y}  ruby y={RUBY_Y:.1f}")
    print(f"lines={lines} ruby={n_ruby} shrunk={shrunk} events={len(events)}")
    print(f"wrote {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
