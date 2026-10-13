#!/usr/bin/env python3
"""Title letter size by original language, from paddleocr_world_titles.py.

For each poster, a text line belongs to the title when most of it matches the
TMDB title: native-script characters against original_title (Japanese,
Chinese, Korean, Thai), or Latin words (fuzzy, ratio >= 0.8) against title and
original_title. A poster has a title when its matched lines cover at least half
of the title. When both a native-script and a Latin title are found, the larger
one counts.

Letter size = the short side of the title's largest line, as a share of the
poster's height (the short side, so vertical CJK titles measure glyph size, not
the length of the word). Posters 2000–2026; medians with a bootstrap 95%
interval.

Hand check (2026-10-13, 40 posters, 8 per language): the measured line was the
title's largest in 37.

  python3 world_title_size.py
"""

from __future__ import annotations

import csv
import difflib
import json
import random
import re
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
LINES = DATA / "qa" / "paddleocr_world" / "lines.jsonl"
RECENT = (2000, 2026)
MIN_SCORE = 0.5
NATIVE = re.compile(r"[぀-ヿ㐀-鿿가-힯฀-๿]")


def native(s: str) -> set[str]:
    return {c for c in s if NATIVE.match(c)}


def words(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) >= 2]


def near(w: str, pool) -> bool:
    return any(w == x or difflib.SequenceMatcher(None, w, x).ratio() >= 0.8 for x in pool)


def letter_size(line: dict, w: int, h: int) -> float:
    return min(line["box"][2] * w, line["box"][3] * h) / h


def title_lines(rec: dict, title: str, original: str) -> list[dict]:
    """The poster's title lines (native or Latin, whichever is larger), or []."""
    want_n = native(original)
    want_w = set(words(title)) | set(words(original))
    nat, lat, got_n, got_w = [], [], set(), set()
    for line in rec["lines"]:
        if line["score"] < MIN_SCORE:
            continue
        chars = native(line["text"])
        if want_n and chars and len(chars & want_n) / len(chars) >= 0.5:
            nat.append(line)
            got_n |= chars & want_n
        ws = words(line["text"])
        if want_w and ws and sum(near(x, want_w) for x in ws) / len(ws) >= 0.6:
            lat.append(line)
            got_w |= {x for x in want_w if near(x, ws)}
    found = []
    if want_n and len(got_n) / len(want_n) >= 0.5:
        found.append(nat)
    if want_w and len(got_w) / len(want_w) >= 0.5:
        found.append(lat)
    size = lambda ls: max(letter_size(x, rec["w"], rec["h"]) for x in ls)  # noqa: E731
    return max(found, key=size) if found else []


def median_ci(xs: list[float], n: int = 2000) -> tuple[float, float, float]:
    rnd = random.Random(1)
    boot = sorted(statistics.median(rnd.choices(xs, k=len(xs))) for _ in range(n))
    return statistics.median(xs), boot[int(0.025 * n)], boot[int(0.975 * n) - 1]


def main() -> None:
    movies = {}
    with (DATA / "horror_movies.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            movies[int(r["id"])] = r
    years = {}
    with (DATA / "faces_v2.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["year"]:
                years[int(r["id"])] = int(float(r["year"]))
    by_lang: dict[str, list[float]] = {}
    total: dict[str, int] = {}
    for raw in LINES.open(encoding="utf-8"):
        rec = json.loads(raw)
        m = movies.get(rec["id"])
        if rec["status"] != "ok" or not m:
            continue
        year = years.get(rec["id"]) or int((m.get("release_date") or "0")[:4] or 0)
        if not RECENT[0] <= year <= RECENT[1]:
            continue
        total[rec["lang"]] = total.get(rec["lang"], 0) + 1
        lines = title_lines(rec, m["title"], m["original_title"])
        if lines:
            size = max(letter_size(x, rec["w"], rec["h"]) for x in lines)
            by_lang.setdefault(rec["lang"], []).append(size)
    print(f"title letter size, {RECENT[0]}–{RECENT[1]} (share of poster height, median, 95% CI)")
    for lang in ("en", "ja", "zh", "ko", "th"):
        xs = by_lang.get(lang, [])
        if xs:
            med, lo, hi = median_ci(xs)
            print(
                f"  {lang}  {len(xs):4d}/{total[lang]:4d} with a title  "
                f"{100 * med:4.1f}% ({100 * lo:.1f}–{100 * hi:.1f})"
            )


if __name__ == "__main__":
    main()
