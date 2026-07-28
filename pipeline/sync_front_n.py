#!/usr/bin/env python3
"""Keep front-end copy / README corpus n in sync with posters.csv.

Canonical n = len(data/posters.csv). Copy lives in site/index.html,
site/i18n/*, and README.md as US-formatted thousands (e.g. 37,888) and
sometimes bare (n=37888).

  python3 sync_front_n.py              # check; exit 1 if mismatch
  python3 sync_front_n.py --fix       # replace stale corpus n → current
  python3 sync_front_n.py --fix --dry-run

Called from validate_corpus.py (--fix-front) and apply_exclusions.py.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = HERE / "data"
SITE = ROOT / "site"

# Prose / meta that mentions the published corpus size.
FRONT_COPY_FILES = [
    ROOT / "README.md",
    SITE / "index.html",
    SITE / "i18n" / "es-content.json",
    SITE / "i18n" / "content.js",
    SITE / "i18n" / "ui.json",
    SITE / "i18n" / "ui.js",
]

# Generated data headers (n without commas).
FRONT_DATA_HEADERS = [
    SITE / "data" / "explorer.js",
    SITE / "data" / "lookup.js",
    SITE / "data" / "series.js",
]

# Band for "published corpus n" (excludes ~72,000 TMDB raw and small exclusion counts).
CORPUS_N_MIN = 20_000
CORPUS_N_MAX = 60_000
PROTECTED = frozenset({72_000})  # full TMDB horror mention

# 37,888 or 37888 — not preceded by ~ (approx) or digit.
FMT_RE = re.compile(r"(?<![~\d])(\d{1,3}),(\d{3})(?!\d)")
BARE_RE_TMPL = r"(?<![~\d]){n}(?!\d)"


def corpus_n() -> int:
    path = DATA / "posters.csv"
    if not path.exists():
        raise SystemExit(f"falta {path}")
    # cheap: count data rows
    with path.open(encoding="utf-8", errors="replace") as f:
        n = sum(1 for _ in f) - 1
    if n <= 0:
        raise SystemExit(f"{path} vacio")
    return n


def fmt(n: int) -> str:
    return f"{n:,}"


def _iter_fmt_ns(text: str) -> list[int]:
    out: list[int] = []
    for m in FMT_RE.finditer(text):
        v = int(m.group(1) + m.group(2))
        if CORPUS_N_MIN <= v <= CORPUS_N_MAX and v not in PROTECTED:
            out.append(v)
    return out


def detect_stale_n(canonical: int, files: list[Path] | None = None) -> int | None:
    """Most common corpus-sized formatted n in copy that is not canonical, else None."""
    files = files or FRONT_COPY_FILES
    counts: Counter[int] = Counter()
    for path in files:
        if not path.exists():
            continue
        counts.update(_iter_fmt_ns(path.read_text(encoding="utf-8", errors="replace")))
    # Drop canonical; leftover mode is the stale published n.
    counts.pop(canonical, None)
    if not counts:
        return None
    stale, _ = counts.most_common(1)[0]
    return stale


def check_front_n(canonical: int | None = None) -> list[str]:
    """Return human-readable mismatch messages (empty = ok)."""
    n = canonical if canonical is not None else corpus_n()
    want = fmt(n)
    issues: list[str] = []

    for path in FRONT_COPY_FILES:
        if not path.exists():
            issues.append(f"falta {path.relative_to(ROOT)}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found = _iter_fmt_ns(text)
        if not found:
            issues.append(
                f"{path.relative_to(ROOT)}: no aparece n formateado "
                f"en banda corpus ({want})"
            )
            continue
        other = sorted({v for v in found if v != n})
        if other:
            issues.append(
                f"{path.relative_to(ROOT)}: n stale {', '.join(fmt(v) for v in other)} "
                f"(esperado {want}; hits canónicos={found.count(n)})"
            )
        elif found.count(n) == 0:
            issues.append(f"{path.relative_to(ROOT)}: falta {want}")

    # series.js AOF_META / header
    series = SITE / "data" / "series.js"
    if series.exists():
        head = "\n".join(series.read_text(encoding="utf-8").splitlines()[:8])
        m = re.search(r"AOF_META=\{n:(\d+)", head) or re.search(
            r"n=([\d,]+)\s+posters", head
        )
        if m:
            sn = int(m.group(1).replace(",", ""))
            if sn != n:
                issues.append(f"site/data/series.js: n={sn:,} != {n:,}")
        else:
            issues.append("site/data/series.js: no pude parsear n")

    explorer = SITE / "data" / "explorer.js"
    if explorer.exists():
        first = explorer.read_text(encoding="utf-8", errors="replace").splitlines()[0]
        m = re.search(r"n=(\d+)", first)
        if m and int(m.group(1)) != n:
            issues.append(f"site/data/explorer.js: n={int(m.group(1)):,} != {n:,}")

    lookup = SITE / "data" / "lookup.js"
    if lookup.exists():
        first = lookup.read_text(encoding="utf-8", errors="replace").splitlines()[0]
        m = re.search(r"n=(\d+)", first)
        if m and int(m.group(1)) != n:
            issues.append(f"site/data/lookup.js: n={int(m.group(1)):,} != {n:,}")

    return issues


def _replace_n(text: str, old: int, new: int) -> tuple[str, int]:
    """Replace formatted and bare old n with new. Returns (text, n_subs)."""
    if old == new:
        return text, 0
    old_fmt, new_fmt = fmt(old), fmt(new)
    n_subs = 0
    if old_fmt in text:
        c = text.count(old_fmt)
        text = text.replace(old_fmt, new_fmt)
        n_subs += c
    # bare: only when not part of a larger number / already comma form
    bare = re.compile(BARE_RE_TMPL.format(n=old))
    text, c = bare.subn(str(new), text)
    n_subs += c
    return text, n_subs


def sync_front_n(
    canonical: int | None = None,
    *,
    dry_run: bool = False,
    from_n: int | None = None,
) -> dict:
    """Replace stale corpus n in front copy. Does not regenerate series/lookup/explorer."""
    n = canonical if canonical is not None else corpus_n()
    stale = from_n if from_n is not None else detect_stale_n(n)
    report = {
        "canonical": n,
        "stale": stale,
        "files": {},
        "changed": False,
    }
    if stale is None:
        # Still ensure canonical appears; if check is clean, nothing to do.
        issues = check_front_n(n)
        report["issues_remaining"] = issues
        return report

    for path in FRONT_COPY_FILES:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        new_text, n_subs = _replace_n(text, stale, n)
        if n_subs:
            report["files"][str(path.relative_to(ROOT))] = n_subs
            report["changed"] = True
            if not dry_run:
                path.write_text(new_text, encoding="utf-8")

    report["issues_remaining"] = check_front_n(n) if not dry_run else []
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fix", action="store_true", help="escribir reemplazos")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from-n", type=int, default=None, help="forzar n viejo a reemplazar")
    ap.add_argument("--n", type=int, default=None, help="forzar n canonico (default: posters.csv)")
    args = ap.parse_args()
    n = args.n if args.n is not None else corpus_n()
    print(f"corpus n={n:,}")

    if args.fix or args.dry_run:
        rep = sync_front_n(n, dry_run=args.dry_run, from_n=args.from_n)
        if rep["stale"] is None and not rep.get("changed"):
            issues = check_front_n(n)
            if issues:
                print("no hay n stale unico que reemplazar; mismatches:")
                for i in issues:
                    print(f"  - {i}")
                return 1
            print("front ya alineado")
            return 0
        mode = "dry-run" if args.dry_run else "fix"
        print(f"{mode}: {fmt(rep['stale'])} → {fmt(n)}")
        for f, c in rep["files"].items():
            print(f"  {f}: {c} reemplazos")
        if args.dry_run:
            return 0
        left = rep.get("issues_remaining") or []
        if left:
            print("quedan mismatches:")
            for i in left:
                print(f"  - {i}")
            return 1
        print("LISTO.")
        return 0

    issues = check_front_n(n)
    if issues:
        print("front n MISMATCH:")
        for i in issues:
            print(f"  - {i}")
        print("corre: python3 sync_front_n.py --fix")
        return 1
    print("front n OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
