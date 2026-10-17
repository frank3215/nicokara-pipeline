#!/usr/bin/env python3
"""Plain Japanese lyric lines -> FA-Kara "haruhi" ruby format.

`漢字` becomes `{漢字|かんじ}`; kana / latin / punctuation pass through untouched.
Reads stdin, writes stdout, so the intermediate files stay easy to diff.
"""
import sys

import pykakasi

KKS = pykakasi.kakasi()
ITERATION_MARK = "\u3005"  # 々


def has_kanji(text: str) -> bool:
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf" or ch == ITERATION_MARK:
            return True
    return False


def convert(line: str) -> str:
    parts = []
    for item in KKS.convert(line):
        orig = item.get("orig", "")
        if not orig:
            continue
        if has_kanji(orig):
            ruby = item.get("hira") or item.get("kana") or orig
            parts.append("{%s|%s}" % (orig, ruby))
        else:
            parts.append(orig)
    return "".join(parts)


def main() -> int:
    for raw in sys.stdin:
        line = raw.rstrip("\n")
        if not line.strip():
            print()
            continue
        print(convert(line))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
