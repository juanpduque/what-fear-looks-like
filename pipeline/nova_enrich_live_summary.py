#!/usr/bin/env python3
"""Live summary for nova_enrich.csv (local only; no Bedrock).

  python3 nova_enrich_live_summary.py
  python3 nova_enrich_live_summary.py --watch 60
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent / "data" / "qa" / "nova_enrich"
CSV_PATH = BASE / "nova_enrich.csv"
OUT_MD = BASE / "live_summary.md"
OUT_JSON = BASE / "live_summary.json"
POSTERS_CSV = Path(__file__).resolve().parent / "data" / "posters.csv"


def _f(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def summarize() -> dict:
    rows = []
    if CSV_PATH.exists():
        with CSV_PATH.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                if str(r.get("status") or "") == "ok":
                    rows.append(r)

    # unique by id (last wins)
    by_id: dict[int, dict] = {}
    for r in rows:
        try:
            by_id[int(r["id"])] = r
        except (TypeError, ValueError):
            pass
    rows = list(by_id.values())

    total_corpus = 0
    if POSTERS_CSV.exists():
        with POSTERS_CSV.open(encoding="utf-8", errors="replace") as f:
            total_corpus = sum(1 for _ in csv.DictReader(f))

    n = len(rows)
    langs = Counter()
    moods = Counter()
    for r in rows:
        for lang in str(r.get("languages") or "").split("|"):
            lang = lang.strip()
            if lang:
                langs[lang] += 1
        for mood in str(r.get("mood") or "").split("|"):
            mood = mood.strip().lower()
            if mood:
                moods[mood] += 1

    def mean_col(col: str) -> float:
        if not rows:
            return 0.0
        return sum(_f(r.get(col)) for r in rows) / n

    def pct_ge(col: str, thr: float = 0.5) -> float:
        if not rows:
            return 0.0
        return 100.0 * sum(1 for r in rows if _f(r.get(col)) >= thr) / n

    payload = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ok_unique": n,
        "corpus_total": total_corpus,
        "coverage_pct": round(100.0 * n / total_corpus, 2) if total_corpus else None,
        "mean_latency_s": round(mean_col("latency_s"), 3),
        "signals": {
            "weapon_ge_0.5_pct": round(pct_ge("weapon"), 1),
            "monster_ge_0.5_pct": round(pct_ge("monster"), 1),
            "blood_gore_ge_0.5_pct": round(pct_ge("blood_gore"), 1),
            "violence_ge_0.5_pct": round(pct_ge("violence"), 1),
            "person_ge_0.5_pct": round(pct_ge("person"), 1),
            "mean_weapon": round(mean_col("weapon"), 3),
            "mean_monster": round(mean_col("monster"), 3),
            "mean_blood_gore": round(mean_col("blood_gore"), 3),
            "mean_violence": round(mean_col("violence"), 3),
        },
        "top_languages": langs.most_common(10),
        "top_moods": moods.most_common(15),
        "examples": [
            {
                "id": r.get("id"),
                "title": r.get("title"),
                "year": r.get("year"),
                "title_text": r.get("title_text"),
                "mood": r.get("mood"),
                "description": (r.get("description") or "")[:140],
            }
            for r in sorted(rows, key=lambda x: _f(x.get("monster")) + _f(x.get("weapon")), reverse=True)[:5]
        ],
    }
    return payload


def render_md(p: dict) -> str:
    lines = [
        f"# Nova enrich — resumen vivo",
        "",
        f"Actualizado: `{p['ts']}`",
        "",
        f"- OK únicos: **{p['ok_unique']}** / {p.get('corpus_total') or '?'} ({p.get('coverage_pct')}%)",
        f"- Latencia media: **{p['mean_latency_s']}s**",
        "",
        "## Señales (≥0.5)",
        "",
    ]
    sig = p["signals"]
    lines += [
        f"- weapon: {sig['weapon_ge_0.5_pct']}% (mean {sig['mean_weapon']})",
        f"- monster: {sig['monster_ge_0.5_pct']}% (mean {sig['mean_monster']})",
        f"- blood_gore: {sig['blood_gore_ge_0.5_pct']}% (mean {sig['mean_blood_gore']})",
        f"- violence: {sig['violence_ge_0.5_pct']}% (mean {sig['mean_violence']})",
        f"- person: {sig['person_ge_0.5_pct']}%",
        "",
        "## Top idiomas",
        "",
    ]
    for k, v in p["top_languages"]:
        lines.append(f"- {k}: {v}")
    lines += ["", "## Top moods", ""]
    for k, v in p["top_moods"]:
        lines.append(f"- {k}: {v}")
    lines += ["", "## Ejemplos (alto monster+weapon)", ""]
    for e in p["examples"]:
        lines.append(
            f"- **{e['title']}** ({e['year']}, id {e['id']}): "
            f"`{e['title_text']}` — {e['mood']} — {e['description']}"
        )
    lines.append("")
    return "\n".join(lines)


def write_once() -> dict:
    BASE.mkdir(parents=True, exist_ok=True)
    payload = summarize()
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    OUT_MD.write_text(render_md(payload), encoding="utf-8")
    print(
        f"{payload['ts']} ok={payload['ok_unique']} "
        f"cov={payload.get('coverage_pct')}% → {OUT_MD.name}",
        flush=True,
    )
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--watch", type=float, default=0, help="refresh every N seconds (0=once)")
    args = ap.parse_args()
    if args.watch and args.watch > 0:
        while True:
            write_once()
            time.sleep(args.watch)
    write_once()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
