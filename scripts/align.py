#!/usr/bin/env python3
"""Forced-align romanised lyric tokens against a vocal track.

Reuses FA-Kara's normaliser + the yohane MMS_FA karaoke aligner, then dumps the
timed structure so the ASS builder can lay it out.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAKARA = ROOT / "ref" / "FA-Kara"
sys.path.insert(0, str(FAKARA))
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import librosa  # noqa: E402

import haruraw2norm as hn  # noqa: E402
from align_yohane import align_audio_with_text  # noqa: E402
from utils_audio import non_silent_recog  # noqa: E402
from utils_basic import parse_time_to_hundredths, split_long_segments  # noqa: E402

MODEL_ID = "NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn"


def build_structure(lyrics_path: Path, wrap: int) -> list[dict]:
    result: list[dict] = []
    with open(lyrics_path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                result.extend(hn.process_haruhi_line(line, "auto", 0, 1))
    if result and result[-1]["orig"] != "\n":
        result.append({"orig": "\n", "type": 0, "pron": ""})
    if wrap > 0:
        split_long_segments(result, max_length=wrap)
    return result


def main() -> int:
    lyrics_path, audio_path, out_path = (Path(a) for a in sys.argv[1:4])
    wrap = int(sys.argv[4]) if len(sys.argv) > 4 else 20
    trim = int(sys.argv[5]) if len(sys.argv) > 5 else 1

    structure = build_structure(lyrics_path, wrap)
    tokens: list[str] = []
    token_to_index: dict[int, int] = {}
    for idx, item in enumerate(structure):
        if item.get("pron"):
            token_to_index[len(tokens)] = idx
            tokens.append(item["pron"])

    audio, sr = librosa.load(str(audio_path), sr=None)
    ranges = non_silent_recog(audio, sr, 1.0, 10, 0.1) if trim else []
    if ranges:
        kept = sum(e - s for s, e in ranges)
        print(f"silence-trim: {len(ranges)} voiced segments, {kept:.1f}s kept")
    print(f"tokens={len(tokens)} audio={len(audio) / sr:.1f}s sr={sr}", flush=True)
    results = align_audio_with_text(
        audio, tokens, ranges, sr, 1, use_gpu=True, hf_model_id=MODEL_ID
    )

    ok = 0
    for i, res in enumerate(results):
        if res.get("start") in (None, "[error]"):
            continue
        structure[token_to_index[i]]["start"] = res["start"]
        structure[token_to_index[i]]["end"] = res["end"]
        ok += 1

    stamped = [
        (parse_time_to_hundredths(it["start"]), parse_time_to_hundredths(it["end"]))
        for it in structure
        if it.get("start")
    ]
    backwards = sum(1 for a, b in zip(stamped, stamped[1:]) if b[0] < a[0])
    zero = sum(1 for a, b in zip(stamped, stamped[1:]) if b[0] == a[0])
    span = (stamped[-1][1] - stamped[0][0]) / 100 if stamped else 0

    out_path.write_text(json.dumps(structure, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        f"aligned={ok}/{len(tokens)} non_monotonic={backwards} zero_gap={zero} "
        f"lyric_span={span:.1f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
