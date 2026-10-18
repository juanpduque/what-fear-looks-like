#!/usr/bin/env python3
"""
Exporta las series de graficas del ensayo a site/data/series.js.

Fuente: CSV/JSON ya filtrados en pipeline/data/ (posters, attributes, faces,
census, typography, segmentation + decade aggregates). Misma metodologia que
el sitio: medias por decada y rolling trailing de 5 anos (min_periods=2).

  python3 export_site_series.py

Tambien lo invoca apply_exclusions.py al final, para que un re-filtro
regenere automaticamente lo que consume index.html.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = ROOT.parent / "site" / "data" / "series.js"

DECADES = [
    "1920s",
    "1930s",
    "1940s",
    "1950s",
    "1960s",
    "1970s",
    "1980s",
    "1990s",
    "2000s",
    "2010s",
    "2020s",
]
ROLL_YEARS = list(range(1925, 2021, 5)) + [2022, 2025, 2026]
DIAG_YEARS = list(range(1925, 2021, 5)) + [2025, 2026]
CENSUS_KEYS = {
    "giant monster": "giant_monster",
    "vampire": "vampire",
    "witch": "witch",
    "masked killer": "masked_killer",
    "zombie": "zombie",
    "ghost": "ghost",
}


def _load_json(name: str):
    path = DATA / name
    if not path.exists():
        raise FileNotFoundError(f"falta {path} — corre apply_exclusions.py antes")
    return json.loads(path.read_text())


def _yearly_mean(rows, year_key, val_fn):
    buckets: dict[int, list[float]] = defaultdict(list)
    for r in rows:
        y = int(float(r[year_key]))
        if y < 1897 or y > 2030:  # skip undated sentinel (9999)
            continue
        buckets[y].append(val_fn(r))
    return {y: sum(v) / len(v) for y, v in buckets.items()}


def _yearly_buckets(rows, year_key, val_fn):
    buckets: dict[int, list[float]] = defaultdict(list)
    for r in rows:
        y = int(float(r[year_key]))
        if y < 1897 or y > 2030:  # skip undated sentinel (9999)
            continue
        buckets[y].append(val_fn(r))
    return buckets


def _trailing_ci(buckets, years, rnd: int = 1, window: int = 5, min_periods: int = 2):
    """95% interval for each _trailing_roll point: [[year, lo, hi, n_posters], ...].

    The rolling value is the mean of the window's yearly means, so its variance
    is sum(var_y / n_y) / k^2 over the k years with posters. Years with a single
    poster borrow the window's pooled variance. Early decades have few posters
    per year; the essay draws this as a band so thin data is not read as trend.
    """
    out = []
    for y in years:
        if not buckets.get(y):
            continue
        yrs = [yy for yy in range(y - window + 1, y + 1) if buckets.get(yy)]
        if len(yrs) < min_periods:
            continue
        pooled = [v for yy in yrs for v in buckets[yy]]
        pooled_var = statistics.variance(pooled) if len(pooled) > 1 else 0.0
        k = len(yrs)
        est = sum(statistics.fmean(buckets[yy]) for yy in yrs) / k
        var = sum(
            (statistics.variance(buckets[yy]) if len(buckets[yy]) > 1 else pooled_var)
            / len(buckets[yy])
            for yy in yrs
        ) / (k * k)
        half = 1.96 * math.sqrt(var)
        out.append([y, round(est - half, rnd), round(est + half, rnd), len(pooled)])
    return out


def _wilson(k: int, n: int, z: float = 1.96):
    """95% Wilson interval for a share k/n, in percent."""
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * max(0.0, c - h), 1), round(100 * min(1.0, c + h), 1)]


def _mean_ci(values, scale: float = 100.0):
    """95% normal interval for a mean of per-poster values, in percent."""
    n = len(values)
    if n < 2:
        return None
    m = statistics.fmean(values)
    half = 1.96 * statistics.stdev(values) / math.sqrt(n)
    return [round(scale * max(0.0, m - half), 1), round(scale * (m + half), 1)]


def _by_decade(rows):
    out: dict[int, list] = defaultdict(list)
    for r in rows:
        out[int(float(r["year"])) // 10 * 10].append(r)
    return out


def _decade_stats(posters, seg, typo_rows, census_rows, chart_decades, census_decades):
    """Per-decade n and 95% intervals behind RIVER, TYPO, BLOOD_SEMANTIC and CENSUS_SERIES.

    RIVER / BLOOD are means of per-poster values (normal interval on the mean); TYPO
    and CENSUS are shares of posters or titles (Wilson). Every n is counted on the
    published corpus, so it matches the *_decade.json files the series come from.
    """
    bands = ("band_red", "band_warm", "band_green", "band_blue", "band_purple", "band_dark")
    registers = ("ornate", "decorative", "standard", "clean", "minimal")
    pos, sg = _by_decade(posters), _by_decade(seg)
    ty = _by_decade(r for r in typo_rows if 1920 <= int(float(r["year"])) <= 2029)
    ce = _by_decade(census_rows)
    decs = sorted(chart_decades)
    stats = {
        "river": {
            "n": [len(pos[d]) for d in decs],
            "ci": [[_mean_ci([float(r[b]) for r in pos[d]]) for b in bands] for d in decs],
        },
        "typo": {
            "n": [len(ty[d]) for d in decs],
            "ci": [
                [_wilson(sum(r["register"] == g for r in ty[d]), len(ty[d])) for g in registers]
                for d in decs
            ],
        },
        "blood": {
            "n": [len(sg[d]) for d in decs],
            "ci": [_mean_ci([float(r["clip_blood"]) for r in sg[d]]) for d in decs],
        },
        "census": {
            "decades": list(census_decades),
            "n": [len(ce[d]) for d in census_decades],
            "ci": {
                label: [
                    _wilson(sum(r["label"] == col for r in ce[d]), len(ce[d]))
                    for d in census_decades
                ]
                for label, col in CENSUS_KEYS.items()
            },
        },
    }
    return stats


def _trailing_roll(series: dict[int, float], window: int = 5, min_periods: int = 2):
    out = {}
    for y in sorted(series):
        vals = [series[yy] for yy in range(y - window + 1, y + 1) if yy in series]
        if len(vals) >= min_periods:
            out[y] = sum(vals) / len(vals)
    return out


def _pts_at(roll: dict[int, float], years: list[int], rnd: int = 1):
    return [[y, round(roll[y], rnd)] for y in years if y in roll]


def _read_csv(name: str):
    import csv

    from corpus import canonical_ids

    path = DATA / name
    if not path.exists():
        raise FileNotFoundError(f"falta {path}")
    keep = canonical_ids()
    seen: set[int] = set()
    rows = []
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            pid = int(r["id"])
            if pid in keep and pid not in seen:
                seen.add(pid)
                rows.append(r)
    return rows


def build_series() -> dict:
    posters = _read_csv("posters.csv")
    attrs = _read_csv("attributes.csv")
    faces = _read_csv("faces_v2.csv")
    hue = _load_json("hue_river.json")
    typo_d = _load_json("typography_decade.json")
    cens_d = _load_json("census_decade.json")
    seg_d = _load_json("segmentation_decade.json")

    # vote_count for mainstream line (optional — skip decades if missing)
    votes: dict[int, float] = {}
    hm = DATA / "horror_movies.csv"
    if hm.exists():
        import csv

        with hm.open(newline="") as f:
            for r in csv.DictReader(f):
                try:
                    votes[int(r["id"])] = float(r.get("vote_count") or 0)
                except (TypeError, ValueError, KeyError):
                    pass

    # Charts label with DECADES (1920s–2020s). Decade JSONs may include
    # thin pre-1920 buckets — keep those out of RIVER / TYPO / BLOOD_SEMANTIC
    # so series length always matches DECADES.
    chart_decades = {1920 + 10 * i for i in range(11)}

    river = []
    for row in sorted(hue, key=lambda x: int(x["decade"])):
        if int(row["decade"]) not in chart_decades:
            continue
        river.append(
            [
                round(float(row["band_red"]) * 100, 1),
                round(float(row["band_warm"]) * 100, 1),
                round(float(row["band_green"]) * 100, 1),
                round(float(row["band_blue"]) * 100, 1),
                round(float(row["band_purple"]) * 100, 1),
                round(float(row["band_dark"]) * 100, 1),
            ]
        )

    typo = []
    for row in sorted(typo_d, key=lambda r: int(r["decade"])):
        if int(row["decade"]) not in chart_decades:
            continue
        typo.append(
            [
                round(float(row[k]), 4)
                for k in ("ornate", "decorative", "standard", "clean", "minimal")
            ]
        )

    blood_semantic = [
        round(float(row["clip_blood"]) * 100, 1)
        for row in sorted(seg_d, key=lambda r: int(r["decade"]))
        if int(row["decade"]) in chart_decades
    ]

    if not (len(river) == len(typo) == len(blood_semantic) == len(DECADES)):
        raise SystemExit(
            f"chart series length mismatch: "
            f"RIVER={len(river)} TYPO={len(typo)} "
            f"BLOOD_SEMANTIC={len(blood_semantic)} DECADES={len(DECADES)} "
            f"(expected all {len(DECADES)}; filter decade aggregates to 1920–2020)"
        )

    bright = _yearly_mean(posters, "year", lambda r: float(r["brightness"]))
    red = _yearly_mean(posters, "year", lambda r: float(r["red_share"]) * 100)
    face_y = _yearly_mean(
        faces,
        "year",
        lambda r: 100.0 if int(float(r["n_faces"])) > 0 else 0.0,
    )
    text_y = _yearly_mean(attrs, "year", lambda r: float(r["text_area"]) * 100)
    sym_y = _yearly_mean(attrs, "year", lambda r: float(r["symmetry"]))
    diag_y = _yearly_mean(attrs, "year", lambda r: float(r["diagonal_score"]) * 100)
    ci_src = {
        "dark": (_yearly_buckets(posters, "year", lambda r: float(r["brightness"])), ROLL_YEARS, 1),
        "red": (
            _yearly_buckets(posters, "year", lambda r: float(r["red_share"]) * 100),
            ROLL_YEARS,
            1,
        ),
        "face": (
            _yearly_buckets(
                faces, "year", lambda r: 100.0 if int(float(r["n_faces"])) > 0 else 0.0
            ),
            ROLL_YEARS,
            1,
        ),
        "text": (
            _yearly_buckets(attrs, "year", lambda r: float(r["text_area"]) * 100),
            ROLL_YEARS,
            1,
        ),
        "sym": (_yearly_buckets(attrs, "year", lambda r: float(r["symmetry"])), ROLL_YEARS, 3),
        "diag": (
            _yearly_buckets(attrs, "year", lambda r: float(r["diagonal_score"]) * 100),
            DIAG_YEARS,
            1,
        ),
    }

    main_buckets: dict[int, list[float]] = defaultdict(list)
    for r in posters:
        pid = int(r["id"])
        y = int(float(r["year"]))
        if votes.get(pid, 0) >= 100:
            main_buckets[(y // 10) * 10].append(float(r["brightness"]))
    main_dec = [
        [d, round(sum(v) / len(v), 1)] for d, v in sorted(main_buckets.items()) if d >= 1950
    ]

    census = {}
    for label, col in CENSUS_KEYS.items():
        pts = []
        for row in sorted(cens_d, key=lambda r: int(r["decade"])):
            pts.append([int(row["decade"]), round(float(row.get(col, 0) or 0) * 100, 1)])
        census[label] = pts

    seg_rows = _read_csv("segmentation.csv") if (DATA / "segmentation.csv").exists() else []
    seg_n = len(seg_rows)
    decade_stats = _decade_stats(
        posters,
        seg_rows,
        _read_csv("typography.csv"),
        _read_csv("census.csv"),
        chart_decades,
        sorted(int(r["decade"]) for r in cens_d),
    )

    return {
        "n": len(posters),
        "seg_n": seg_n,
        "DECADES": DECADES,
        "RIVER": river,
        "TYPO": typo,
        "BLOOD_SEMANTIC": blood_semantic,
        "MAIN_DEC": main_dec,
        "DARK_PTS": _pts_at(_trailing_roll(bright), ROLL_YEARS, 1),
        "RED_PTS": _pts_at(_trailing_roll(red), ROLL_YEARS, 1),
        "FACE_PTS": _pts_at(_trailing_roll(face_y), ROLL_YEARS, 1),
        "TEXT_PTS": _pts_at(_trailing_roll(text_y), ROLL_YEARS, 1),
        "SYM_PTS": _pts_at(_trailing_roll(sym_y), ROLL_YEARS, 3),
        "DIAG_PTS": _pts_at(_trailing_roll(diag_y), DIAG_YEARS, 1),
        "CENSUS_SERIES": census,
        "DECADE_STATS": decade_stats,
        "SERIES_CI": {k: _trailing_ci(b, yrs, rnd) for k, (b, yrs, rnd) in ci_src.items()},
    }


def _js_num(v):
    if isinstance(v, float):
        # compact but stable: drop trailing zeros via json then tweak
        s = json.dumps(v)
        return s
    return json.dumps(v)


def _js_pts(rows):
    parts = []
    for a, b in rows:
        parts.append(f"[{a},{_js_num(b)}]")
    return "[" + ",".join(parts) + "]"


def _js_matrix(rows, as_pct_1dp=False):
    lines = []
    for r in rows:
        if as_pct_1dp:
            cells = ",".join(f"{v:4.1f}" for v in r)
            lines.append(f" [{cells}]")
        else:
            cells = ",".join(f"{v:.4f}" for v in r)
            lines.append(f" [{cells}]")
    return ",\n".join(lines)


def render_js(series: dict) -> str:
    n = series["n"]
    seg_n = series["seg_n"]
    river = series["RIVER"]
    typo = series["TYPO"]
    decades = series["DECADES"]

    typo_lines = []
    for i, row in enumerate(typo):
        comma = "," if i < len(typo) - 1 else ""
        cells = ",".join(f"{v:.4f}" for v in row)
        typo_lines.append(f" [{cells}]{comma} // {decades[i]}")

    cens_lines = ["const CENSUS_SERIES={"]
    items = list(series["CENSUS_SERIES"].items())
    for i, (name, pts) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        cens_lines.append(f'  "{name}":{_js_pts(pts)}{comma}')
    cens_lines.append("};")

    return f"""/* Auto-generated by pipeline/export_site_series.py — do not edit by hand.
   n={n:,} posters; segmentation n={seg_n:,}.
   Re-run: python3 pipeline/export_site_series.py
   (also runs at the end of apply_exclusions.py) */
const DECADES={json.dumps(decades)};
const RIVER=[ /* 1920s..2020s — [red, warm, green, blue, purple, dark/grey] % */
{_js_matrix(river, as_pct_1dp=True)}
];
const TYPO=[
{chr(10).join(typo_lines)}
];
const BLOOD_PIXEL=RIVER.map(r=>r[0]);
const BLOOD_SEMANTIC={json.dumps(series["BLOOD_SEMANTIC"])};
const MAIN_DEC={_js_pts(series["MAIN_DEC"])};
const DARK_PTS={_js_pts(series["DARK_PTS"])};
const RED_PTS={_js_pts(series["RED_PTS"])};
const FACE_PTS={_js_pts(series["FACE_PTS"])};
const TEXT_PTS={_js_pts(series["TEXT_PTS"])};
const SYM_PTS={_js_pts(series["SYM_PTS"])};
const DIAG_PTS={_js_pts(series["DIAG_PTS"])};
{chr(10).join(cens_lines)}
const SERIES_CI={json.dumps(series["SERIES_CI"], separators=(",", ":"))}; /* [year, lo95, hi95, n posters] */
const DECADE_STATS={json.dumps(series["DECADE_STATS"], separators=(",", ":"))}; /* per decade: n and 95% [lo,hi] behind RIVER, TYPO, BLOOD_SEMANTIC, CENSUS_SERIES */
const AOF_META={{n:{n},seg_n:{seg_n}}};
"""


def export(out: Path | None = None) -> Path:
    out = out or OUT
    series = build_series()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_js(series))
    print(f"escrito {out.relative_to(ROOT.parent)} (n={series['n']:,}, seg_n={series['seg_n']:,})")
    return out


def main():
    export()


if __name__ == "__main__":
    main()
