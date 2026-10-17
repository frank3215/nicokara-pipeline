#!/usr/bin/env python3
"""Build the karaoke ASS with the upstream render layer.

Alignment comes from FA-Kara (this song has no QRC per-character track); the
layout comes from Mihaly-Ma/karaoke-video-maker's ``render`` package:

* ``LibassMetrics`` asks libass itself for advance widths by rendering marker
  blocks, so ruby sits on the advance slot rather than an ink-bbox estimate.
* ``AssBuilder`` owns the two alternating slots, fade-in lead and the outline
  flipping colour with the fill.

One behaviour is changed here rather than inherited: the builder wraps over-wide
lines *at render time*, so a single lyric occupies both slots and starves the
next line. We split such lines into separate ``Line`` objects before layout,
reusing the builder's own advance metrics to pick the break point.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ref" / "kvm" / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from kvm.models.karaoke import (  # noqa: E402
    KaraokeProject,
    KaraokeStyle,
    Line,
    RubySpan,
    Token,
)
from kvm.render.ass_builder import AssBuilder  # noqa: E402
from kvm.render.text_metrics import FontSpec, LibassMetrics  # noqa: E402

from utils_shim import parse_time_to_hundredths as P  # noqa: E402

FONT_CHAIN = ["Hiragino Kaku Gothic ProN"]
FONT_SIZE = 54
MARGIN_V = 44
MARGIN_H = 84
LINE_GAP = 30
OUT_W, OUT_H = 1280, 720

# Measured bias of the MMS_FA alignment against vocal onsets:
#   p50 -24 ms, p75 +79 ms, p90 +178 ms -> a right tail of lateness.
# FA-Kara ships -150 ms as the default offset for its ruby LRC, so two
# independent signals agree on the order of magnitude.
SHIFT_MS = -150

# A line whose sung span is this short is an alignment artefact, not something a
# viewer could read. Worse, it still claims a display slot for an instant, which
# can push the *next* line's entry past its own first note (seen on the "oh"
# interjection: 50 ms in slot 1 delayed the following line by 0.70 s).
MIN_LINE_MS = 250


def split_lines(items):
    lines, cur = [], []
    for it in items:
        if it.get("type") == 0 and it.get("orig") == "\n":
            if cur:
                lines.append(cur)
            cur = []
        else:
            cur.append(it)
    if cur:
        lines.append(cur)
    return lines


def to_units(line_items):
    """Collapse mora-continuation entries into their owning glyph."""
    units, open_kanji = [], None
    for it in line_items:
        kind, orig = it.get("type"), it.get("orig", "")
        if kind == 2:
            if orig:
                u = {"text": orig, "ruby": [it.get("ruby", "")],
                     "start": it.get("start"), "end": it.get("end"), "kind": 2}
                units.append(u)
                open_kanji = u
            elif open_kanji is not None:
                open_kanji["ruby"].append(it.get("ruby", ""))
                if it.get("end"):
                    open_kanji["end"] = it["end"]
        elif orig:
            units.append({"text": orig, "ruby": [], "start": it.get("start"),
                          "end": it.get("end"), "kind": kind})
            open_kanji = None
    for u in units:
        u["ruby"] = "".join(u["ruby"])
    return units


def build_line(units) -> Line | None:
    timed = [u for u in units if u.get("start") and u.get("end")]
    if not timed:
        return None

    tokens: list[Token] = []
    ruby: list[RubySpan] = []
    cursor = 0

    for u in units:
        text = u["text"]
        if not text:
            continue
        if u.get("start") and u.get("end"):
            s = P(u["start"]) / 100 * 1000 + SHIFT_MS
            e = P(u["end"]) / 100 * 1000 + SHIFT_MS
            s = max(0.0, s)
            e = max(s + 10.0, e)
            n = len(text)
            step = max(1.0, (e - s) / n)
            for k, ch in enumerate(text):
                tokens.append(Token(text=ch, start_ms=int(round(s + step * k)),
                                    dur_ms=int(round(step))))
            if u["kind"] == 2 and u["ruby"] and u["ruby"] != text:
                ruby.append(RubySpan(start=cursor, end=cursor + len(text),
                                     text=u["ruby"]))
        else:
            if tokens:
                tokens[-1].text += text
            elif text.strip():
                return None
            cursor += len(text)
            continue
        cursor += len(text)

    if not tokens:
        return None

    for i in range(len(tokens) - 1, 0, -1):
        if tokens[i].dur_ms <= 0:
            tokens[i - 1].text += tokens[i].text
            del tokens[i]

    limit = sum(len(t.text) for t in tokens)
    for r in ruby:
        r.start = min(r.start, limit)
        r.end = min(r.end, limit)
    ruby = [r for r in ruby if r.end > r.start]
    return Line(tokens=tokens, ruby=ruby)


# --------------------------------------------------------------- pre-layout fit
def _pick_split(line: Line, cum: list[int], avail: int) -> int:
    """Pick a token boundary that yields two rows which both fit.

    Prefers a real pause (largest gap between tokens), never cuts inside a ruby
    span, and falls back to the furthest boundary that still fits.
    """
    n = len(line.tokens)
    if n < 2 or not cum:
        return 0

    offsets, acc = [], 0
    for t in line.tokens:
        acc += len(t.text)
        offsets.append(acc)

    total = cum[-1]
    inside_ruby = {off for r in line.ruby for off in offsets if r.start < off < r.end}

    def width_at(i: int) -> int:
        idx = offsets[i] - 1
        return cum[idx] if 0 <= idx < len(cum) else total

    best_gap, best_i = -1, 0
    for i in range(n - 1):
        if offsets[i] in inside_ruby:
            continue
        w = width_at(i)
        if w <= avail and (total - w) <= avail:
            gap = line.tokens[i + 1].start_ms - line.tokens[i].end_ms
            if gap > best_gap:
                best_gap, best_i = gap, i + 1
    if best_i:
        return best_i

    for i in range(n - 2, 0, -1):
        if offsets[i] in inside_ruby:
            continue
        if width_at(i) <= avail:
            return i
    return 0


def _split(line: Line, k: int) -> tuple[Line, Line]:
    left_t, right_t = line.tokens[:k], line.tokens[k:]
    off = sum(len(t.text) for t in left_t)
    left_r = [RubySpan(r.start, r.end, r.text, r.source, r.locked)
              for r in line.ruby if r.end <= off]
    right_r = [RubySpan(r.start - off, r.end - off, r.text, r.source, r.locked)
               for r in line.ruby if r.start >= off]
    return Line(tokens=left_t, ruby=left_r), Line(tokens=right_t, ruby=right_r)


def split_to_fit(lines, metrics, spec, avail: int) -> list[Line]:
    out: list[Line] = []
    queue = list(lines)
    while queue:
        cur = queue.pop(0)
        text = "".join(t.text for t in cur.tokens)
        if not text:
            continue
        cum = metrics.advances(text, spec)
        total = cum[-1] if cum else 0
        if total <= avail or len(cur.tokens) < 2:
            out.append(cur)
            continue
        k = _pick_split(cur, cum, avail)
        if k <= 0 or k >= len(cur.tokens):
            out.append(cur)
            continue
        left, right = _split(cur, k)
        queue = [left, right] + queue
    return out


def drop_degenerate(lines: list[Line]) -> tuple[list[Line], list[tuple[int, int]]]:
    kept, dropped = [], []
    for ln in lines:
        if not ln.tokens:
            continue
        start = min(t.start_ms for t in ln.tokens)
        end = max(t.end_ms for t in ln.tokens)
        if end - start < MIN_LINE_MS:
            dropped.append((start, end - start))
            continue
        kept.append(ln)
    return kept, dropped


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    global SHIFT_MS
    if len(sys.argv) > 3:
        SHIFT_MS = int(sys.argv[3])

    items = json.loads(src.read_text(encoding="utf-8"))
    lines = []
    for line_items in split_lines(items):
        ln = build_line(to_units(line_items))
        if ln is not None:
            lines.append(ln)

    style = KaraokeStyle(
        font_names=FONT_CHAIN,
        font_size=FONT_SIZE,
        bold=False,
        margin_v=MARGIN_V,
        margin_h=MARGIN_H,
        line_gap=LINE_GAP,
        slot_gap_ms=0,
        credits_enabled=False,
        stagger=False,
    )

    metrics = LibassMetrics(str(ROOT / "bin" / "ffmpeg"))
    spec = FontSpec(name=FONT_CHAIN[0], size=FONT_SIZE, bold=False)
    avail = OUT_W - 2 * MARGIN_H
    # pre-split with a tighter budget than the renderer uses, so AssBuilder's own
    # wrap (which would eat a second slot) can never trigger
    before = len(lines)
    lines, dropped = drop_degenerate(lines)
    for at_ms, dur in dropped:
        print(f"  dropped {dur:>4d} ms line at {at_ms / 1000:7.2f}s")
    lines = split_to_fit(lines, metrics, spec, avail - 8)

    project = KaraokeProject(
        title="HATSUBOSHI KING",
        artist="LILJA-MC",
        lines=lines,
        style=style,
        video_width=OUT_W,
        video_height=OUT_H,
    )

    ass = AssBuilder(project, metrics).build()
    dst.write_text(ass, encoding="utf-8")
    print(f"lines={before} -> {len(lines)} after fit  "
          f"tokens={sum(len(l.tokens) for l in lines)}  "
          f"ruby={sum(len(l.ruby) for l in lines)}")
    print(f"shift={SHIFT_MS:+d} ms   avail={avail}px")
    print(f"wrote {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
