# nicokara-pipeline

Turn a song + its lyric lines into a KTV-style ニコカラ subtitle track: per-syllable
colour sweep, furigana (振り仮名) sitting on the correct kanji, and two alternating
lyric rows so the next line is readable before it is sung.

Two output formats:

| Output | Consumer |
|---|---|
| `kara.ass` + burned `.mp4` | anything libass-based (`ffmpeg`, `mpv`, VLC) |
| `o_ruby.lrc` / `o_rlf.lrc` | NicoKaraMaker3 / RhythmicaLyrics (Windows) |

**This repo contains no lyrics and no media.** `work/` is gitignored; you supply the
lyric text and the video yourself.

## Why these two upstream projects

The interesting work is split, not duplicated:

| Stage | Upstream | Why |
|---|---|---|
| audio → per-syllable timing | [moriwx/FA-Kara](https://github.com/moriwx/FA-Kara) | wraps the MMS_FA model fine-tuned on Japanese karaoke data |
| layout → ASS | [Mihaly-Ma/karaoke-video-maker](https://github.com/Mihaly-Ma/karaoke-video-maker) | its `LibassMetrics` asks libass for real advance widths; its `AssBuilder` owns the two-slot layout |

A hand-written ASS layer was tried first and produced three separate bugs, all
documented below. The upstream render layer already solves them.

## Install

```bash
./setup.sh          # ffmpeg+libass, ref/ checkouts, venv, cmudict, aligner model
```

Requires `python3`, `git`, and network access. `setup.sh` is idempotent.

> **`ffmpeg` must have libass.** The mainline Homebrew bottle does **not** — it ships
> without `--enable-libass`, so `-filters` has no `subtitles` / `ass` / `drawtext`
> and burning has nothing to run. `setup.sh` fetches a static build that does have it
> and checks by capability, not by version.

## Running

```bash
export NLTK_DATA=$PWD/.nltk_data HF_HOME=$PWD/.hf XDG_CACHE_HOME=$PWD/.cache

# 1. audio + vocal separation
bin/ffmpeg -y -i "$SRC" -vn -ac 2 -ar 44100 -c:a pcm_s16le work/full.wav
TORCH_HOME=$PWD/.torch .venv/bin/python -m demucs --two-stems=vocals -d cpu \
  -o work/separated work/full.wav

# 2. readings: plain kana lines -> {漢字|かんじ} form
.venv/bin/python scripts/autoruby.py < work/lyrics_ja.txt > work/lyrics_haru.txt

# 3. forced alignment (args: lyrics audio out [wrap] [silence-trim])
.venv/bin/python scripts/align.py work/lyrics_haru.txt \
  work/separated/htdemucs/full/vocals.wav work/align.json 0 1

# 4. ASS  (args: align out [shift_ms])
.venv/bin/python scripts/upstream_ass.py work/align.json work/kara.ass -150

# 5. burn / preview
./scripts/burn.sh "$SRC" work/kara.ass out.mp4
./scripts/preview.sh "$SRC" work/kara.ass work/preview 42.4 105

# optional: ruby LRC for NicoKaraMaker3
.venv/bin/python scripts/ruby_lrc.py work/align.json work/lrc -150
```

`scripts/asr.py` is an optional Whisper (MLX) bootstrap that drafts lyric lines when
you have no text yet. Its output goes to a file only.

## The five things that actually bite

Everything here was found by measurement, not assumption.

### 1. `Fontsize` is not a pixel size

HarfBuzz and Pillow agree that a full-width glyph at `Fontsize 56` advances 56 px.
libass renders the same font at **42 px**. The ratio is constant across kanji / kana /
latin / digits / punctuation and across sizes — and it **depends on `Bold`**
(0.811 for `Bold:0`, 0.750 for `Bold:-1`).

So a hand-computed layout is wrong by ~1.23x, which reads as "the leftmost ruby drifts
left, the rightmost drifts right" — it expands about the line centre.

`LibassMetrics` solves this properly: it appends a `█` marker glyph and back-solves the
advance from pixels, so the numbers are *defined* to match the renderer. The naive
alternative — measuring the ink's right edge — is wrong because side bearings leak in;
it reports 45 vs 52 for what should be identical full-width glyphs.

### 2. Events without `\pos` get moved by collision avoidance

libass shifts non-`\pos` events upward so they do not overlap other events on the same
frame. With a lead-in/lead-out padding scheme adjacent lines *always* overlap, which
silently pushed one line up by 79 px.

Pin the main line with `{\an2\pos(cx, height - margin_v)}` instead: `\pos` events are
immune. Anchor semantics, measured: `\an7\pos(y)` → ink top `y+11`,
`\an5\pos(y)` → ink centre `y` (exact), `\an2\pos(y)` → ink bottom `y-11`.

### 3. A renderer that wraps at render time fights a two-slot layout

If an over-wide line is wrapped while rendering, that one lyric occupies **both** rows
and the following line loses its slot — it then appears late. Split over-wide lines
into separate `Line` objects *before* layout, with a budget slightly tighter than the
renderer's, so the renderer's own wrap can never fire.

Measure before blaming the content: one line was 1102 px against 1100 px available —
2 px over. A margin of 84 instead of 90 fixed it.

### 4. Line splitting at the alignment stage shifts slot parity

Inserting a newline during alignment splits one phrase into two lyric lines and shifts
every later line's slot parity by one, so the "current / next" pairing is wrong for the
rest of the song. Keep `wrap=0` at alignment time and let the layout step decide.

### 5. Degenerate lines claim a slot for an instant

Text that is not in the audio still gets tokens; the aligner crams them into ~50 ms
each. Diagnostics: a line is suspect when >30 % of its tokens are shorter than 60 ms
**and** the short ones are contiguous at the tail — scattered short mora are just fast
delivery.

Two consequences:

- unreadable text (a 50 ms line cannot be read), and
- worse, that line still holds a display slot for an instant. With slot alternation
  plus a 350 ms slot gap, the next line in the same slot can be forced to start *after*
  its own first note. Measured: lead −0.70 s and −0.55 s on two lines.

Drop lines shorter than ~250 ms and set `slot_gap_ms = 0`. Verify by measuring, per
line, `lead = first_token_start − event_start`: every line should be clearly positive.

## Frame-accurate preview

`ffmpeg -ss` **before** `-i` resets timestamps, so libass sees t≈0 and the subtitle
"disappears". Use `-copyts`. `scripts/preview.sh` does.

## Lyrics timing offset

MMS_FA's token onsets sit slightly past the perceptual attack: measured p50 −24 ms,
p75 +79 ms, p90 +178 ms against vocal onsets. FA-Kara ships −150 ms as its default for
the ruby LRC. `-150` is the default here; it is a CLI argument so you can dial it
without touching code.

## Repo layout

```
scripts/
  autoruby.py      kana lines -> {漢字|かんじ} form (pykakasi)
  align.py         FA-Kara MMS_FA alignment, dumps a timed structure
  upstream_ass.py  project assembly + ASS via kvm's AssBuilder/LibassMetrics
  ruby_lrc.py      ruby LRC for NicoKaraMaker3 / RhythmicaLyrics
  asr.py           optional Whisper draft (MLX, Apple Silicon)
  burn.sh          burn ASS onto the source, 720p, libass
  preview.sh       frame grabs that respect PTS (-copyts)
setup.sh           fetch what git deliberately excludes
```

## Notes

- The upstream renderer is used as a library (`ref/kvm/backend` on `sys.path`), not
  duplicated. If you change it, send the fix upstream.
- NicoKaraMaker3 is Windows-only and its GitHub repo is a 101-byte README pointing at
  the author's site — it cannot run on macOS or be scripted. That is why the ruby LRC
  is produced here and the burning is done through libass.
- Nothing in this repo is a redistribution of any song, lyric or video.

## License

MIT — see [LICENSE](LICENSE). Covers the code in this repo only. Neither upstream
project is vendored: `setup.sh` clones
[FA-Kara](https://github.com/moriwx/FA-Kara) and
[karaoke-video-maker](https://github.com/Mihaly-Ma/karaoke-video-maker) at install
time, and each carries its own license.
