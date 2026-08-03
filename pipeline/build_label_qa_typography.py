#!/usr/bin/env python3
"""Build typography / text-role labeling QA for team (GitHub PAT save).

Classes (visual judgment on the poster, OCR is only a hint):
  image_led  — image dominates; little or no meaningful lettering
  title_led  — big title (maybe small credits); text is not a wall of copy
  text_heavy — lots of copy: credits, quotes, taglines, dense lettering
  doubtful   — unsure

Sample stratified by OCR proxies (empty / short / long) from poster_ocr.csv.

Writes:
  site/label-qa-typography.html
  pipeline/qa/label-qa-typography.html
  pipeline/data/qa/typography_qa_r1_ids.csv
  pipeline/data/qa/typography_qa_r1_labels.json  (stub if missing)

  python3 build_label_qa_typography.py
  python3 build_label_qa_typography.py --n 250
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OCR = DATA / "poster_ocr.csv"
OCR_TX = DATA / "poster_ocr_textract.csv"
HM = DATA / "horror_movies.csv"
BF = DATA / "poster_paths_backfill.csv"
OUT_SITE = ROOT.parent / "site" / "label-qa-typography.html"
OUT_QA = ROOT / "qa" / "label-qa-typography.html"
OUT_IDS = DATA / "qa" / "typography_qa_r1_ids.csv"
OUT_LABELS = DATA / "qa" / "typography_qa_r1_labels.json"
IMG = "https://image.tmdb.org/t/p/w500"


def load_paths() -> dict[int, str]:
    paths: dict[int, str] = {}
    for src in (HM, BF):
        if not src.exists():
            continue
        with src.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(float(r["id"]))
                except Exception:
                    continue
                p = (r.get("poster_path") or "").strip()
                if p.startswith("/") and pid not in paths:
                    paths[pid] = p
    return paths


def load_meta() -> dict[int, dict]:
    meta: dict[int, dict] = {}
    posters = DATA / "posters.csv"
    if posters.exists():
        with posters.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except Exception:
                    continue
                meta[pid] = {
                    "title": r.get("title") or "",
                    "year": int(float(r["year"])) if r.get("year") else "",
                }
    if HM.exists():
        with HM.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(float(r["id"]))
                except Exception:
                    continue
                if pid not in meta:
                    rd = (r.get("release_date") or "")[:4]
                    meta[pid] = {
                        "title": r.get("title") or r.get("original_title") or "",
                        "year": int(rd) if rd.isdigit() else "",
                    }
    return meta


def load_ocr_map() -> dict[int, dict]:
    """Prefer EasyOCR; fill empties from Textract when available."""
    out: dict[int, dict] = {}
    if OCR.exists():
        with OCR.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except Exception:
                    continue
                text = (r.get("full_ocr") or "").strip()
                try:
                    n_lines = int(float(r.get("n_lines") or 0))
                except Exception:
                    n_lines = 0
                try:
                    n_boxes = int(float(r.get("n_boxes") or 0))
                except Exception:
                    n_boxes = 0
                try:
                    mean_conf = float(r.get("mean_conf") or 0)
                except Exception:
                    mean_conf = 0.0
                out[pid] = {
                    "ocr_chars": len(text),
                    "n_lines": n_lines,
                    "n_boxes": n_boxes,
                    "mean_conf": round(mean_conf, 4),
                    "ocr_preview": text[:120].replace("\n", " "),
                    "ocr_source": "easyocr",
                }
    if OCR_TX.exists():
        with OCR_TX.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except Exception:
                    continue
                text = (r.get("full_ocr") or "").strip()
                cur = out.get(pid)
                if cur and cur["ocr_chars"] > 0:
                    continue
                try:
                    n_lines = int(float(r.get("n_lines") or 0))
                except Exception:
                    n_lines = 0
                try:
                    n_boxes = int(float(r.get("n_boxes") or 0))
                except Exception:
                    n_boxes = 0
                out[pid] = {
                    "ocr_chars": len(text),
                    "n_lines": n_lines,
                    "n_boxes": n_boxes,
                    "mean_conf": 0.0,
                    "ocr_preview": text[:120].replace("\n", " "),
                    "ocr_source": "textract" if text else (cur or {}).get("ocr_source", "easyocr"),
                }
    return out


def proxy_bucket(ocr: dict) -> str:
    chars = int(ocr.get("ocr_chars") or 0)
    lines = int(ocr.get("n_lines") or 0)
    boxes = int(ocr.get("n_boxes") or 0)
    # Proxies only for sampling balance — labelers judge the image.
    if chars == 0 or (chars < 8 and lines <= 1 and boxes <= 1):
        return "image_led"
    if chars >= 80 or lines >= 6 or boxes >= 10:
        return "text_heavy"
    return "title_led"


def pick_sample(n: int, seed: int) -> list[dict]:
    paths = load_paths()
    meta = load_meta()
    ocr_map = load_ocr_map()
    buckets: dict[str, list[dict]] = {
        "image_led": [],
        "title_led": [],
        "text_heavy": [],
    }
    for pid, ocr in ocr_map.items():
        if pid not in paths:
            continue
        m = meta.get(pid, {})
        year = m.get("year") or ""
        try:
            decade = (int(year) // 10) * 10 if year not in ("", None) else 0
        except Exception:
            decade = 0
        bucket = proxy_bucket(ocr)
        buckets[bucket].append(
            {
                "id": pid,
                "title": m.get("title") or f"id {pid}",
                "year": year,
                "decade": decade,
                "proxy": bucket,
                "ocr_chars": ocr["ocr_chars"],
                "n_lines": ocr["n_lines"],
                "n_boxes": ocr["n_boxes"],
                "mean_conf": ocr["mean_conf"],
                "ocr_preview": ocr["ocr_preview"],
                "ocr_source": ocr["ocr_source"],
                "path": paths[pid],
                "img": IMG + paths[pid],
            }
        )

    rng = random.Random(seed)
    # Within each bucket: shuffle, then soft decade spread (take round-robin by decade)
    for k in buckets:
        by_dec: dict[int, list] = {}
        for c in buckets[k]:
            by_dec.setdefault(c["decade"], []).append(c)
        for d in by_dec:
            rng.shuffle(by_dec[d])
        ordered: list[dict] = []
        decs = sorted(by_dec.keys())
        while any(by_dec[d] for d in decs):
            for d in decs:
                if by_dec[d]:
                    ordered.append(by_dec[d].pop())
        buckets[k] = ordered

    # ~equal thirds
    n_each = max(1, n // 3)
    rem = n - 3 * n_each
    targets = {
        "image_led": n_each + (1 if rem > 0 else 0),
        "title_led": n_each + (1 if rem > 1 else 0),
        "text_heavy": n_each,
    }
    picked: list[dict] = []
    for k, want in targets.items():
        picked.extend(buckets[k][:want])
    if len(picked) < n:
        used = {x["id"] for x in picked}
        rest = []
        for k in ("text_heavy", "title_led", "image_led"):
            rest.extend(c for c in buckets[k] if c["id"] not in used)
        picked.extend(rest[: n - len(picked)])

    rng.shuffle(picked)
    return picked[:n]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=250)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    if not OCR.exists():
        raise SystemExit(f"missing {OCR}")

    rows = pick_sample(args.n, args.seed)
    print(
        f"sample n={len(rows)} by_proxy={dict(Counter(r['proxy'] for r in rows))}",
        flush=True,
    )

    DATA.joinpath("qa").mkdir(parents=True, exist_ok=True)
    with OUT_IDS.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "id",
                "title",
                "year",
                "decade",
                "proxy",
                "ocr_chars",
                "n_lines",
                "n_boxes",
                "mean_conf",
                "ocr_source",
                "path",
            ],
        )
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in w.fieldnames})

    if not OUT_LABELS.exists():
        OUT_LABELS.write_text(
            json.dumps(
                {
                    "updated_at": None,
                    "n_labels": 0,
                    "verdicts": {},
                    "note": "typography QA r1 — image_led / title_led / text_heavy",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"stub {OUT_LABELS}", flush=True)

    # Drop heavy preview from HTML payload? Keep short preview for labeler hint.
    payload_rows = []
    for r in rows:
        payload_rows.append(
            {
                "id": r["id"],
                "title": r["title"],
                "year": r["year"],
                "proxy": r["proxy"],
                "ocr_chars": r["ocr_chars"],
                "n_lines": r["n_lines"],
                "n_boxes": r["n_boxes"],
                "mean_conf": r["mean_conf"],
                "ocr_preview": r["ocr_preview"],
                "ocr_source": r["ocr_source"],
                "path": r["path"],
                "img": r["img"],
            }
        )
    payload = json.dumps(payload_rows, ensure_ascii=False, separators=(",", ":"))
    html = HTML_TEMPLATE.replace("__N__", str(len(rows))).replace("__DATA__", payload)
    OUT_SITE.parent.mkdir(parents=True, exist_ok=True)
    OUT_QA.parent.mkdir(parents=True, exist_ok=True)
    OUT_SITE.write_text(html, encoding="utf-8")
    OUT_QA.write_text(html, encoding="utf-8")
    print(f"wrote {OUT_SITE}", flush=True)
    print(f"wrote {OUT_QA}", flush=True)
    print(f"wrote {OUT_IDS}", flush=True)
    return 0


HTML_TEMPLATE = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Label QA · tipografía (__N__)</title>
<style>
:root{--bg:#0a0a0c;--bg2:#141416;--ink:#e8e4da;--dim:#9a958a;--line:#2a2a30;
  --blood:#c1121f;--ok:#3d9a6a;--img:#6a8f71;--title:#c9a227;--heavy:#c45c7a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"Source Serif 4",Georgia,serif;min-height:100vh}
.wrap{max-width:980px;margin:0 auto;padding:20px 20px 80px}
.top{display:flex;flex-wrap:wrap;gap:12px 20px;align-items:baseline;
  border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:18px}
h1{font-family:"Anton",Impact,sans-serif;font-size:26px;letter-spacing:.02em;
  margin:0;font-weight:400}
.meta{color:var(--dim);font-size:14px}
.progress{flex:1;min-width:160px;height:6px;background:var(--line);border-radius:3px;overflow:hidden}
.progress>i{display:block;height:100%;width:0;background:var(--blood);transition:width .15s}
.filter{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px}
.filter button{background:var(--bg2);border:1px solid var(--line);color:var(--dim);
  padding:6px 10px;border-radius:4px;cursor:pointer;font:inherit;font-size:13px}
.filter button.on{border-color:var(--ink);color:var(--ink)}
.stage{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(280px,.9fr);gap:20px}
@media(max-width:800px){.stage{grid-template-columns:1fr}}
.poster{width:100%;max-height:72vh;object-fit:contain;background:#000;border:1px solid var(--line)}
.panel h2{font-size:22px;margin:0 0 6px;font-family:"Anton",Impact,sans-serif;font-weight:400}
.year{color:var(--dim);font-size:14px;margin-bottom:10px}
.badge{display:inline-block;padding:2px 8px;border-radius:3px;font-size:12px;margin:0 4px 6px 0;
  border:1px solid var(--line);color:var(--dim)}
.badge.image_led{color:#b8d4be;border-color:var(--img)}
.badge.title_led{color:#e8d48a;border-color:var(--title)}
.badge.text_heavy{color:#f0b8c8;border-color:var(--heavy)}
.hint{color:var(--dim);font-size:14px;line-height:1.45}
.ocrbox{margin:10px 0;padding:10px;background:#0e0e10;border:1px solid var(--line);
  border-radius:4px;font-size:12px;color:var(--dim);line-height:1.4;max-height:7.5em;overflow:auto}
.ocrbox b{color:var(--ink)}
.actions{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}
.actions button{border:1px solid var(--line);background:var(--bg2);color:var(--ink);
  padding:10px 12px;border-radius:4px;cursor:pointer;font:inherit;font-size:14px}
.actions button.image_led{border-color:var(--img)}
.actions button.title_led{border-color:var(--title)}
.actions button.text_heavy{border-color:var(--heavy)}
.actions button.is-selected{outline:2px solid var(--ink)}
.actions button.nav{color:var(--dim)}
.mine{margin-top:8px;padding:10px;background:var(--bg2);border:1px solid var(--line);border-radius:4px}
.mine.marked{border-color:var(--ok)}
.keys{color:var(--dim);font-size:12px}
kbd{border:1px solid var(--line);padding:1px 5px;border-radius:3px;font-size:11px}
.toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:22px;
  padding-top:14px;border-top:1px solid var(--line)}
.toolbar button{background:var(--bg2);border:1px solid var(--line);color:var(--ink);
  padding:8px 12px;border-radius:4px;cursor:pointer;font:inherit;font-size:13px}
.status{color:var(--dim);font-size:13px}
.cloud{margin-top:22px;padding:16px;border:1px solid var(--line);border-radius:6px;background:var(--bg2)}
.cloud h3{margin:0 0 8px;font-size:16px;font-family:"Anton",Impact,sans-serif;font-weight:400}
.hint2{color:var(--dim);font-size:13px;line-height:1.4;margin:0 0 12px}
.cloud .row{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:8px}
.cloud input{flex:1;min-width:220px;background:#0e0e10;border:1px solid var(--line);
  color:var(--ink);padding:8px 10px;border-radius:4px;font:inherit}
.cloud button{background:#1a1a1e;border:1px solid var(--line);color:var(--ink);
  padding:8px 12px;border-radius:4px;cursor:pointer;font:inherit;font-size:13px}
.msg{font-size:13px;min-height:1.2em;color:var(--dim)}
.msg.ok{color:var(--ok)}
.msg.err{color:#e07070}
.score{font-size:13px;color:var(--dim);margin:8px 0}
</style>
<link href="https://fonts.googleapis.com/css2?family=Anton&family=Source+Serif+4:wght@400;600&display=swap" rel="stylesheet">
</head>
<body>
<div class="wrap">
  <div class="top">
    <h1>Tipografía · ronda 1</h1>
    <span class="meta" id="counter">0 / __N__</span>
    <div class="progress" aria-hidden="true"><i id="bar"></i></div>
  </div>
  <div class="filter" id="filters">
    <button type="button" data-f="all" class="on">all</button>
    <button type="button" data-f="todo">sin marcar</button>
    <button type="button" data-f="done">marcados</button>
    <button type="button" data-f="proxy_image_led">proxy image</button>
    <button type="button" data-f="proxy_title_led">proxy title</button>
    <button type="button" data-f="proxy_text_heavy">proxy heavy</button>
    <button type="button" data-f="lab_image_led">→ image_led</button>
    <button type="button" data-f="lab_title_led">→ title_led</button>
    <button type="button" data-f="lab_text_heavy">→ text_heavy</button>
    <button type="button" data-f="lab_doubtful">→ doubtful</button>
  </div>
  <div class="stage">
    <img class="poster" id="poster" alt="">
    <div class="panel">
      <h2 id="title">—</h2>
      <div class="year" id="year">—</div>
      <div>
        <span class="badge" id="proxyBadge">—</span>
      </div>
      <div class="score" id="score">—</div>
      <p class="hint"><b>image_led</b> = manda la imagen; poco o nada de lettering útil ·
        <b>title_led</b> = título grande dominante (créditos chicos OK) ·
        <b>text_heavy</b> = mucho copy: quotes, credits, taglines, tipografía densa ·
        <b>doubtful</b> si no estás seguro. Juzgá el póster; el OCR es solo pista.</p>
      <div class="ocrbox" id="ocrbox">—</div>
      <div class="actions">
        <button type="button" class="image_led" data-pick="image_led" title="1">1 · image_led</button>
        <button type="button" class="title_led" data-pick="title_led" title="2">2 · title_led</button>
        <button type="button" class="text_heavy" data-pick="text_heavy" title="3">3 · text_heavy</button>
        <button type="button" data-pick="doubtful" title="4">4 · doubtful</button>
        <button type="button" class="nav" id="btnPrev" title="←">← Prev</button>
        <button type="button" class="nav" id="btnNext" title="→">Next →</button>
      </div>
      <div class="mine" id="mine">Tu etiqueta: <b>—</b></div>
      <p class="keys">Atajos: <kbd>1</kbd>–<kbd>4</kbd> · <kbd>←</kbd><kbd>→</kbd>/<kbd>Enter</kbd>/<kbd>Space</kbd> · <kbd>U</kbd> limpiar</p>
    </div>
  </div>
  <div class="toolbar">
    <button type="button" id="btnExport">Exportar CSV</button>
    <button type="button" id="btnClear">Borrar progreso local</button>
    <span class="status" id="status"></span>
  </div>
  <div class="cloud">
    <h3>Guardar en el repo (GitHub)</h3>
    <p class="hint2">PAT fine-grained con <b>Contents: Read and write</b> en
      <code>juanpduque/what-fear-looks-like</code>. Token solo en este navegador.
      Archivo: <code>pipeline/data/qa/typography_qa_r1_labels.json</code>.
      Varias personas: cada una hace <b>Cargar</b> al empezar y <b>Guardar</b> al terminar (merge por timestamp).</p>
    <div class="row">
      <input type="password" id="ghToken" placeholder="GitHub PAT (solo local)" autocomplete="off">
      <button type="button" id="btnSaveToken">Recordar token</button>
      <button type="button" id="btnClearToken">Olvidar token</button>
    </div>
    <div class="row">
      <button type="button" id="btnPushGh">⬆ Guardar en GitHub</button>
      <button type="button" id="btnPullGh">⬇ Cargar desde GitHub</button>
    </div>
    <div class="msg" id="ghMsg"></div>
  </div>
</div>
<script>
const DATA = __DATA__;
const STORE = "aof-label-qa-typography-r1-v1";
const TOKEN_STORE = "aof-typography-qa-r1-gh-token";
const GH_REPO = "juanpduque/what-fear-looks-like";
const GH_PATH = "pipeline/data/qa/typography_qa_r1_labels.json";
const GH_BRANCH = "main";
const LABELS = ["image_led","title_led","text_heavy","doubtful"];
let filter = "all";
let idx = 0;
let verdicts = {};

function normalizeEntry(v){
  if(!v || typeof v !== "object") return null;
  const lab = (v.label || "").trim();
  if(!LABELS.includes(lab)) return null;
  return {
    id: v.id, title: v.title, year: v.year,
    label: lab, proxy: v.proxy || "",
    ocr_chars: v.ocr_chars, n_lines: v.n_lines,
    ts: v.ts || Date.now()
  };
}
function loadVerdicts(){
  let raw = {};
  try { raw = JSON.parse(localStorage.getItem(STORE) || "{}") || {}; } catch(e){ raw = {}; }
  const out = {};
  Object.keys(raw).forEach(id => {
    const n = normalizeEntry(raw[id]);
    if(n) out[id] = n;
  });
  return out;
}
verdicts = loadVerdicts();
try { localStorage.setItem(STORE, JSON.stringify(verdicts)); } catch(e){}
try { window.__ghTokenInit = localStorage.getItem(TOKEN_STORE) || ""; } catch(e){}

function save(){ localStorage.setItem(STORE, JSON.stringify(verdicts)); updateStatus(); }

function filtered(){
  return DATA.filter(d => {
    const v = verdicts[d.id];
    if(filter==="todo") return !v;
    if(filter==="done") return !!v;
    if(filter==="proxy_image_led") return d.proxy==="image_led";
    if(filter==="proxy_title_led") return d.proxy==="title_led";
    if(filter==="proxy_text_heavy") return d.proxy==="text_heavy";
    if(filter==="lab_image_led") return v && v.label==="image_led";
    if(filter==="lab_title_led") return v && v.label==="title_led";
    if(filter==="lab_text_heavy") return v && v.label==="text_heavy";
    if(filter==="lab_doubtful") return v && v.label==="doubtful";
    return true;
  });
}

function show(){
  const list = filtered();
  const img = document.getElementById("poster");
  if(!list.length){
    document.getElementById("title").textContent = "No hay casos en este filtro";
    img.removeAttribute("src");
    document.getElementById("mine").innerHTML = "Tu etiqueta: <b>—</b>";
    document.getElementById("ocrbox").textContent = "—";
    return;
  }
  if(idx >= list.length) idx = list.length - 1;
  if(idx < 0) idx = 0;
  const d = list[idx];
  img.onerror = () => { img.alt = "sin imagen"; };
  img.src = d.img || ("https://image.tmdb.org/t/p/w500" + (d.path||""));
  img.alt = d.title;
  document.getElementById("title").textContent = d.title;
  const y = d.year===9999 || d.year==="" ? "sin año" : d.year;
  document.getElementById("year").innerHTML =
    y + " · id " + d.id +
    ' · <a href="https://www.themoviedb.org/movie/'+d.id+'" target="_blank" rel="noopener">TMDB</a>';
  const pb = document.getElementById("proxyBadge");
  pb.textContent = "proxy OCR: " + d.proxy;
  pb.className = "badge " + d.proxy;
  document.getElementById("score").textContent =
    "chars " + d.ocr_chars +
    " · lines " + d.n_lines +
    " · boxes " + d.n_boxes +
    " · conf " + Number(d.mean_conf||0).toFixed(2) +
    " · " + (d.ocr_source || "ocr");
  const prev = (d.ocr_preview || "").trim();
  document.getElementById("ocrbox").innerHTML = prev
    ? "<b>OCR hint:</b> " + prev.replace(/</g,"&lt;")
    : "<b>OCR hint:</b> (vacío)";
  document.querySelectorAll(".actions button[data-pick]").forEach(b => b.classList.remove("is-selected"));
  const v = verdicts[d.id];
  const mine = document.getElementById("mine");
  if(!v){
    mine.className = "mine";
    mine.innerHTML = "Tu etiqueta: <b>sin marcar</b>";
  } else {
    mine.className = "mine marked";
    mine.innerHTML = "Tu etiqueta: <b>" + v.label + "</b>";
    const pick = document.querySelector('.actions button[data-pick="'+v.label+'"]');
    if(pick) pick.classList.add("is-selected");
  }
  document.getElementById("counter").textContent =
    (idx+1) + " / " + list.length + "  (set " + DATA.length + ")";
  const done = DATA.filter(x => verdicts[x.id]).length;
  document.getElementById("bar").style.width = (100 * done / DATA.length) + "%";
  updateStatus();
}

function setLabel(lab){
  const list = filtered();
  if(!list.length || !LABELS.includes(lab)) return;
  const d = list[idx];
  verdicts[d.id] = {
    id: d.id, title: d.title, year: d.year,
    label: lab, proxy: d.proxy,
    ocr_chars: d.ocr_chars, n_lines: d.n_lines,
    ts: Date.now()
  };
  save();
  if(idx < list.length - 1) idx++;
  show();
}
function undo(){
  const list = filtered();
  if(!list.length) return;
  delete verdicts[list[idx].id];
  save(); show();
}
function updateStatus(){
  const counts = {image_led:0, title_led:0, text_heavy:0, doubtful:0};
  let done = 0;
  DATA.forEach(d => {
    const v = verdicts[d.id];
    if(!v) return;
    done++;
    if(counts[v.label]!=null) counts[v.label]++;
  });
  document.getElementById("status").textContent =
    "marcados " + done + "/" + DATA.length +
    " · image " + counts.image_led +
    " · title " + counts.title_led +
    " · heavy " + counts.text_heavy +
    " · doubt " + counts.doubtful;
}
function toCSV(rows){
  const cols = ["id","title","year","label","proxy","ocr_chars","n_lines","ts"];
  const esc = v => {
    const s = String(v==null?"":v);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g,'""') + '"' : s;
  };
  return cols.join(",") + "\n" + rows.map(r => cols.map(c => esc(r[c])).join(",")).join("\n");
}
function download(name, text){
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], {type:"text/csv"}));
  a.download = name; a.click(); URL.revokeObjectURL(a.href);
}
function ghMsg(text, ok){
  const el = document.getElementById("ghMsg");
  el.textContent = text || "";
  el.className = "msg " + (ok===true ? "ok" : ok===false ? "err" : "");
}
function getToken(){ return (document.getElementById("ghToken").value || "").trim(); }
function utf8ToB64(str){ return btoa(unescape(encodeURIComponent(str))); }
function b64ToUtf8(str){ return decodeURIComponent(escape(atob(str))); }
function mergeVerdicts(remote, local){
  const out = {};
  const ids = new Set([...Object.keys(remote||{}), ...Object.keys(local||{})]);
  ids.forEach(id => {
    const a = normalizeEntry((remote||{})[id]);
    const b = normalizeEntry((local||{})[id]);
    if(!a && !b) return;
    if(!a){ out[id]=b; return; }
    if(!b){ out[id]=a; return; }
    out[id] = ((b.ts||0) >= (a.ts||0)) ? b : a;
  });
  return out;
}
async function ghGetFile(token){
  const url = "https://api.github.com/repos/" + GH_REPO + "/contents/" + GH_PATH + "?ref=" + GH_BRANCH;
  const r = await fetch(url, {
    headers: {
      "Accept": "application/vnd.github+json",
      "Authorization": "Bearer " + token,
      "X-GitHub-Api-Version": "2022-11-28"
    }
  });
  if(r.status === 404) return { exists:false, sha:null, verdicts:{} };
  if(!r.ok) throw new Error("GET " + r.status + " " + (await r.text()).slice(0,180));
  const j = await r.json();
  let parsed = {};
  try {
    const data = JSON.parse(b64ToUtf8(j.content.replace(/\n/g,"")));
    parsed = data.verdicts || data || {};
  } catch(e){ parsed = {}; }
  return { exists:true, sha:j.sha, verdicts:parsed };
}
async function pushToGitHub(){
  const token = getToken();
  if(!token){ ghMsg("Pegá un PAT primero.", false); return; }
  ghMsg("Guardando…");
  try {
    const remote = await ghGetFile(token);
    const merged = mergeVerdicts(remote.verdicts, verdicts);
    const n = Object.keys(merged).length;
    const bodyObj = { updated_at: new Date().toISOString(), n_labels: n, verdicts: merged };
    const payload = {
      message: "chore(qa): update typography QA r1 labels (" + n + ")",
      content: utf8ToB64(JSON.stringify(bodyObj, null, 2) + "\n"),
      branch: GH_BRANCH
    };
    if(remote.sha) payload.sha = remote.sha;
    const r = await fetch("https://api.github.com/repos/" + GH_REPO + "/contents/" + GH_PATH, {
      method: "PUT",
      headers: {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });
    if(!r.ok) throw new Error("PUT " + r.status + " " + (await r.text()).slice(0,220));
    verdicts = {};
    Object.keys(merged).forEach(id => { const n = normalizeEntry(merged[id]); if(n) verdicts[id]=n; });
    save(); show();
    ghMsg("Guardado en GitHub · " + n + " labels → " + GH_PATH, true);
  } catch(e){ ghMsg(String(e.message || e), false); }
}
async function pullFromGitHub(){
  const token = getToken();
  if(!token){ ghMsg("Pegá un PAT primero.", false); return; }
  ghMsg("Cargando…");
  try {
    const remote = await ghGetFile(token);
    const merged = mergeVerdicts(remote.verdicts, verdicts);
    verdicts = {};
    Object.keys(merged).forEach(id => { const n = normalizeEntry(merged[id]); if(n) verdicts[id]=n; });
    save(); show();
    ghMsg("Cargado · " + Object.keys(verdicts).length + " labels", true);
  } catch(e){ ghMsg(String(e.message || e), false); }
}

document.querySelectorAll(".actions button[data-pick]").forEach(b => {
  b.onclick = () => setLabel(b.dataset.pick);
});
document.getElementById("btnPrev").onclick = () => { idx--; show(); };
document.getElementById("btnNext").onclick = () => { idx++; show(); };
document.getElementById("btnExport").onclick = () => {
  const rows = Object.values(verdicts);
  if(!rows.length){ alert("Aún no hay etiquetas"); return; }
  download("typography_qa_r1_labels.csv", toCSV(rows));
};
document.getElementById("btnClear").onclick = () => {
  if(confirm("¿Borrar el progreso local de tipografía r1 en este navegador?")){
    verdicts = {}; save(); idx = 0; show();
  }
};
document.getElementById("filters").onclick = (e) => {
  const b = e.target.closest("button[data-f]");
  if(!b) return;
  filter = b.dataset.f;
  document.querySelectorAll("#filters button").forEach(x => x.classList.toggle("on", x===b));
  idx = 0; show();
};
document.getElementById("btnSaveToken").onclick = () => {
  const t = getToken();
  localStorage.setItem(TOKEN_STORE, t);
  ghMsg(t ? "Token recordado en este navegador." : "Token vacío.", !!t);
};
document.getElementById("btnClearToken").onclick = () => {
  localStorage.removeItem(TOKEN_STORE);
  document.getElementById("ghToken").value = "";
  ghMsg("Token olvidado.", true);
};
document.getElementById("btnPushGh").onclick = pushToGitHub;
document.getElementById("btnPullGh").onclick = pullFromGitHub;
document.addEventListener("keydown", (e) => {
  if(e.target.matches("input,textarea")) return;
  if(e.key==="1") setLabel("image_led");
  else if(e.key==="2") setLabel("title_led");
  else if(e.key==="3") setLabel("text_heavy");
  else if(e.key==="4") setLabel("doubtful");
  else if(e.key==="ArrowLeft"){ idx--; show(); }
  else if(e.key==="ArrowRight" || e.key==="Enter" || e.key===" "){ e.preventDefault(); idx++; show(); }
  else if(e.key==="u" || e.key==="U") undo();
});
if(window.__ghTokenInit) document.getElementById("ghToken").value = window.__ghTokenInit;
show();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
