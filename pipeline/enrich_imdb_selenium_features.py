#!/usr/bin/env python3
"""Resolve remaining feature IMDb ids via headed Chrome Selenium.

Reads leftovers from data/imdb_suggest_features_miss.csv (or --ids-file).
For each title+year: IMDb suggest candidates → open title pages → accept when
TMDB director overlaps page directors (year exact preferred, ±1 allowed).

Resume: skips ids already present in hits/miss output CSVs (unless --force).
Merges accepted tt into data/imdb_ids.csv.

Usage:
  export NO_PROXY='*'
  TMDB_API_KEY=... python3 enrich_imdb_selenium_features.py
  python3 enrich_imdb_selenium_features.py --limit 10
  python3 enrich_imdb_selenium_features.py --force   # redo prior misses
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import random
import time
import urllib.parse
from pathlib import Path

import requests

from enrich_imdb_ids import DATA, SIDECAR, load_sidecar, write_sidecar
from match_imdb_title_basics_features import valid_tt
from resolve_imdb_ambiguous_selenium import (
    director_overlap,
    fetch_tmdb,
    normalize_title,
)

SUGGEST_MISS = DATA / "imdb_suggest_features_miss.csv"
BASICS_MISS = DATA / "imdb_basics_match_features_miss.csv"
AMBIG_MISS = DATA / "imdb_basics_ambiguous_selenium_miss.csv"
HITS_OUT = DATA / "imdb_selenium_features_hits.csv"
MISS_OUT = DATA / "imdb_selenium_features_miss.csv"

CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
API_HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.imdb.com",
    "Referer": "https://www.imdb.com/",
}

PREFERRED_QID = frozenset({"movie", "tvMovie"})
PREFERRED_Q = frozenset({"feature", "TV movie"})
DEPRIORITIZED_QID = frozenset(
    {"short", "tvEpisode", "tvSeries", "videoGame", "podcastSeries", "musicVideo"}
)

HIT_FIELDS = [
    "id",
    "imdb_id",
    "title",
    "year",
    "director",
    "imdb_directors",
    "match",
    "imdb_year",
]
MISS_FIELDS = ["id", "title", "year", "director", "reason", "candidates"]


def build_driver(*, headless: bool = False):
    os.environ.setdefault("NO_PROXY", "*")
    os.environ.setdefault("no_proxy", "*")

    import tempfile

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    opts = Options()
    if platform.system() == "Darwin":
        chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if Path(chrome).exists():
            opts.binary_location = chrome
    else:
        for chrome in (
            os.environ.get("CHROME_BIN") or "",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/google-chrome",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
        ):
            if chrome and Path(chrome).exists():
                opts.binary_location = chrome
                break
    if headless:
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1920,1080")
    else:
        opts.add_argument("--window-size=1280,900")
        opts.add_argument("--start-maximized")
    # Isolated profile avoids hanging when personal Chrome is already open.
    profile = tempfile.mkdtemp(prefix="aof-imdb-chrome-")
    opts.add_argument(f"--user-data-dir={profile}")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--lang=en-US")
    opts.add_argument(f"--user-agent={CHROME_UA}")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    print(f"  Chrome profile={profile}", flush=True)
    print("  Installing/locating chromedriver…", flush=True)
    service = Service(ChromeDriverManager().install())
    print("  Launching Chrome…", flush=True)
    driver = webdriver.Chrome(service=service, options=opts)
    print("  Chrome ready", flush=True)
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": (
                    "Object.defineProperty(navigator, 'webdriver', "
                    "{get: () => undefined});"
                )
            },
        )
    except Exception:
        pass
    driver.set_page_load_timeout(45)
    return driver


def suggest_by_title(session: requests.Session, title: str) -> list[dict]:
    key = title.strip().lower()
    if not key:
        return []
    first = key[0] if key[0].isalnum() else "0"
    url = (
        f"https://v2.sg.media-imdb.com/suggestion/"
        f"{first}/{urllib.parse.quote(key)}.json"
    )
    r = session.get(url, headers=API_HEADERS, timeout=30)
    if r.status_code != 200:
        return []
    out = []
    for x in r.json().get("d") or []:
        tt = str(x.get("id") or "")
        if not tt.startswith("tt"):
            continue
        try:
            y = int(x["y"]) if x.get("y") is not None else None
        except (TypeError, ValueError):
            y = None
        out.append(
            {
                "imdb_id": tt,
                "title": str(x.get("l") or ""),
                "year": y,
                "qid": (x.get("qid") or "").strip(),
                "q": (x.get("q") or "").strip(),
            }
        )
    return out


def titles_equal(a: str, b: str) -> bool:
    return normalize_title(a) == normalize_title(b) and bool(normalize_title(a))


def pick_candidates(
    title: str, year: int | None, suggestions: list[dict], max_n: int = 5
) -> list[dict]:
    exact_title = [c for c in suggestions if titles_equal(c["title"], title)]
    if not exact_title:
        # soft: casefold raw
        exact_title = [
            c
            for c in suggestions
            if (c["title"] or "").casefold().strip() == title.casefold().strip()
        ]
    pool = exact_title or list(suggestions)

    # Prefer movies; drop clearly wrong types when alternatives exist
    movies = [
        c
        for c in pool
        if c.get("qid") in PREFERRED_QID or c.get("q") in PREFERRED_Q
    ]
    if movies:
        pool = movies
    else:
        pool = [
            c
            for c in pool
            if c.get("qid") not in DEPRIORITIZED_QID
        ] or pool

    def rank(c: dict) -> tuple:
        y = c.get("year")
        if year and y is not None:
            yd = abs(y - year)
        else:
            yd = 9
        pref = 0 if (c.get("qid") in PREFERRED_QID or c.get("q") in PREFERRED_Q) else 1
        return (yd, pref)

    pool = sorted(pool, key=rank)
    # keep year within ±1 when year known
    if year:
        near = [c for c in pool if c.get("year") is not None and abs(c["year"] - year) <= 1]
        if near:
            pool = near
    # dedupe
    seen: set[str] = set()
    out: list[dict] = []
    for c in pool:
        if c["imdb_id"] in seen:
            continue
        seen.add(c["imdb_id"])
        out.append(c)
        if len(out) >= max_n:
            break
    return out


def extract_page_meta(driver) -> dict:
    return driver.execute_script(
        """
        const title = (document.querySelector('meta[property="og:title"]') || {}).content
          || document.title || '';
        let year = null;
        const ym = title.match(/\\((\\d{4})\\)/);
        if (ym) year = parseInt(ym[1], 10);
        const directors = [];
        for (const a of document.querySelectorAll(
          '[data-testid="title-pc-principal-credit"] a, a[href*="/name/nm"]'
        )) {
          const block = a.closest('[data-testid="title-pc-principal-credit"], li, div');
          const label = (block && block.innerText) ? block.innerText.slice(0, 120) : '';
          if (/director/i.test(label) || /directed by/i.test(label)) {
            const name = (a.textContent || '').trim();
            if (name && !directors.includes(name) && name.toLowerCase() !== 'director') {
              directors.push(name);
            }
          }
        }
        for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
          try {
            const j = JSON.parse(s.textContent);
            const d = j.director;
            if (!d) continue;
            for (const x of (Array.isArray(d) ? d : [d])) {
              const name = (x && (x.name || x)) + '';
              if (name && !directors.includes(name)) directors.push(name);
            }
          } catch (e) {}
        }
        const blocked = /^Just a moment|^Attention Required|captcha/i.test(document.title)
          || !!document.querySelector('#challenge-form, .g-recaptcha');
        return {
          title, year, directors, blocked,
          statusTitle: document.title,
        };
        """
    )


def load_done_ids(force: bool) -> set[int]:
    done: set[int] = set()
    if force:
        return done
    for path in (HITS_OUT, MISS_OUT):
        if not path.exists():
            continue
        with path.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    done.add(int(r["id"]))
                except (KeyError, TypeError, ValueError):
                    continue
    return done


def load_prior_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def load_todo_from_csvs() -> list[dict]:
    """Prefer suggest miss; fall back to basics miss + ambig miss."""
    rows: list[dict] = []
    seen: set[int] = set()

    def add(path: Path) -> None:
        if not path.exists():
            return
        with path.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                if pid in seen:
                    continue
                seen.add(pid)
                year = None
                ys = (r.get("year") or "").strip()
                if ys.isdigit():
                    year = int(ys)
                rows.append(
                    {
                        "id": pid,
                        "title": (r.get("title") or "").strip(),
                        "original_title": (r.get("original_title") or "").strip(),
                        "year": year,
                    }
                )

    if SUGGEST_MISS.exists():
        add(SUGGEST_MISS)
    else:
        add(BASICS_MISS)
        add(AMBIG_MISS)
    return rows


def load_ids_file(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "," in line and not line[0].isdigit():
            # maybe csv header
            continue
        part = line.split(",")[0].strip()
        if part.isdigit():
            rows.append({"id": int(part), "title": "", "original_title": "", "year": None})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=os.environ.get("TMDB_API_KEY"))
    ap.add_argument("--ids-file", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=1.4)
    ap.add_argument("--jitter", type=float, default=0.6)
    ap.add_argument("--pause", type=float, default=1.1, help="wait after page load")
    ap.add_argument("--max-candidates", type=int, default=5)
    ap.add_argument("--headless", action="store_true", help="NOT recommended (IMDb blocks)")
    ap.add_argument("--force", action="store_true", help="reprocess ids already in out CSVs")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-merge", action="store_true")
    args = ap.parse_args()

    if not args.api_key:
        raise SystemExit("Need TMDB_API_KEY or --api-key")

    os.environ.setdefault("NO_PROXY", "*")
    os.environ.setdefault("no_proxy", "*")

    mapping = load_sidecar()
    done = load_done_ids(args.force)

    if args.ids_file:
        todo = load_ids_file(Path(args.ids_file))
    else:
        todo = load_todo_from_csvs()

    # filter: still no tt, not already processed
    filtered: list[dict] = []
    skipped_tt = skipped_done = 0
    for r in todo:
        pid = r["id"]
        if valid_tt(mapping.get(pid, "")):
            skipped_tt += 1
            continue
        if pid in done:
            skipped_done += 1
            continue
        filtered.append(r)

    if args.limit:
        filtered = filtered[: args.limit]

    print(
        f"todo={len(filtered)} skip_has_tt={skipped_tt} "
        f"skip_resume={skipped_done} headless={args.headless}",
        flush=True,
    )
    if not filtered:
        print("nothing to do")
        return

    hits = load_prior_rows(HITS_OUT) if not args.force else []
    misses = load_prior_rows(MISS_OUT) if not args.force else []
    # if force, start clean for ids we will redo — keep others
    if args.force:
        redo = {r["id"] for r in filtered}
        hits = [h for h in load_prior_rows(HITS_OUT) if int(h["id"]) not in redo]
        misses = [m for m in load_prior_rows(MISS_OUT) if int(m["id"]) not in redo]

    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": "what-fear-looks-like/selenium-features"})

    driver = None
    try:
        print("Starting headed Chrome…", flush=True)
        driver = build_driver(headless=args.headless)
    except Exception as e:
        raise SystemExit(f"Chrome/Selenium failed: {e}") from e

    n = len(filtered)
    try:
        for i, row in enumerate(filtered, 1):
            pid = row["id"]
            # re-check sidecar (resume / parallel)
            if valid_tt(mapping.get(pid, "")):
                print(f"  {i}/{n} SKIP {pid} already has tt", flush=True)
                continue

            tmdb = fetch_tmdb(session, args.api_key, pid)
            title = (
                row.get("title")
                or tmdb.get("title")
                or ""
            ).strip()
            ot = (row.get("original_title") or "").strip()
            year = row.get("year") or tmdb.get("year")
            dirs = tmdb.get("directors") or []
            base = {
                "id": pid,
                "title": title,
                "year": year or "",
                "director": "; ".join(dirs),
            }

            if not title:
                misses.append({**base, "reason": "no_title", "candidates": ""})
                print(f"  {i}/{n} MISS {pid} no_title", flush=True)
                continue
            if not year:
                misses.append({**base, "reason": "no_year", "candidates": ""})
                print(f"  {i}/{n} MISS {pid} no_year", flush=True)
                continue
            if not dirs:
                misses.append({**base, "reason": "no_tmdb_director", "candidates": ""})
                print(f"  {i}/{n} MISS {pid} {title!r} no_tmdb_director", flush=True)
                continue

            suggestions: list[dict] = []
            seen_tt: set[str] = set()
            for q in (title, ot):
                if not q:
                    continue
                for c in suggest_by_title(session, q):
                    if c["imdb_id"] in seen_tt:
                        continue
                    seen_tt.add(c["imdb_id"])
                    suggestions.append(c)
                time.sleep(0.12)

            cands = pick_candidates(
                title, int(year), suggestions, max_n=args.max_candidates
            )
            if not cands and ot and ot.casefold() != title.casefold():
                cands = pick_candidates(
                    ot, int(year), suggestions, max_n=args.max_candidates
                )
            if not cands:
                misses.append(
                    {**base, "reason": "no_suggest_candidates", "candidates": ""}
                )
                print(f"  {i}/{n} MISS {pid} {title!r} no_suggest", flush=True)
                time.sleep(args.delay)
                continue

            accepted = None
            last_reason = "no_director_match"
            tried: list[str] = []

            for c in cands:
                tt = c["imdb_id"]
                tried.append(f"{tt}:{c.get('year')}")
                url = f"https://www.imdb.com/title/{tt}/"
                try:
                    driver.get(url)
                    time.sleep(args.pause)
                    info = extract_page_meta(driver) or {}
                except Exception as e:
                    last_reason = f"nav_err {type(e).__name__}"
                    continue

                status = (info.get("statusTitle") or "")[:80]
                if info.get("blocked") or "Just a moment" in status:
                    last_reason = f"blocked title={status!r}"
                    time.sleep(2.5)
                    info = extract_page_meta(driver) or {}
                    if info.get("blocked") or "Just a moment" in (
                        info.get("statusTitle") or ""
                    ):
                        continue

                page_year = info.get("year")
                page_dirs = info.get("directors") or []
                if page_year and abs(int(page_year) - int(year)) > 1:
                    last_reason = f"year_mismatch page={page_year}"
                    continue
                if not page_dirs:
                    last_reason = "no_directors_on_page"
                    continue
                if director_overlap(dirs, page_dirs) >= 1:
                    accepted = {
                        **base,
                        "imdb_id": tt,
                        "imdb_directors": "; ".join(page_dirs),
                        "imdb_year": page_year or c.get("year") or "",
                        "match": "year_director",
                    }
                    break
                last_reason = (
                    f"director_mismatch page={';'.join(page_dirs)[:60]}"
                )
                time.sleep(0.4)

            if accepted:
                hits.append(accepted)
                mapping[pid] = accepted["imdb_id"]
                print(
                    f"  {i}/{n} OK {pid} {accepted['imdb_id']} {title!r} "
                    f"← {accepted['imdb_directors'][:50]}",
                    flush=True,
                )
            else:
                misses.append(
                    {
                        **base,
                        "reason": last_reason,
                        "candidates": "|".join(tried),
                    }
                )
                print(
                    f"  {i}/{n} MISS {pid} {title!r} ({year}) {last_reason}",
                    flush=True,
                )

            if i % 5 == 0:
                write_csv(HITS_OUT, hits, HIT_FIELDS)
                write_csv(MISS_OUT, misses, MISS_FIELDS)
                if not args.dry_run and not args.no_merge:
                    write_sidecar(mapping)

            time.sleep(args.delay + random.uniform(0, args.jitter))
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

    write_csv(HITS_OUT, hits, HIT_FIELDS)
    write_csv(MISS_OUT, misses, MISS_FIELDS)
    if not args.dry_run and not args.no_merge:
        write_sidecar(mapping)

    reasons: dict[str, int] = {}
    for m in misses:
        key = str(m.get("reason") or "").split(" page=")[0].split(" title=")[0]
        reasons[key] = reasons.get(key, 0) + 1

    new_hits = sum(1 for h in hits if int(h["id"]) in {r["id"] for r in filtered})
    print(
        f"\n=== SELENIUM FEATURES ===\n"
        f"session_todo={n} hits_total={len(hits)} miss_total={len(misses)}\n"
        f"reasons={json.dumps(reasons, ensure_ascii=False)}\n"
        f"→ {HITS_OUT.name} / {MISS_OUT.name}"
    )
    _ = new_hits  # silence if unused; counts in files


if __name__ == "__main__":
    main()
