#!/usr/bin/env python3
"""Build a visual review queue for title-box vs displayed-poster mismatches.

Catches the 11868-class bug: boxes measured on one TMDB artwork, site shows another
(or two detectors disagree on where the title sits).

Signals:
  1. SPECIMEN_PATHS path != explorer.js POSTERS path
  2. Low IoU / large vertical gap between title_boxes sources
  3. Optional --ids

Outputs:
  pipeline/data/qa/title_box_mismatch.csv
  pipeline/data/qa/title_box_review.html   ← interactive visual QA

Usage:
  python3 qa_title_boxes_mismatch.py --open
  python3 qa_title_boxes_mismatch.py --ids 11868,571
"""
from __future__ import annotations

import argparse
import json
import re
import webbrowser
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SITE = ROOT.parent / "site"
OUT_CSV = DATA / "qa" / "title_box_mismatch.csv"
OUT_HTML = DATA / "qa" / "title_box_review.html"

BOX_FILES = [
    ("easy", "title_boxes.csv"),
    ("rek", "title_boxes_rekognition.csv"),
    ("rek_thriller", "title_boxes_rekognition_thriller.csv"),
    ("rek_mystery", "title_boxes_rekognition_mystery.csv"),
    ("backfill", "title_boxes_backfill.csv"),
    ("backfill_scifi", "title_boxes_backfill_scifi.csv"),
    ("vision", "title_boxes_vision_pilot.csv"),
]


def iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def ok_box(r) -> bool:
    try:
        return float(r.text_x) >= 0 and float(r.text_w) > 0 and float(r.text_h) > 0
    except Exception:
        return False


def box_tuple(r):
    return (
        float(r.text_x),
        float(r.text_top),
        float(r.text_w),
        float(r.text_h),
    )


def load_specimen_paths() -> dict[int, str]:
    text = (SITE / "src" / "shared" / "posters.js").read_text(encoding="utf-8")
    m = re.search(r"export const SPECIMEN_PATHS=\{([^}]+)\}", text, re.S)
    if not m:
        return {}
    return {int(k): v for k, v in re.findall(r'(\d+):"([^"]+)"', m.group(1))}


def load_explorer() -> dict[int, dict]:
    text = (SITE / "data" / "explorer.js").read_text(encoding="utf-8")
    rows = re.findall(
        r'\[(\d{4}),"[^"]*","(/[^"]+\.jpg)","((?:\\.|[^"\\])*)",[^\]]*?,(\d+)\]',
        text,
    )
    out = {}
    for year, path, title, pid in rows:
        out[int(pid)] = {
            "year": int(year),
            "path": path,
            "title": title.encode("utf-8").decode("unicode_escape"),
        }
    return out


def load_box_tables() -> dict[str, pd.DataFrame]:
    tables = {}
    for key, name in BOX_FILES:
        p = DATA / name
        if not p.exists():
            continue
        df = pd.read_csv(p)
        if not {"id", "text_x", "text_top", "text_w", "text_h"}.issubset(df.columns):
            continue
        df = df[df.apply(ok_box, axis=1)].copy()
        df["id"] = df["id"].astype(int)
        if "score" in df.columns:
            df["score"] = pd.to_numeric(df["score"], errors="coerce").fillna(0)
            df = df.sort_values("score", ascending=False).drop_duplicates("id")
        else:
            df = df.drop_duplicates("id", keep="last")
        tables[key] = df.set_index("id")
    attr = pd.read_csv(
        DATA / "attributes.csv",
        usecols=["id", "text_x", "text_top", "text_w", "text_h"],
    )
    attr["id"] = attr["id"].astype(int)
    attr = attr[attr.apply(ok_box, axis=1)].drop_duplicates("id")
    tables["attr"] = attr.set_index("id")
    return tables


def pair_disagreement(tables, a, b, v_gap=0.12, iou_thr=0.15):
    if a not in tables or b not in tables:
        return {}
    da, db = tables[a], tables[b]
    out = {}
    for i in da.index.intersection(db.index):
        ba, bb = box_tuple(da.loc[i]), box_tuple(db.loc[i])
        gap = abs((ba[1] + ba[3] / 2) - (bb[1] + bb[3] / 2))
        ov = iou(ba, bb)
        if gap >= v_gap or ov < iou_thr:
            out[int(i)] = {
                "pair": f"{a}_vs_{b}",
                "v_gap": round(gap, 3),
                "iou": round(ov, 3),
            }
    return out


def build_queue(extra_ids: list[int] | None = None) -> pd.DataFrame:
    explorer = load_explorer()
    specimen = load_specimen_paths()
    tables = load_box_tables()
    flags: dict[int, dict] = {}

    def ensure(i: int):
        if i not in flags:
            meta = explorer.get(i, {})
            flags[i] = {
                "id": i,
                "title": meta.get("title", ""),
                "year": meta.get("year", ""),
                "site_path": meta.get("path", ""),
                "specimen_path": specimen.get(i, ""),
                "path_mismatch": 0,
                "box_disagree": 0,
                "signals": [],
                "v_gap_max": 0.0,
                "iou_min": 1.0,
                "attr_box": "",
                "rek_box": "",
                "easy_box": "",
                "vision_box": "",
                "review_url": f"http://127.0.0.1:5173/what-fear-looks-like/?id={i}#lookup",
            }
        return flags[i]

    for i, sp in specimen.items():
        ep = explorer.get(i, {}).get("path")
        if ep and sp and ep != sp:
            row = ensure(i)
            row["path_mismatch"] = 1
            row["signals"].append("specimen_ne_site_path")

    for a, b in (
        ("attr", "rek"),
        ("attr", "easy"),
        ("attr", "vision"),
        ("easy", "rek"),
        ("rek", "vision"),
    ):
        for i, info in pair_disagreement(tables, a, b).items():
            if i not in explorer and i not in specimen:
                continue
            row = ensure(i)
            row["box_disagree"] = 1
            row["signals"].append(info["pair"])
            row["v_gap_max"] = max(row["v_gap_max"], info["v_gap"])
            row["iou_min"] = min(row["iou_min"], info["iou"])

    if extra_ids:
        for i in extra_ids:
            ensure(i)["signals"].append("user_id")

    for i, row in flags.items():
        for key, col in (
            ("attr", "attr_box"),
            ("rek", "rek_box"),
            ("easy", "easy_box"),
            ("vision", "vision_box"),
        ):
            if key in tables and i in tables[key].index:
                t = box_tuple(tables[key].loc[i])
                row[col] = ",".join(f"{x:.4f}" for x in t)

    rows = list(flags.values())
    for r in rows:
        r["signals"] = "|".join(sorted(set(r["signals"])))
        r["priority"] = (
            100 * r["path_mismatch"]
            + 10 * r["box_disagree"]
            + min(50, int(r["v_gap_max"] * 100))
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(
        ["path_mismatch", "v_gap_max", "priority"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def _parse_box(s):
    if s is None or (isinstance(s, float) and pd.isna(s)) or str(s).strip() == "":
        return None
    parts = [float(x) for x in str(s).split(",")]
    return parts if len(parts) == 4 else None


def write_html(df: pd.DataFrame):
    records = []
    for _, r in df.iterrows():
        year = r.get("year")
        try:
            year = int(year) if pd.notna(year) and str(year).strip() != "" else None
        except Exception:
            year = None
        records.append(
            {
                "id": int(r["id"]),
                "title": str(r.get("title") or ""),
                "year": year,
                "site_path": str(r.get("site_path") or ""),
                "specimen_path": str(r.get("specimen_path") or ""),
                "path_mismatch": int(r.get("path_mismatch") or 0),
                "box_disagree": int(r.get("box_disagree") or 0),
                "signals": str(r.get("signals") or ""),
                "v_gap_max": float(r.get("v_gap_max") or 0),
                "iou_min": float(r.get("iou_min") or 1),
                "attr_box": _parse_box(r.get("attr_box")),
                "rek_box": _parse_box(r.get("rek_box")),
                "easy_box": _parse_box(r.get("easy_box")),
                "vision_box": _parse_box(r.get("vision_box")),
                "review_url": str(r.get("review_url") or ""),
            }
        )

    payload = json.dumps(records, ensure_ascii=False)
    n_path = sum(1 for x in records if x["path_mismatch"])
    n_box = sum(1 for x in records if x["box_disagree"])

    # Escape for embedding in <script>: break </script> sequences
    payload_js = payload.replace("<", "\\u003c")

    doc = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Title-box review · {len(records)}</title>
<style>
:root {{
  --bg:#090b0e; --panel:#12151a; --line:#262b33; --ink:#ece7df; --muted:#9a958a;
  --amber:#e5a00d; --red:#c1121f; --teal:#3db8a8; --blue:#5a9eb0; --ok:#6aa84f;
  color-scheme:dark; font-family:"IBM Plex Sans",ui-sans-serif,system-ui,sans-serif;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); min-height:100vh; }}
header {{
  display:flex; flex-wrap:wrap; gap:12px 18px; align-items:center; justify-content:space-between;
  padding:12px 16px; border-bottom:1px solid var(--line); position:sticky; top:0; z-index:5;
  background:rgba(9,11,14,.92); backdrop-filter:blur(10px);
}}
h1 {{ margin:0; font-size:15px; font-weight:600; }}
.stats {{ color:var(--muted); font-size:12px; }}
.controls {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; }}
button, select {{
  background:#1a1f27; color:var(--ink); border:1px solid var(--line); border-radius:8px;
  padding:7px 10px; font:inherit; font-size:12px; cursor:pointer;
}}
button:hover, select:hover {{ border-color:#3a4250; }}
button.ok {{ border-color:var(--ok); }}
button.fix {{ border-color:var(--red); color:#ff8a8a; }}
button.skip {{ border-color:var(--muted); }}
kbd {{
  font:11px/1 ui-monospace,Menlo,monospace; background:#1a1f27; border:1px solid var(--line);
  border-bottom-width:2px; border-radius:4px; padding:2px 5px; color:var(--muted);
}}
main {{ display:grid; grid-template-columns:1fr 280px; min-height:calc(100vh - 58px); }}
@media (max-width:900px) {{ main {{ grid-template-columns:1fr; }} .rail {{ display:none; }} }}
.stage {{ padding:16px; display:flex; flex-direction:column; gap:12px; min-width:0; }}
.meta-row {{ display:flex; flex-wrap:wrap; gap:10px 16px; align-items:baseline; justify-content:space-between; }}
.title {{ font-size:22px; font-weight:650; margin:0; }}
.title small {{ color:var(--muted); font-weight:500; font-size:14px; }}
.badges {{ display:flex; gap:6px; flex-wrap:wrap; }}
.badge {{ font-size:11px; padding:3px 8px; border-radius:999px; border:1px solid var(--line); color:var(--muted); }}
.badge.path {{ background:#c1121f22; color:#ff8a8a; border-color:#c1121f55; }}
.badge.boxes {{ background:#e5a00d18; color:var(--amber); border-color:#e5a00d44; }}
.compare {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; flex:1; }}
.compare.single {{ grid-template-columns:minmax(240px,520px); justify-content:center; }}
.pane {{
  background:var(--panel); border:1px solid var(--line); border-radius:12px; overflow:hidden;
  display:flex; flex-direction:column;
}}
.pane h2 {{
  margin:0; padding:8px 12px; font-size:11px; letter-spacing:.08em; text-transform:uppercase;
  color:var(--muted); border-bottom:1px solid var(--line); display:flex; justify-content:space-between; gap:8px;
}}
.frame {{
  position:relative; background:#000; flex:1; min-height:420px;
  display:flex; align-items:center; justify-content:center;
}}
.frame img {{ max-width:100%; max-height:min(72vh,780px); width:auto; height:auto; display:block; }}
.overlay {{ position:absolute; inset:0; pointer-events:none; }}
.overlay i {{ position:absolute; border:2px solid; box-shadow:0 0 0 1px #000a; border-radius:2px; }}
.overlay i.attr {{ border-color:var(--amber); }}
.overlay i.rek {{ border-color:var(--teal); }}
.overlay i.easy {{ border-color:var(--blue); }}
.overlay i.vision {{ border-color:#b08ad4; }}
.legend {{
  display:flex; flex-wrap:wrap; gap:10px 14px; padding:8px 12px; border-top:1px solid var(--line);
  font-size:11px; color:var(--muted);
}}
.legend span::before {{
  content:""; display:inline-block; width:10px; height:10px; border:2px solid; margin-right:6px;
  vertical-align:-1px; border-radius:2px;
}}
.legend .attr::before {{ border-color:var(--amber); }}
.legend .rek::before {{ border-color:var(--teal); }}
.legend .easy::before {{ border-color:var(--blue); }}
.legend .vision::before {{ border-color:#b08ad4; }}
.help {{ color:var(--muted); font-size:12px; }}
.rail {{ border-left:1px solid var(--line); background:#0d1014; overflow:auto; padding:10px; }}
.rail h3 {{ margin:4px 8px 10px; font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.08em; }}
.thumb {{
  display:grid; grid-template-columns:42px 1fr; gap:8px; align-items:center;
  padding:6px; border-radius:8px; cursor:pointer; border:1px solid transparent;
}}
.thumb:hover {{ background:#171b22; }}
.thumb.is-on {{ border-color:var(--amber); background:#1a1510; }}
.thumb img {{ width:42px; height:63px; object-fit:cover; border-radius:4px; background:#000; }}
.thumb .t {{ font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.thumb .s {{ font-size:10px; color:var(--muted); }}
.verdict-dot {{ width:8px; height:8px; border-radius:50%; display:inline-block; margin-right:4px; background:#333; }}
.verdict-dot.ok {{ background:var(--ok); }}
.verdict-dot.fix {{ background:var(--red); }}
.verdict-dot.skip {{ background:var(--muted); }}
.empty {{ padding:40px; color:var(--muted); text-align:center; }}
</style>
</head>
<body>
<header>
  <div>
    <h1>Revisión visual · cajas de título</h1>
    <div class="stats" id="stats">{len(records)} total · {n_path} path≠ · {n_box} boxes≠</div>
  </div>
  <div class="controls">
    <select id="filter" title="Filtro">
      <option value="path">Solo path≠ ({n_path})</option>
      <option value="all">Todos ({len(records)})</option>
      <option value="box">Solo boxes≠</option>
      <option value="todo">Sin veredicto</option>
      <option value="fix">Marcados fix</option>
    </select>
    <button type="button" id="prev">← <kbd>K</kbd></button>
    <button type="button" id="next">→ <kbd>J</kbd></button>
    <button type="button" class="ok" id="markOk">OK <kbd>1</kbd></button>
    <button type="button" class="fix" id="markFix">Fix <kbd>2</kbd></button>
    <button type="button" class="skip" id="markSkip">Skip <kbd>3</kbd></button>
    <button type="button" id="openAu">Autopsia <kbd>O</kbd></button>
    <button type="button" id="exportBtn">Export JSON</button>
  </div>
</header>
<main>
  <section class="stage">
    <div class="meta-row">
      <h2 class="title" id="title">—</h2>
      <div class="badges" id="badges"></div>
    </div>
    <div class="help">Teclado: <kbd>J</kbd>/<kbd>K</kbd> navegar · <kbd>1</kbd> OK · <kbd>2</kbd> Fix · <kbd>3</kbd> Skip · <kbd>O</kbd> autopsia. Empieza en path≠ (caso 11868).</div>
    <div class="compare" id="compare"></div>
  </section>
  <aside class="rail">
    <h3 id="railTitle">Cola</h3>
    <div id="rail"></div>
  </aside>
</main>
<script>
const ALL = {payload_js};
const STORE_KEY = 'aof_title_box_review_v1';
const IMG = (path, w='w500') => path ? ('https://image.tmdb.org/t/p/' + w + path) : '';

function loadVerdicts() {{
  try {{ return JSON.parse(localStorage.getItem(STORE_KEY) || '{{}}'); }} catch (e) {{ return {{}}; }}
}}
function saveVerdicts(v) {{ localStorage.setItem(STORE_KEY, JSON.stringify(v)); }}

let verdicts = loadVerdicts();
let filter = 'path';
let queue = [];
let idx = 0;

function filtered() {{
  return ALL.filter(r => {{
    const v = verdicts[r.id];
    if (filter === 'path') return !!r.path_mismatch;
    if (filter === 'box') return !!r.box_disagree;
    if (filter === 'todo') return !v;
    if (filter === 'fix') return v === 'fix';
    return true;
  }});
}}

function boxEl(box, cls) {{
  if (!box) return '';
  const tx = box[0], tt = box[1], tw = box[2], th = box[3];
  return '<i class="' + cls + '" style="left:' + (tx*100) + '%;top:' + (tt*100) + '%;width:' + (tw*100) + '%;height:' + (th*100) + '%"></i>';
}}

function pane(label, path, boxes, note) {{
  if (!path) return '';
  return '<div class="pane"><h2><span>' + label + '</span><span>' + (note || '') + '</span></h2>' +
    '<div class="frame"><img src="' + IMG(path) + '" alt=""><div class="overlay">' + boxes + '</div></div>' +
    '<div class="legend"><span class="attr">attr</span><span class="rek">rek</span><span class="easy">easy</span><span class="vision">vision</span></div></div>';
}}

function fitOverlays() {{
  document.querySelectorAll('.frame').forEach(frame => {{
    const img = frame.querySelector('img');
    const ov = frame.querySelector('.overlay');
    if (!img || !ov) return;
    const place = () => {{
      const fr = frame.getBoundingClientRect();
      const ir = img.getBoundingClientRect();
      ov.style.left = (ir.left - fr.left) + 'px';
      ov.style.top = (ir.top - fr.top) + 'px';
      ov.style.width = ir.width + 'px';
      ov.style.height = ir.height + 'px';
    }};
    if (img.complete) place();
    img.onload = place;
    place();
  }});
}}

function render() {{
  queue = filtered();
  const compare = document.getElementById('compare');
  if (!queue.length) {{
    compare.innerHTML = '<div class="empty">Nada en este filtro.</div>';
    document.getElementById('title').textContent = '—';
    document.getElementById('rail').innerHTML = '';
    document.getElementById('stats').textContent = '0 en filtro · ' + Object.keys(verdicts).length + ' veredictos';
    return;
  }}
  idx = Math.max(0, Math.min(idx, queue.length - 1));
  const r = queue[idx];
  const v = verdicts[r.id];
  document.getElementById('title').innerHTML =
    (r.title || 'Untitled') + ' <small>' + (r.year || '') + ' · id ' + r.id +
    ' · ' + (idx+1) + '/' + queue.length + (v ? ' · ' + v : '') + '</small>';

  const badges = [];
  if (r.path_mismatch) badges.push('<span class="badge path">path≠ arte distinto</span>');
  if (r.box_disagree) badges.push('<span class="badge boxes">boxes≠ gap ' + r.v_gap_max + ' iou ' + r.iou_min + '</span>');
  document.getElementById('badges').innerHTML = badges.join('');

  const boxes = boxEl(r.attr_box,'attr') + boxEl(r.rek_box,'rek') + boxEl(r.easy_box,'easy') + boxEl(r.vision_box,'vision');

  if (r.path_mismatch && r.site_path && r.specimen_path && r.site_path !== r.specimen_path) {{
    compare.className = 'compare';
    compare.innerHTML =
      pane('Arte del sitio (autopsia)', r.site_path, boxes, 'caja sobre ESTE arte') +
      pane('Arte specimen / OCR', r.specimen_path, boxes, 'posible origen de la caja');
  }} else {{
    compare.className = 'compare single';
    compare.innerHTML = pane('Arte del sitio', r.site_path || r.specimen_path, boxes, r.signals || '');
  }}

  document.getElementById('railTitle').textContent = 'Cola · ' + queue.length;
  document.getElementById('rail').innerHTML = queue.map((x, i) => {{
    const vv = verdicts[x.id] || '';
    const path = x.site_path || x.specimen_path;
    return '<div class="thumb' + (i===idx?' is-on':'') + '" data-i="' + i + '">' +
      '<img src="' + IMG(path,'w92') + '" alt="" loading="lazy">' +
      '<div><div class="t"><span class="verdict-dot ' + vv + '"></span>' + (x.title || x.id) + '</div>' +
      '<div class="s">' + x.id + (x.path_mismatch?' · path≠':'') + (x.box_disagree?' · boxes≠':'') + '</div></div></div>';
  }}).join('');

  document.getElementById('stats').textContent =
    queue.length + ' en filtro · ' + (idx+1) + '/' + queue.length + ' · ' + Object.keys(verdicts).length + ' veredictos';
  requestAnimationFrame(fitOverlays);
}}

function go(d) {{ idx += d; render(); }}
function mark(v) {{
  if (!queue.length) return;
  verdicts[queue[idx].id] = v;
  saveVerdicts(verdicts);
  if (filter === 'todo') {{
    queue = filtered();
    idx = Math.min(idx, Math.max(0, queue.length - 1));
  }} else {{
    idx = Math.min(idx + 1, Math.max(0, queue.length - 1));
  }}
  render();
}}

document.getElementById('filter').addEventListener('change', e => {{ filter = e.target.value; idx = 0; render(); }});
document.getElementById('prev').onclick = () => go(-1);
document.getElementById('next').onclick = () => go(1);
document.getElementById('markOk').onclick = () => mark('ok');
document.getElementById('markFix').onclick = () => mark('fix');
document.getElementById('markSkip').onclick = () => mark('skip');
document.getElementById('openAu').onclick = () => {{ if (queue[idx]) window.open(queue[idx].review_url, '_blank'); }};
document.getElementById('rail').addEventListener('click', e => {{
  const t = e.target.closest('.thumb'); if (!t) return; idx = +t.dataset.i; render();
}});
document.getElementById('exportBtn').onclick = () => {{
  const blob = new Blob([JSON.stringify({{ verdicts, at: new Date().toISOString() }}, null, 2)], {{ type:'application/json' }});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
  a.download = 'title_box_review_verdicts.json'; a.click();
}};
window.addEventListener('keydown', e => {{
  if (e.target.matches('input,textarea,select')) return;
  const k = e.key.toLowerCase();
  if (k === 'j' || k === 'arrowright') {{ e.preventDefault(); go(1); }}
  if (k === 'k' || k === 'arrowleft') {{ e.preventDefault(); go(-1); }}
  if (k === '1') mark('ok');
  if (k === '2') mark('fix');
  if (k === '3') mark('skip');
  if (k === 'o' && queue[idx]) window.open(queue[idx].review_url, '_blank');
}});
window.addEventListener('resize', () => fitOverlays());
render();
</script>
</body>
</html>
"""
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(doc, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="", help="comma ids to force-include")
    ap.add_argument("--open", action="store_true", help="open HTML in browser")
    ap.add_argument("--limit", type=int, default=0, help="cap records in HTML (0=all)")
    args = ap.parse_args()

    extra = [int(x) for x in args.ids.split(",") if x.strip()]
    df = build_queue(extra or None)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    view = df.head(args.limit) if args.limit else df
    write_html(view)
    print(f"wrote {OUT_CSV} ({len(df):,} rows)")
    print(f"wrote {OUT_HTML}")
    print(f"  path_mismatch={int(df['path_mismatch'].sum()) if len(df) else 0}")
    print(f"  box_disagree={int(df['box_disagree'].sum()) if len(df) else 0}")
    print(f"file://{OUT_HTML.resolve()}")
    if args.open:
        webbrowser.open(OUT_HTML.resolve().as_uri())


if __name__ == "__main__":
    main()
