#!/usr/bin/env python3
"""Poster↔title match: max(overlap OCR↔title, OCR↔original_title, Translate(OCR)→EN↔title).

Uses existing DetectText OCR + horror_movies titles. Amazon Translate only when
max(o1, o2) is low and OCR language is not English.

Writes:
  data/qa/poster_title_match.csv
  data/qa/poster_title_match_suspects.csv

  export AWS_PROFILE=sandbox
  python3 poster_title_match.py
  python3 poster_title_match.py --translate-below 0.35 --workers 8
  python3 poster_title_match.py --no-translate   # local o1/o2 only
  # Expand Translate on non-EN rows not yet translated (keeps existing CSV):
  python3 poster_title_match.py --refill-translate --translate-below 0.55 \\
      --translate-min-chars 60 --suspect-below 0.35
"""
from __future__ import annotations

import argparse
import csv
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from ocr_metrics import title_overlap_score

DATA = Path(__file__).resolve().parent / "data"
HM = DATA / "horror_movies.csv"
OCR_ESSAY = DATA / "poster_ocr_rek_text.csv"
OCR_GAP = DATA / "poster_ocr_rek_text_alllang.csv"
COMP_ESSAY = DATA / "ocr_comprehend.csv"
COMP_GAP = DATA / "ocr_comprehend_alllang.csv"
OUT = DATA / "qa" / "poster_title_match.csv"
OUT_SUSPECTS = DATA / "qa" / "poster_title_match_suspects.csv"
REGION = "us-east-1"

FIELDS = [
    "id",
    "title",
    "original_title",
    "original_language",
    "ocr_source",
    "ocr_chars",
    "ocr_lang",
    "ocr_lang_score",
    "overlap_title",
    "overlap_original",
    "overlap_max_local",
    "translated",
    "overlap_translated",
    "overlap_max",
    "translate_error",
    "suspect",
]

_print_lock = threading.Lock()
_write_lock = threading.Lock()
_translate_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def load_meta() -> dict[int, dict]:
    out: dict[int, dict] = {}
    with HM.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(float(r["id"]))
            except Exception:
                continue
            out[pid] = {
                "title": (r.get("title") or "").strip(),
                "original_title": (r.get("original_title") or "").strip(),
                "original_language": (r.get("original_language") or "").strip(),
            }
    return out


def load_ocr(path: Path, source: str) -> dict[int, dict]:
    out: dict[int, dict] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except Exception:
                continue
            text = (r.get("full_ocr") or "").strip()
            out[pid] = {"full_ocr": text, "ocr_source": source, "ocr_chars": len(text)}
    return out


def load_lang(*paths: Path) -> dict[int, tuple[str, float]]:
    """Prefer detecttext Comprehend rows; else any source with a lang code."""
    best: dict[int, tuple[str, float, int]] = {}  # code, score, priority

    def prio(src: str) -> int:
        s = (src or "").lower()
        if s == "detecttext":
            return 3
        if s in ("easyocr", "textract", "rek_text"):
            return 2
        return 1

    for path in paths:
        if not path.exists():
            continue
        with path.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except Exception:
                    continue
                code = (r.get("lang_code") or "").strip().lower()
                if not code:
                    continue
                try:
                    score = float(r.get("lang_score") or 0)
                except Exception:
                    score = 0.0
                pr = prio(r.get("source") or "")
                cur = best.get(pid)
                if cur is None or pr > cur[2] or (pr == cur[2] and score > cur[1]):
                    best[pid] = (code, score, pr)
    return {pid: (c, s) for pid, (c, s, _) in best.items()}


def load_done(path: Path, force: bool) -> dict[int, dict]:
    if force or not path.exists():
        return {}
    out: dict[int, dict] = {}
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                out[int(r["id"])] = r
            except Exception:
                pass
    return out


def write_rows(path: Path, rows: dict[int, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            for pid in sorted(rows):
                w.writerow(rows[pid])


def _script_fallback_lang(text: str) -> str | None:
    """Best-effort source lang when Translate auto picks an unsupported pair."""
    if not text:
        return None
    cyr = sum(1 for ch in text if "\u0400" <= ch <= "\u04FF")
    cjk = sum(1 for ch in text if "\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff")
    arab = sum(1 for ch in text if "\u0600" <= ch <= "\u06FF")
    letters = sum(1 for ch in text if ch.isalpha()) or 1
    if cyr / letters >= 0.25:
        return "ru"
    if cjk / letters >= 0.25:
        # prefer Japanese if kana present else Chinese
        if any("\u3040" <= ch <= "\u30ff" for ch in text):
            return "ja"
        return "zh"
    if arab / letters >= 0.25:
        return "ar"
    return None


def translate_to_en(client, text: str, source: str | None = None) -> tuple[str, str]:
    """Return (translated_text, error). Prefer auto; fall back on script if unsupported pair."""
    del source  # Comprehend codes are often bad Translate pairs; start from auto

    def _call(src: str) -> str:
        with _translate_lock:
            resp = client.translate_text(
                Text=text[:9000],
                SourceLanguageCode=src,
                TargetLanguageCode="en",
            )
        return (resp.get("TranslatedText") or "").strip()

    try:
        return _call("auto"), ""
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "UnsupportedLanguagePairException":
            fb = _script_fallback_lang(text)
            if fb:
                try:
                    return _call(fb), ""
                except ClientError as e2:
                    return "", f"{code}:{e2}"
            # last resort: try common European sources
            for fb in ("es", "fr", "de", "pt", "it", "id"):
                try:
                    return _call(fb), ""
                except ClientError:
                    continue
        return "", f"{code}:{e}"
    except Exception as e:
        return "", str(e)[:200]


def build_row(
    pid: int,
    ocr: dict,
    meta: dict,
    lang: tuple[str, float] | None,
    *,
    translate_below: float,
    min_chars: int,
    translate_min_chars: int,
    client,
    do_translate: bool,
) -> dict:
    title = meta.get("title") or ""
    orig = meta.get("original_title") or ""
    text = ocr.get("full_ocr") or ""
    o1 = title_overlap_score(text, title) if text and title else 0.0
    o2 = title_overlap_score(text, orig) if text and orig else 0.0
    o_local = max(o1, o2)
    lang_code = (lang[0] if lang else "") or ""
    lang_score = lang[1] if lang else 0.0

    translated = ""
    o3 = 0.0
    terr = ""
    # Translate only substantial non-EN OCR with weak local match.
    need = (
        do_translate
        and bool(text)
        and len(text) >= translate_min_chars
        and o_local < translate_below
        and bool(title)
        and lang_code != "en"
    )

    if need:
        translated, terr = translate_to_en(client, text, None)
        if translated:
            o3_title = title_overlap_score(translated, title) if title else 0.0
            o3_orig = title_overlap_score(translated, orig) if orig else 0.0
            o3 = max(o3_title, o3_orig)

    o_max = max(o_local, o3)
    suspect = "1" if (text and len(text) >= min_chars and o_max < translate_below) else "0"

    return {
        "id": pid,
        "title": title,
        "original_title": orig,
        "original_language": meta.get("original_language") or "",
        "ocr_source": ocr.get("ocr_source") or "",
        "ocr_chars": ocr.get("ocr_chars") or len(text),
        "ocr_lang": lang_code,
        "ocr_lang_score": round(lang_score, 4) if lang_score else "",
        "overlap_title": o1,
        "overlap_original": o2,
        "overlap_max_local": o_local,
        "translated": 1 if translated else 0,
        "overlap_translated": o3 if translated else "",
        "overlap_max": o_max,
        "translate_error": terr,
        "suspect": suspect,
    }


def _fnum(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def refill_todo(
    existing: dict[int, dict],
    ocr_map: dict[int, dict],
    lang_map: dict[int, tuple[str, float]],
    *,
    translate_below: float,
    min_chars: int,
    translate_min_chars: int,
) -> list[int]:
    """Non-EN rows under threshold that still need (or failed) Translate."""
    del min_chars  # suspects use min_chars elsewhere; refill gates on translate_min_chars
    out: list[int] = []
    for pid, ocr in ocr_map.items():
        chars = int(ocr.get("ocr_chars") or 0)
        if chars < translate_min_chars:
            continue
        lang = ""
        if pid in lang_map:
            lang = (lang_map[pid][0] or "").lower()
        row = existing.get(pid) or {}
        if not lang:
            lang = (str(row.get("ocr_lang") or "")).lower()
        if lang == "en":
            continue
        loc = _fnum(row.get("overlap_max_local"))
        if not row:
            if not lang:
                continue
            out.append(pid)
            continue
        if loc >= translate_below:
            continue
        already = str(row.get("translated")) in ("1",) or row.get("translated") == 1
        terr = (row.get("translate_error") or "").strip()
        if already and not terr:
            continue
        if not lang:
            ol = (str(row.get("original_language") or "")).lower()
            if ol in ("en", ""):
                continue
        out.append(pid)
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", default=REGION)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--translate-below", type=float, default=0.35)
    ap.add_argument("--suspect-below", type=float, default=None, help="default=translate-below")
    ap.add_argument("--min-chars", type=int, default=4, help="min OCR chars to mark suspect")
    ap.add_argument(
        "--translate-min-chars",
        type=int,
        default=60,
        help="min OCR chars required before calling Amazon Translate",
    )
    ap.add_argument("--no-translate", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument(
        "--refill-translate",
        action="store_true",
        help="Only Translate non-EN rows under --translate-below missing/failed translation; merge into existing CSV",
    )
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids-file", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--suspects-out", type=Path, default=OUT_SUSPECTS)
    args = ap.parse_args()
    suspect_below = args.suspect_below if args.suspect_below is not None else args.translate_below

    if not HM.exists():
        raise SystemExit(f"missing {HM}")

    meta = load_meta()
    ocr_map = load_ocr(OCR_ESSAY, "detecttext_essay")
    ocr_map.update(load_ocr(OCR_GAP, "detecttext_alllang"))
    lang_map = load_lang(COMP_GAP, COMP_ESSAY)

    if args.ids_file:
        want: set[int] = set()
        with args.ids_file.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    want.add(int(line.split(",")[0]))
                except Exception:
                    pass
        ocr_map = {k: v for k, v in ocr_map.items() if k in want}

    if args.refill_translate:
        if args.force:
            raise SystemExit("--refill-translate is incompatible with --force (would wipe CSV)")
        if not args.out.exists():
            raise SystemExit(f"--refill-translate requires existing {args.out}")
        if args.no_translate:
            raise SystemExit("--refill-translate needs Translate enabled")
        existing = load_done(args.out, force=False)
        # coerce keys
        rows: dict[int, dict] = {int(k): v for k, v in existing.items()}
        todo = refill_todo(
            rows,
            ocr_map,
            lang_map,
            translate_below=args.translate_below,
            min_chars=args.min_chars,
            translate_min_chars=args.translate_min_chars,
        )
        if args.limit:
            todo = todo[: args.limit]
        log(
            f"refill n_todo={len(todo)} base={len(rows)} below={args.translate_below} "
            f"translate_min_chars={args.translate_min_chars} "
            f"suspect_below={suspect_below} workers={args.workers}"
        )
    else:
        done = load_done(args.out, args.force)
        todo = [pid for pid in sorted(ocr_map) if pid not in done]
        if args.limit:
            todo = todo[: args.limit]
        rows = dict(done)
        log(
            f"start n_ocr={len(ocr_map)} n_todo={len(todo)} done={len(done)} "
            f"translate={'off' if args.no_translate else 'on'} "
            f"below={args.translate_below} translate_min_chars={args.translate_min_chars} "
            f"workers={args.workers}"
        )

    client = None
    if not args.no_translate:
        client = boto3.client(
            "translate",
            region_name=args.region,
            config=Config(retries={"max_attempts": 8, "mode": "adaptive"}),
        )

    t0 = time.time()
    ok_t = 0
    err_t = 0
    completed = 0

    def work(pid: int) -> dict:
        return build_row(
            pid,
            ocr_map[pid],
            meta.get(pid, {}),
            lang_map.get(pid),
            translate_below=args.translate_below,
            min_chars=args.min_chars,
            translate_min_chars=args.translate_min_chars,
            client=client,
            do_translate=not args.no_translate,
        )

    if not todo:
        log("nothing to do")
    else:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            futs = {ex.submit(work, pid): pid for pid in todo}
            for fut in as_completed(futs):
                pid = futs[fut]
                try:
                    row = fut.result()
                except Exception as e:
                    row = {
                        "id": pid,
                        "title": meta.get(pid, {}).get("title", ""),
                        "original_title": meta.get(pid, {}).get("original_title", ""),
                        "original_language": meta.get(pid, {}).get("original_language", ""),
                        "ocr_source": ocr_map[pid].get("ocr_source", ""),
                        "ocr_chars": ocr_map[pid].get("ocr_chars", 0),
                        "ocr_lang": "",
                        "ocr_lang_score": "",
                        "overlap_title": 0,
                        "overlap_original": 0,
                        "overlap_max_local": 0,
                        "translated": 0,
                        "overlap_translated": "",
                        "overlap_max": 0,
                        "translate_error": str(e)[:200],
                        "suspect": "1",
                    }
                if row.get("translated") in (1, "1"):
                    ok_t += 1
                if row.get("translate_error"):
                    err_t += 1
                rows[pid] = row
                completed += 1
                if completed % 100 == 0 or completed == len(todo):
                    # refresh suspects flags for written rows only; full pass below
                    write_rows(args.out, rows)
                    rate = completed / max(1e-6, time.time() - t0)
                    log(
                        f"[{completed}/{len(todo)}] translated≈{ok_t} terr={err_t} "
                        f"rate={rate:.1f}/s id={pid} max={row.get('overlap_max')}"
                    )

    # recompute suspect flag for full table
    for pid, row in rows.items():
        o_max = _fnum(row.get("overlap_max"))
        try:
            chars = int(float(row.get("ocr_chars") or 0))
        except Exception:
            chars = 0
        row["suspect"] = "1" if chars >= args.min_chars and o_max < suspect_below else "0"

    write_rows(args.out, rows)
    suspects = {pid: r for pid, r in rows.items() if str(r.get("suspect")) == "1"}
    write_rows(args.suspects_out, suspects)

    n_trans = sum(1 for r in rows.values() if str(r.get("translated")) in ("1", "1"))
    improved = 0
    if args.refill_translate:
        # count where translate beat local among this run — approximate via o3>loc
        for pid in todo:
            r = rows.get(pid) or {}
            if str(r.get("translated")) != "1":
                continue
            if _fnum(r.get("overlap_translated")) > _fnum(r.get("overlap_max_local")):
                improved += 1
    log(
        f"LISTO n={len(rows)} suspects={len(suspects)} translated={n_trans} "
        f"terr={err_t} elapsed={(time.time()-t0)/60:.1f}m → {args.out}"
        + (f" refill_improved={improved}" if args.refill_translate else "")
    )
    log(f"suspects → {args.suspects_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
