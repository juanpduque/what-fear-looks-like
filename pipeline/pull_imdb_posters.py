#!/usr/bin/env python3
"""Recover posters from live IMDb assets when OMDb/Amazon CDN hashes are stale.

Why this exists
---------------
OMDb often returns a ``Poster`` URL on ``m.media-amazon.com`` that 404s.
The same title still has art on IMDb — under a *different* Amazon media hash.
Direct ``requests`` / headless Chromium to ``imdb.com/title/tt…/`` often get
HTTP 202 (bot interstitial). Two recovery paths, both with desktop-Chrome
request headers:

  1. **Suggestion API (default)** — the same endpoint IMDb's search box uses
     (``v2.sg.media-imdb.com/suggestion/t/{tt}.json``). Returns ``imageUrl``
     with a fresh hash. No page render; polite and fast.

  2. **Playwright Chromium (``--browser``)** — Python's Puppeteer equivalent.
     Full page load with viewport / locale / Sec-CH-UA. Use when the
     suggestion API has no image, or for debugging with ``--headed``.

Methodology place
-----------------
EN no-TMDB-poster gap, after:

  1. enrich_imdb_ids.py / enrich_imdb_wikidata.py
  2. probe_omdb_posters.py
  3. pull_omdb_posters.py  → 404s → gap_en_omdb_amazon_dead.csv

This script is the next pass. Local JPGs feed ``analyze_color_ids.py``.

Setup
-----
  pip3 install requests
  # only if you use --browser:
  pip3 install playwright && playwright install chromium

Usage
-----
  python3 pull_imdb_posters.py --min-votes 2 --limit 25
  python3 pull_imdb_posters.py                              # all amazon-dead
  python3 pull_imdb_posters.py --include-omdb-miss
  python3 pull_imdb_posters.py --browser --headed --limit 5 # Puppeteer-style
  python3 pull_imdb_posters.py --download-only

Outputs
-------
  data/imdb_poster_hits.csv   id,imdb_id,title,year,imdb_poster,source
  data/imdb_poster_miss.csv   id,imdb_id,title,year,reason
  data/imdb_poster_ids.csv    id,title,year
  data/posters/{id}.jpg
"""
from __future__ import annotations

import argparse
import csv
import random
import re
import time
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent / "data"
POSTER_DIR = DATA / "posters"
DEAD = DATA / "gap_en_omdb_amazon_dead.csv"
OMDB_MISS = DATA / "gap_en_no_poster_omdb_miss.csv"
GAP = DATA / "gap_en_remaining_no_poster.csv"
HITS = DATA / "imdb_poster_hits.csv"
MISS = DATA / "imdb_poster_miss.csv"
IDS_OUT = DATA / "imdb_poster_ids.csv"
SIDECAR = DATA / "imdb_ids.csv"

SUGGEST_TMPL = "https://v2.sg.media-imdb.com/suggestion/t/{tt}.json"

# Desktop Chrome — same class of headers a normal visitor sends.
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
    "Sec-CH-UA": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
}
BROWSER_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Upgrade-Insecure-Requests": "1",
    "Sec-CH-UA": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}
IMAGE_HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.imdb.com/",
    "Sec-Fetch-Dest": "image",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "cross-site",
}

HIT_FIELDS = ["id", "imdb_id", "title", "year", "imdb_poster", "source"]
MISS_FIELDS = ["id", "imdb_id", "title", "year", "reason"]
IDS_FIELDS = ["id", "title", "year"]


def has_local(pid: int) -> bool:
    p = POSTER_DIR / f"{pid}.jpg"
    return p.exists() and p.stat().st_size > 2000


def load_csv_map(path: Path, key: str = "id") -> dict[int, dict]:
    out: dict[int, dict] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                out[int(r[key])] = r
            except (KeyError, TypeError, ValueError):
                continue
    return out


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def load_imdb_sidecar() -> dict[int, str]:
    out: dict[int, str] = {}
    if not SIDECAR.exists():
        return out
    with SIDECAR.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            tt = (r.get("imdb_id") or "").strip()
            if tt.startswith("tt"):
                try:
                    out[int(r["id"])] = tt
                except (KeyError, TypeError, ValueError):
                    continue
    return out


def gap_meta() -> dict[int, dict]:
    return load_csv_map(GAP) if GAP.exists() else {}


def prefer_large(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return u
    if "._V1_FMjpg_UX" in u:
        return re.sub(r"\._V1_FMjpg_UX\d+_", "._V1_FMjpg_UX1000_", u)
    if "._V1_UX" in u:
        return re.sub(r"\._V1_UX\d+", "._V1_UX1000", u)
    if "._V1_SX" in u:
        return re.sub(r"\._V1_SX\d+", "._V1_SX1000", u)
    # bare ._V1_.jpg from suggestion API → ask for ~1000px
    if u.endswith("._V1_.jpg"):
        return u.replace("._V1_.jpg", "._V1_UX1000.jpg")
    return u


def _year4(raw: str) -> str:
    s = (raw or "").strip()
    if len(s) >= 4 and s[:4].isdigit():
        return s[:4]
    return ""


def collect_from_ids_file(
    path: Path,
    *,
    min_votes: int,
    force: bool,
) -> list[dict]:
    """Load candidates from a CSV with id + imdb_id (gap_en_has_imdb_no_poster style)."""
    meta = gap_meta()
    sidecar = load_imdb_sidecar()
    done_hits = load_csv_map(HITS)
    done_miss = load_csv_map(MISS)
    rows: list[dict] = []
    seen: set[int] = set()
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if pid in seen:
                continue
            if has_local(pid) and not force:
                continue
            if not force and (pid in done_hits or pid in done_miss):
                continue
            tt = (r.get("imdb_id") or sidecar.get(pid) or "").strip()
            if not tt.startswith("tt"):
                continue
            g = meta.get(pid, {})
            try:
                votes = int(float(g.get("vote_count") or r.get("vote_count") or 0))
            except (TypeError, ValueError):
                votes = 0
            if votes < min_votes:
                continue
            year = _year4(r.get("year") or g.get("year") or "")
            rows.append(
                {
                    "id": pid,
                    "imdb_id": tt,
                    "title": r.get("title") or g.get("title") or "",
                    "year": year,
                    "votes": votes,
                    "bucket": "ids_file",
                }
            )
            seen.add(pid)
    rows.sort(key=lambda x: (-x["votes"], x["id"]))
    return rows


def collect_candidates(*, include_omdb_miss: bool, min_votes: int) -> list[dict]:
    meta = gap_meta()
    sidecar = load_imdb_sidecar()
    done_hits = load_csv_map(HITS)
    done_miss = load_csv_map(MISS)
    rows: list[dict] = []
    sources: list[tuple[Path, str]] = [(DEAD, "amazon_dead")]
    if include_omdb_miss:
        sources.append((OMDB_MISS, "omdb_miss"))

    seen: set[int] = set()
    for path, src in sources:
        if not path.exists():
            print(f"skip missing {path.name}", flush=True)
            continue
        with path.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                if pid in seen or has_local(pid):
                    continue
                if pid in done_hits or pid in done_miss:
                    continue
                tt = (r.get("imdb_id") or sidecar.get(pid) or "").strip()
                if not tt.startswith("tt"):
                    continue
                g = meta.get(pid, {})
                try:
                    votes = int(float(g.get("vote_count") or r.get("vote_count") or 0))
                except (TypeError, ValueError):
                    votes = 0
                if votes < min_votes:
                    continue
                rows.append(
                    {
                        "id": pid,
                        "imdb_id": tt,
                        "title": r.get("title") or g.get("title") or "",
                        "year": _year4(r.get("year") or g.get("year") or ""),
                        "votes": votes,
                        "bucket": src,
                    }
                )
                seen.add(pid)
    rows.sort(key=lambda x: (-x["votes"], x["id"]))
    return rows


def download_poster(session: requests.Session, pid: int, url: str) -> tuple[bool, str]:
    dest = POSTER_DIR / f"{pid}.jpg"
    if has_local(pid):
        return True, "exists"
    try:
        r = session.get(url, headers=IMAGE_HEADERS, timeout=60, allow_redirects=True)
    except requests.RequestException as e:
        return False, f"{type(e).__name__}: {e}"
    if r.status_code != 200 or len(r.content) < 2000:
        return False, f"http {r.status_code} len={len(r.content)}"
    if r.content[:3] not in (b"\xff\xd8\xff", b"\x89PN") and r.content[:4] != b"RIFF":
        return False, "bad magic"
    POSTER_DIR.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return True, "ok"


def suggest_poster(session: requests.Session, tt: str) -> tuple[str | None, str]:
    """IMDb autocomplete API — same host the website search uses."""
    url = SUGGEST_TMPL.format(tt=tt)
    try:
        r = session.get(url, headers=API_HEADERS, timeout=30)
    except requests.RequestException as e:
        return None, f"suggest {type(e).__name__}"
    if r.status_code != 200:
        return None, f"suggest http {r.status_code}"
    try:
        data = r.json()
    except ValueError:
        return None, "suggest bad-json"
    for item in data.get("d") or []:
        if item.get("id") != tt:
            continue
        img = (item.get("i") or {}).get("imageUrl") or ""
        if img.startswith("http"):
            return prefer_large(img), "suggest"
        return None, "suggest no-image"
    return None, "suggest tt-not-in-payload"


def extract_poster_from_page(page) -> tuple[str | None, str]:
    data = page.evaluate(
        """() => {
          const og = document.querySelector('meta[property="og:image"]');
          if (og && og.content && og.content.includes('media-amazon')) {
            return {url: og.content, source: 'og:image'};
          }
          const imgs = [...document.querySelectorAll('img')]
            .map(i => ({
              src: i.currentSrc || i.src || '',
              w: i.naturalWidth || 0,
            }))
            .filter(i => i.src.includes('media-amazon.com/images'));
          imgs.sort((a, b) => b.w - a.w);
          if (imgs.length) return {url: imgs[0].src, source: 'img'};
          return {url: null, source: 'none'};
        }"""
    )
    url = (data or {}).get("url") or None
    src = (data or {}).get("source") or "none"
    return (prefer_large(url) if url else None), src


def scrape_browser(
    candidates: list[dict],
    *,
    delay: float,
    jitter: float,
    headless: bool,
    timeout_ms: int,
    channel: str,
) -> tuple[dict[int, dict], dict[int, dict]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise SystemExit(
            "Playwright required for --browser (Python Puppeteer).\n"
            "  pip3 install playwright && playwright install chromium\n"
            f"({e})"
        ) from e

    hits = load_csv_map(HITS)
    miss = load_csv_map(MISS)
    session = requests.Session()
    launch_kwargs: dict = {"headless": headless}
    if channel:
        launch_kwargs["channel"] = channel

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        context = browser.new_context(
            user_agent=CHROME_UA,
            locale="en-US",
            timezone_id="America/New_York",
            viewport={"width": 1440, "height": 900},
            screen={"width": 1440, "height": 900},
            color_scheme="light",
            extra_http_headers=BROWSER_HEADERS,
            java_script_enabled=True,
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = context.new_page()
        page.set_default_timeout(timeout_ms)

        for i, row in enumerate(candidates, 1):
            pid, tt = int(row["id"]), row["imdb_id"]
            poster, source, reason = None, "none", ""
            try:
                resp = page.goto(
                    f"https://www.imdb.com/title/{tt}/",
                    wait_until="domcontentloaded",
                )
                status = resp.status if resp else 0
                try:
                    page.wait_for_selector(
                        'meta[property="og:image"], img[src*="media-amazon.com/images"]',
                        timeout=min(timeout_ms, 15000),
                    )
                except Exception:
                    pass
                page.wait_for_timeout(500)
                poster, source = extract_poster_from_page(page)
                if not poster:
                    reason = f"no-poster status={status}"
            except Exception as e:
                reason = f"{type(e).__name__}: {e}"

            _record(
                session, hits, miss, row, poster, source, reason,
                i, len(candidates),
            )
            if i % 10 == 0 or i == len(candidates):
                _flush(hits, miss)
            time.sleep(delay + random.uniform(0, jitter))

        context.close()
        browser.close()
    return hits, miss


def scrape_suggest(
    candidates: list[dict],
    *,
    delay: float,
    jitter: float,
) -> tuple[dict[int, dict], dict[int, dict]]:
    hits = load_csv_map(HITS)
    miss = load_csv_map(MISS)
    session = requests.Session()
    for i, row in enumerate(candidates, 1):
        poster, source = suggest_poster(session, row["imdb_id"])
        reason = "" if poster else source
        src = source if poster else "none"
        _record(
            session, hits, miss, row, poster, src, reason,
            i, len(candidates),
        )
        if i % 25 == 0 or i == len(candidates):
            _flush(hits, miss)
        time.sleep(delay + random.uniform(0, jitter))
    return hits, miss


def _record(
    session: requests.Session,
    hits: dict[int, dict],
    miss: dict[int, dict],
    row: dict,
    poster: str | None,
    source: str,
    reason: str,
    i: int,
    n: int,
) -> None:
    pid = int(row["id"])
    tt = row["imdb_id"]
    base = {
        "id": pid,
        "imdb_id": tt,
        "title": row.get("title") or "",
        "year": row.get("year") or "",
    }
    if poster:
        ok, detail = download_poster(session, pid, poster)
        if ok:
            hits[pid] = {**base, "imdb_poster": poster, "source": source}
            miss.pop(pid, None)
            print(
                f"  {i}/{n} OK {pid} {tt} votes={row.get('votes', 0)} via {source}",
                flush=True,
            )
            return
        miss[pid] = {**base, "reason": f"download {detail}"}
        print(f"  {i}/{n} FAIL-DL {pid} {detail}", flush=True)
        return
    miss[pid] = {**base, "reason": reason or "no-poster"}
    print(f"  {i}/{n} MISS {pid} {tt} {reason}", flush=True)


def _flush(hits: dict[int, dict], miss: dict[int, dict]) -> None:
    write_csv(HITS, [hits[k] for k in sorted(hits)], HIT_FIELDS)
    write_csv(MISS, [miss[k] for k in sorted(miss)], MISS_FIELDS)


def download_only(hits: dict[int, dict]) -> None:
    session = requests.Session()
    ok = fail = 0
    for pid, r in hits.items():
        if has_local(pid):
            ok += 1
            continue
        good, detail = download_poster(session, pid, r.get("imdb_poster") or "")
        if good:
            ok += 1
        else:
            fail += 1
            print(f"  FAIL {pid}: {detail}", flush=True)
    print(f"download-only ok={ok} fail={fail}")


def write_ids_out(hits: dict[int, dict]) -> int:
    rows = []
    for pid, r in sorted(hits.items()):
        if not has_local(pid):
            continue
        y = str(r.get("year") or "").strip()
        year = int(y[:4]) if len(y) >= 4 and y[:4].isdigit() else 9999
        rows.append({"id": pid, "title": r.get("title") or "", "year": year})
    write_csv(IDS_OUT, rows, IDS_FIELDS)
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Fetch live IMDb poster URLs for OMDb Amazon-404 gaps "
            "(suggestion API by default; Playwright/--browser optional)."
        )
    )
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--min-votes", type=int, default=0)
    ap.add_argument("--include-omdb-miss", action="store_true")
    ap.add_argument("--delay", type=float, default=0.35,
                    help="base delay between titles (suggest API; raise for --browser)")
    ap.add_argument("--jitter", type=float, default=0.25)
    ap.add_argument(
        "--browser",
        action="store_true",
        help="use Playwright Chromium (Puppeteer-style) instead of suggestion API",
    )
    ap.add_argument("--headed", action="store_true", help="with --browser, show the window")
    ap.add_argument(
        "--channel",
        default="",
        help="Playwright channel, e.g. chrome (system Google Chrome)",
    )
    ap.add_argument("--timeout", type=int, default=30000)
    ap.add_argument("--download-only", action="store_true")
    ap.add_argument(
        "--ids-file",
        default="",
        help="CSV with id,imdb_id[,title,year] (e.g. gap_en_has_imdb_no_poster.csv)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="with --ids-file, retry ids even if already in hits/miss or local jpg exists",
    )
    args = ap.parse_args()

    if args.download_only:
        hits = load_csv_map(HITS)
        if not hits:
            raise SystemExit(f"no hits in {HITS}")
        download_only(hits)
        print(f"ids ready for color: {write_ids_out(hits)} → {IDS_OUT.name}")
        return

    if args.ids_file:
        ids_path = Path(args.ids_file)
        if not ids_path.is_absolute():
            ids_path = Path(__file__).resolve().parent / ids_path
        if not ids_path.exists():
            raise SystemExit(f"ids-file not found: {ids_path}")
        candidates = collect_from_ids_file(
            ids_path, min_votes=args.min_votes, force=args.force
        )
    else:
        candidates = collect_candidates(
            include_omdb_miss=args.include_omdb_miss,
            min_votes=args.min_votes,
        )
    if args.limit:
        candidates = candidates[: args.limit]
    mode = "browser/Playwright" if args.browser else "suggest API"
    src = args.ids_file or f"dead+omdb_miss={args.include_omdb_miss}"
    print(
        f"candidates={len(candidates):,} mode={mode} "
        f"(min_votes={args.min_votes}, src={src}, force={args.force})",
        flush=True,
    )
    if not candidates:
        print(f"nothing to scrape; ids ready={write_ids_out(load_csv_map(HITS))}")
        return

    if args.browser:
        delay = args.delay if args.delay != 0.35 else 1.2
        jitter = args.jitter if args.jitter != 0.25 else 0.8
        hits, miss = scrape_browser(
            candidates,
            delay=delay,
            jitter=jitter,
            headless=not args.headed,
            timeout_ms=args.timeout,
            channel=args.channel,
        )
    else:
        hits, miss = scrape_suggest(
            candidates, delay=args.delay, jitter=args.jitter
        )

    _flush(hits, miss)
    n = write_ids_out(hits)
    print(
        f"\n=== IMDb POSTER ===\n"
        f"hits={len(hits):,} miss={len(miss):,} local_ids={n} → {IDS_OUT.name}\n"
        f"next: python3 analyze_color_ids.py --ids-file data/{IDS_OUT.name}"
    )


if __name__ == "__main__":
    main()
