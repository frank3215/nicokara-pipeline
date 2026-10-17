"""Tiny local copy of FA-Kara's LRC time parser so build_ass has no sys.path tricks."""
import re

_TIME_RE = re.compile(r"\[(\d{2}):(\d{2}):(\d{2})\]")


def parse_time_to_hundredths(time_str: str) -> int:
    m = _TIME_RE.match(time_str)
    if not m:
        raise ValueError(f"bad time string: {time_str!r}")
    return int(m.group(1)) * 6000 + int(m.group(2)) * 100 + int(m.group(3))
