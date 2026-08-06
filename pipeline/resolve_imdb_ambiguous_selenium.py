#!/usr/bin/env python3
"""Resolve ambiguous title.basics IMDb candidates via headed Chrome Selenium.

For each row in data/imdb_basics_match_features_ambiguous.csv:
  1. Fetch TMDB title/year/runtime + Director names from /movie/{id}/credits
  2. Visit each candidate https://www.imdb.com/title/{tt}/ (headed Chrome)
  3. Extract page title, year, directors; score vs TMDB
  4. Accept only when one candidate clearly wins on director overlap

Writes:
  data/imdb_basics_ambiguous_selenium_hits.csv
  data/imdb_basics_ambiguous_selenium_miss.csv
  data/imdb_ids.csv  (merge accepted hits)

Usage:
  export NO_PROXY='*'
  TMDB_API_KEY=... python3 resolve_imdb_ambiguous_selenium.py
  python3 resolve_imdb_ambiguous_selenium.py --dry-run   # TMDB + table only
  python3 resolve_imdb_ambiguous_selenium.py --limit 3
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import requests

from enrich_imdb_ids import DATA, SIDECAR, auth_kwargs, load_sidecar, write_sidecar

AMBIG_IN = DATA / "imdb_basics_match_features_ambiguous.csv"
HITS_OUT = DATA / "imdb_basics_ambiguous_selenium_hits.csv"
MISS_OUT = DATA / "imdb_basics_ambiguous_selenium_miss.csv"

TMDB_MOVIE = "https://api.themoviedb.org/3/movie/{pid}"
TMDB_CREDITS = "https://api.themoviedb.org/3/movie/{pid}/credits"

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_TT_RE = re.compile(r"^tt\d+$")


def normalize_name(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = _PUNCT_RE.sub(" ", s)
    s = _SPACE_RE.sub(" ", s).strip()
    return s


def normalize_title(s: str) -> str:
    s = normalize_name(s)
    if s.startswith("the "):
        s = s[4:].strip()
    return s


def title_sim(a: str, b: str) -> float:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def director_overlap(tmdb: list[str], imdb: list[str]) -> int:
    """Count TMDB directors that match any IMDb director (normalized equality
    or last-name match when unique enough)."""
    if not tmdb or not imdb:
        return 0
    imdb_n = [normalize_name(x) for x in imdb if x]
    imdb_set = set(imdb_n)
    hits = 0
    for d in tmdb:
        nd = normalize_name(d)
        if not nd:
            continue
        if nd in imdb_set:
            hits += 1
            continue
        # last token match (e.g. "J.P. Bradham" vs "JP Bradham")
        last = nd.split()[-1] if nd.split() else ""
        if len(last) >= 4 and any(
            last == (x.split()[-1] if x.split() else "") for x in imdb_n
        ):
            hits += 1
            continue
        # soft containment
        if any(nd in x or x in nd for x in imdb_n if min(len(nd), len(x)) >= 5):
            hits += 1
    return hits


def tmdb_get(session: requests.Session, api_key: str, url: str) -> dict | None:
    kwargs = auth_kwargs(api_key)
    for attempt in range(5):
        try:
            r = session.get(url, timeout=30, **kwargs)
        except requests.RequestException:
            time.sleep(1 + attempt)
            continue
        if r.status_code == 429:
            time.sleep(2 + attempt * 2)
            continue
        if r.status_code == 404:
            return None
        if r.status_code == 401:
            raise SystemExit("TMDB 401 — check TMDB_API_KEY")
        if not r.ok:
            time.sleep(1 + attempt)
            continue
        return r.json()
    return None


def fetch_tmdb(session: requests.Session, api_key: str, pid: int) -> dict:
    movie = tmdb_get(session, api_key, TMDB_MOVIE.format(pid=pid)) or {}
    credits = tmdb_get(session, api_key, TMDB_CREDITS.format(pid=pid)) or {}
    directors = [
        (c.get("name") or "").strip()
        for c in credits.get("crew") or []
        if (c.get("job") or "") == "Director" and (c.get("name") or "").strip()
    ]
    # unique preserve order
    seen: set[str] = set()
    dirs: list[str] = []
    for d in directors:
        if d not in seen:
            seen.add(d)
            dirs.append(d)
    year = None
    rd = (movie.get("release_date") or "")[:4]
    if rd.isdigit():
        year = int(rd)
    return {
        "title": (movie.get("title") or movie.get("original_title") or "").strip(),
        "year": year,
        "runtime": movie.get("runtime"),
        "directors": dirs,
    }


def build_driver():
    """Headed Chrome — IMDb blocks headless. Uses webdriver-manager (+ Xvfb on EC2)."""
    os.environ.setdefault("NO_PROXY", "*")
    os.environ.setdefault("no_proxy", "*")

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    opts = Options()
    # Explicitly NOT headless
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
    opts.add_argument("--window-size=1280,900")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
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
    return driver


def _text_list_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        x = (x or "").strip()
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def scrape_imdb_page(driver, tconst: str, pause: float = 1.2) -> dict:
    """Extract title, year, directors from an IMDb title page."""
    url = f"https://www.imdb.com/title/{tconst}/"
    driver.get(url)
    time.sleep(pause)

    page_title = (driver.title or "").strip()
    # "Title (YYYY) - IMDb" or "Title - IMDb"
    clean_title = re.sub(r"\s*[-–]\s*IMDb\s*$", "", page_title, flags=re.I).strip()
    year = None
    ym = _YEAR_RE.search(clean_title)
    if ym:
        year = int(ym.group(0))
        clean_title = _YEAR_RE.sub("", clean_title)
        clean_title = re.sub(r"\(\s*\)", "", clean_title).strip(" -–|")

    directors: list[str] = []

    # Prefer director name links in Principal Credits / Creators
    try:
        from selenium.webdriver.common.by import By

        # Modern IMDb: list items labeled Director
        for sel in (
            "li[data-testid='title-pc-principal-credit']",
            "[data-testid='title-pc-principal-credit']",
        ):
            for block in driver.find_elements(By.CSS_SELECTOR, sel):
                try:
                    label = block.find_element(By.CSS_SELECTOR, "span, button, a").text
                except Exception:
                    label = block.text[:40] if block.text else ""
                if "director" not in (label or "").lower() and "Director" not in (
                    block.text or ""
                )[:80]:
                    # check full block text starts with Director
                    bt = (block.text or "").strip()
                    if not bt.lower().startswith("director"):
                        continue
                for a in block.find_elements(By.CSS_SELECTOR, "a"):
                    href = a.get_attribute("href") or ""
                    name = (a.text or "").strip()
                    if "/name/nm" in href and name and name.lower() != "director":
                        directors.append(name)
        if not directors:
            # Older layout / fallback: links near "Director"
            for a in driver.find_elements(
                By.CSS_SELECTOR, "a[href*='/name/nm']"
            )[:40]:
                # only if ancestor text mentions Director nearby — skip for now
                pass
    except Exception:
        pass

    # JSON-LD
    if not directors or year is None:
        try:
            from selenium.webdriver.common.by import By

            for script in driver.find_elements(
                By.CSS_SELECTOR, "script[type='application/ld+json']"
            ):
                raw = script.get_attribute("innerHTML") or ""
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                objs = data if isinstance(data, list) else [data]
                for obj in objs:
                    if not isinstance(obj, dict):
                        continue
                    if not clean_title and obj.get("name"):
                        clean_title = str(obj["name"]).strip()
                    if year is None:
                        for key in ("datePublished", "dateCreated"):
                            val = str(obj.get(key) or "")
                            m = _YEAR_RE.search(val)
                            if m:
                                year = int(m.group(0))
                                break
                    if not directors:
                        d = obj.get("director")
                        if isinstance(d, dict) and d.get("name"):
                            directors.append(str(d["name"]).strip())
                        elif isinstance(d, list):
                            for item in d:
                                if isinstance(item, dict) and item.get("name"):
                                    directors.append(str(item["name"]).strip())
                                elif isinstance(item, str):
                                    directors.append(item.strip())
        except Exception:
            pass

    # og:description / meta
    if not directors:
        try:
            from selenium.webdriver.common.by import By

            for sel, attr in (
                ("meta[property='og:description']", "content"),
                ("meta[name='description']", "content"),
            ):
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                if not els:
                    continue
                content = els[0].get_attribute(attr) or ""
                # "Directed by X. With Y..."
                m = re.search(
                    r"[Dd]irected by\s+([^.|]+)",
                    content,
                )
                if m:
                    chunk = m.group(1)
                    for part in re.split(r",| and | & ", chunk):
                        part = part.strip()
                        if part:
                            directors.append(part)
                    break
        except Exception:
            pass

    # h1 fallback for title
    if not clean_title or clean_title.lower() == "imdb":
        try:
            from selenium.webdriver.common.by import By

            h1 = driver.find_elements(By.CSS_SELECTOR, "h1")
            if h1:
                clean_title = (h1[0].text or "").strip() or clean_title
        except Exception:
            pass

    return {
        "tconst": tconst,
        "url": url,
        "title": clean_title,
        "year": year,
        "directors": _text_list_unique(directors),
        "page_title": page_title,
    }


def score_candidate(
    tmdb: dict,
    cand: dict,
    corpus_title: str,
    corpus_year: int | None,
) -> dict:
    tmdb_dirs = tmdb.get("directors") or []
    imdb_dirs = cand.get("directors") or []
    d_hit = director_overlap(tmdb_dirs, imdb_dirs)
    ty = tmdb.get("year") or corpus_year
    cy = cand.get("year")
    year_match = 0
    if ty and cy:
        if ty == cy:
            year_match = 2
        elif abs(ty - cy) == 1:
            year_match = 1
    tsim = max(
        title_sim(tmdb.get("title") or "", cand.get("title") or ""),
        title_sim(corpus_title or "", cand.get("title") or ""),
    )
    # composite for ranking only — accept decision uses director rules
    score = d_hit * 10 + year_match * 2 + tsim
    return {
        **cand,
        "director_hits": d_hit,
        "year_match": year_match,
        "title_sim": round(tsim, 3),
        "score": round(score, 3),
    }


def decide_winner(scored: list[dict]) -> tuple[dict | None, str]:
    """Accept if one candidate clearly wins on directors."""
    if not scored:
        return None, "no_candidates"

    by_dir = sorted(scored, key=lambda x: (x["director_hits"], x["score"]), reverse=True)
    best = by_dir[0]
    rest = by_dir[1:]

    if best["director_hits"] >= 1:
        others_max = max((r["director_hits"] for r in rest), default=0)
        if others_max == 0:
            return best, "unique_director_match"
        # tie on directors — only accept if unique and others truly lower
        tied = [c for c in by_dir if c["director_hits"] == best["director_hits"]]
        if len(tied) == 1:
            return best, "unique_director_match"
        return None, "director_tie"

    # no director matches — do not accept on title/year alone
    if all(c["director_hits"] == 0 for c in scored):
        any_dirs = any(c.get("directors") for c in scored)
        if not any_dirs:
            return None, "no_directors_on_pages"
        return None, "no_director_overlap"

    return None, "unresolved"


def load_ambiguous(limit: int = 0) -> list[dict]:
    rows = []
    with AMBIG_IN.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            rows.append(r)
            if limit and len(rows) >= limit:
                break
    return rows


def parse_pipe(s: str) -> list[str]:
    return [p.strip() for p in (s or "").split("|") if p.strip()]


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def manual_table(rows_meta: list[dict]) -> None:
    """Fallback documentation when Selenium cannot start."""
    print("\n=== Manual resolution table (no accepts) ===")
    print(
        f"{'id':>8}  {'title':<28}  {'year':<6}  {'tmdb_dirs':<36}  candidates"
    )
    for m in rows_meta:
        dirs = "; ".join(m["tmdb"].get("directors") or [])[:34]
        cands = " | ".join(
            f"https://www.imdb.com/title/{tt}/" for tt in m["tconsts"]
        )
        title = (m.get("title") or "")[:26]
        year = m.get("year") or m["tmdb"].get("year") or ""
        print(f"{m['id']:>8}  {title:<28}  {str(year):<6}  {dirs:<36}  {cands}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=os.environ.get("TMDB_API_KEY"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pause", type=float, default=1.2, help="seconds between IMDb loads")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch TMDB only; print manual table; no Selenium / no merge",
    )
    ap.add_argument(
        "--no-merge",
        action="store_true",
        help="write hits/miss but do not update imdb_ids.csv",
    )
    args = ap.parse_args()

    if not args.api_key:
        raise SystemExit("Need TMDB_API_KEY or --api-key")
    if not AMBIG_IN.exists():
        raise SystemExit(f"missing {AMBIG_IN}")

    os.environ.setdefault("NO_PROXY", "*")
    os.environ.setdefault("no_proxy", "*")

    ambig = load_ambiguous(args.limit)
    print(f"ambiguous rows: {len(ambig)}")

    session = requests.Session()
    session.headers.update({"User-Agent": "what-fear-looks-like/resolve-ambiguous"})

    prepared: list[dict] = []
    for r in ambig:
        try:
            pid = int(r["id"])
        except (TypeError, ValueError):
            continue
        tconsts = [t for t in parse_pipe(r.get("tconsts") or "") if _TT_RE.match(t)]
        year = None
        ys = (r.get("year") or "").strip()
        if ys.isdigit():
            year = int(ys)
        tmdb = fetch_tmdb(session, args.api_key, pid)
        prepared.append(
            {
                "id": pid,
                "title": (r.get("title") or tmdb.get("title") or "").strip(),
                "year": year,
                "tconsts": tconsts,
                "n_candidates": len(tconsts),
                "tmdb": tmdb,
            }
        )
        print(
            f"  TMDB {pid}: {tmdb.get('title')!r} ({tmdb.get('year')}) "
            f"dirs={tmdb.get('directors')} n_cand={len(tconsts)}"
        )
        time.sleep(0.15)

    if args.dry_run:
        manual_table(prepared)
        return

    driver = None
    try:
        print("Starting headed Chrome…")
        driver = build_driver()
    except Exception as e:
        print(f"\nERROR: Chrome/Selenium failed to start: {e}")
        manual_table(prepared)
        raise SystemExit(1) from e

    hits: list[dict] = []
    misses: list[dict] = []

    try:
        for i, m in enumerate(prepared, 1):
            pid = m["id"]
            tmdb = m["tmdb"]
            print(f"\n[{i}/{len(prepared)}] id={pid} {m['title']!r}")
            scored: list[dict] = []
            for tt in m["tconsts"]:
                try:
                    page = scrape_imdb_page(driver, tt, pause=args.pause)
                except Exception as e:
                    print(f"  ! scrape {tt}: {e}")
                    page = {
                        "tconst": tt,
                        "url": f"https://www.imdb.com/title/{tt}/",
                        "title": "",
                        "year": None,
                        "directors": [],
                        "page_title": "",
                    }
                sc = score_candidate(tmdb, page, m["title"], m["year"] or tmdb.get("year"))
                scored.append(sc)
                print(
                    f"  {tt}: title={sc['title']!r} year={sc['year']} "
                    f"dirs={sc['directors']} d_hits={sc['director_hits']} "
                    f"ysim={sc['title_sim']} score={sc['score']}"
                )

            winner, reason = decide_winner(scored)
            tmdb_dirs = "; ".join(tmdb.get("directors") or [])
            cand_summary = "|".join(
                f"{c['tconst']}:{c['year'] or ''}:"
                f"{','.join(c['directors'])}:d{c['director_hits']}"
                for c in scored
            )

            if winner:
                hit = {
                    "id": pid,
                    "imdb_id": winner["tconst"],
                    "title": m["title"],
                    "year": m["year"] or tmdb.get("year") or "",
                    "director": tmdb_dirs,
                    "imdb_directors": "; ".join(winner.get("directors") or []),
                    "match": reason,
                    "title_sim": winner["title_sim"],
                    "year_match": winner["year_match"],
                    "candidates": cand_summary,
                }
                hits.append(hit)
                print(f"  → ACCEPT {winner['tconst']} ({reason})")
            else:
                miss = {
                    "id": pid,
                    "title": m["title"],
                    "year": m["year"] or tmdb.get("year") or "",
                    "director": tmdb_dirs,
                    "reason": reason,
                    "candidates": cand_summary,
                }
                misses.append(miss)
                print(f"  → MISS ({reason})")
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

    hit_fields = [
        "id",
        "imdb_id",
        "title",
        "year",
        "director",
        "imdb_directors",
        "match",
        "title_sim",
        "year_match",
        "candidates",
    ]
    miss_fields = ["id", "title", "year", "director", "reason", "candidates"]
    write_csv(HITS_OUT, hits, hit_fields)
    write_csv(MISS_OUT, misses, miss_fields)
    print(f"\nWrote {HITS_OUT} ({len(hits)})")
    print(f"Wrote {MISS_OUT} ({len(misses)})")

    if hits and not args.no_merge:
        mapping = load_sidecar()
        for h in hits:
            mapping[int(h["id"])] = h["imdb_id"]
        write_sidecar(mapping)
        print(f"Merged {len(hits)} hits into {SIDECAR}")

    print(f"\n=== Summary ===")
    print(f"accepted:   {len(hits)}")
    print(f"unresolved: {len(misses)}")
    if hits:
        print("sample hits:")
        for h in hits[:5]:
            print(
                f"  {h['id']} → {h['imdb_id']}  {h['title']!r}  "
                f"({h['match']}) dirs={h['director']!r}"
            )
    if misses:
        print("sample misses:")
        for m in misses[:5]:
            print(
                f"  {m['id']}  {m['title']!r}  reason={m['reason']}  "
                f"dirs={m['director']!r}"
            )


if __name__ == "__main__":
    main()
