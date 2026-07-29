#!/usr/bin/env python3
"""Build QA UI to mark corpus-filter exclusions on the ~20.6k set.

Set = EN + adult=false + runtime≥40 + has IMDb − IMDb isAdult − OCR other_lang
     − exact poster MD5 dups (keep one per group)
     − TMDB genres Comedy / Music / Animation
     − TV horror (TMDB TV Movie ∪ IMDb tvMovie/tvEpisode/…)
     − titles without a remote TMDB poster_path (listed in corpus_filter_no_poster.csv)
     − align to current TMDB primary poster (override drift; drop null primary).

Labels (toggle, multi): other_lang | exclude_adult | exclude_quality

  python3 build_corpus_filter_qa.py
  open ../site/corpus-filter-qa.html
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
QA = DATA / "qa"
OUT = ROOT.parent / "site" / "corpus-filter-qa.html"
IMG = "https://image.tmdb.org/t/p/w500"

PAIRS = QA / "tmdb_en_horror_ge40_imdb_pairs.csv"
ADULT = QA / "ge40_imdb_isAdult.csv"
OCR_LABELS = QA / "ocr_title_review_labels.json"
MD5_DUP = DATA / "excluded_poster_md5_dup.csv"
EX_COMEDY = QA / "corpus_filter_excluded_comedy.csv"
EX_MUSIC = QA / "corpus_filter_excluded_music.csv"
EX_ANIM = QA / "corpus_filter_excluded_animation.csv"
EX_TV = QA / "corpus_filter_excluded_tv.csv"
PRIMARY_OVR = QA / "corpus_filter_poster_primary_override.csv"
DROP_NO_PRIMARY = QA / "corpus_filter_drop_no_primary_poster.csv"
SET_OUT = QA / "corpus_filter_qa_ids.csv"


def load_paths() -> dict[int, str]:
    paths: dict[int, str] = {}
    hm = DATA / "horror_movies.csv"
    if hm.exists():
        with hm.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                p = (r.get("poster_path") or "").strip()
                if p.startswith("/"):
                    paths[pid] = p
    bf = DATA / "poster_paths_backfill.csv"
    if bf.exists():
        with bf.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                if pid in paths:
                    continue
                p = (r.get("poster_path") or "").strip()
                if p.startswith("/"):
                    paths[pid] = p
    # Force current TMDB primary when we detected drift
    if PRIMARY_OVR.exists():
        with PRIMARY_OVR.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                p = (r.get("primary_path") or "").strip()
                if p.startswith("/"):
                    paths[pid] = p
    return paths


def load_meta() -> dict[int, dict]:
    meta: dict[int, dict] = {}
    hm = DATA / "horror_movies.csv"
    if not hm.exists():
        return meta
    with hm.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (KeyError, TypeError, ValueError):
                continue
            year = 9999
            rd = (r.get("release_date") or "").strip()
            if len(rd) >= 4 and rd[:4].isdigit():
                year = int(rd[:4])
            try:
                votes = float(r.get("vote_count") or 0)
            except (TypeError, ValueError):
                votes = 0.0
            meta[pid] = {
                "title": (r.get("title") or r.get("original_title") or "").strip()
                or f"id {pid}",
                "year": year,
                "vote_count": votes,
                "imdb_id": (r.get("imdb_id") or "").strip(),
            }
    return meta


def ocr_other_lang_ids() -> set[int]:
    out: set[int] = set()
    if not OCR_LABELS.exists():
        return out
    data = json.loads(OCR_LABELS.read_text(encoding="utf-8"))
    verdicts = data.get("verdicts") or data
    for k, v in verdicts.items():
        try:
            pid = int(k)
        except (TypeError, ValueError):
            continue
        labs = []
        if isinstance(v, dict):
            labs = v.get("labels") or ([v["label"]] if v.get("label") else [])
        if "other_lang" in labs:
            out.add(pid)
    return out


def load_id_set(path: Path, col: str = "id") -> set[int]:
    out: set[int] = set()
    if not path.exists():
        return out
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                out.add(int(r[col]))
            except (KeyError, TypeError, ValueError):
                continue
    return out


def build_ids() -> list[dict]:
    if not PAIRS.exists():
        raise SystemExit(f"falta {PAIRS} — regenerá el set ge40+imdb primero")

    adult = load_id_set(ADULT)
    skip_lang = ocr_other_lang_ids()
    skip_md5 = load_id_set(MD5_DUP)
    skip_comedy = load_id_set(EX_COMEDY)
    skip_music = load_id_set(EX_MUSIC)
    skip_anim = load_id_set(EX_ANIM)
    skip_tv = load_id_set(EX_TV)
    skip_no_primary = load_id_set(DROP_NO_PRIMARY)
    skip = (
        adult
        | skip_lang
        | skip_md5
        | skip_comedy
        | skip_music
        | skip_anim
        | skip_tv
        | skip_no_primary
    )
    pairs: list[tuple[int, str]] = []
    with PAIRS.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
                iid = (r.get("imdb_id") or "").strip()
            except (KeyError, TypeError, ValueError):
                continue
            if pid in skip:
                continue
            if not iid.startswith("tt"):
                continue
            # Also drop by live genre tags if CSV lists stale
            pairs.append((pid, iid))

    meta = load_meta()
    # Genre gate from horror_movies (Comedy / Music) even if CSV not regenerated
    genre_skip: set[int] = set()
    hm = DATA / "horror_movies.csv"
    if hm.exists():
        with hm.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                parts = {
                    x.strip()
                    for x in (r.get("genre_names") or "").split(",")
                    if x.strip()
                }
                if parts & {"Comedy", "Music", "Animation"}:
                    genre_skip.add(pid)
    pairs = [(pid, iid) for pid, iid in pairs if pid not in genre_skip]
    paths = load_paths()
    rows = []
    for pid, iid in pairs:
        m = meta.get(pid, {})
        title = m.get("title") or f"id {pid}"
        year = int(m.get("year") or 9999)
        votes = float(m.get("vote_count") or 0)
        imdb = m.get("imdb_id") or iid
        path = paths.get(pid, "")
        rows.append(
            {
                "id": pid,
                "title": title,
                "year": year,
                "vote_count": int(votes),
                "imdb_id": imdb,
                "img": (IMG + path) if path else "",
            }
        )

    # Low visibility first (donde más ruido), luego año, id
    rows.sort(key=lambda x: (x["vote_count"], x["year"], x["id"]))

    # GitHub Pages solo puede mostrar CDN remoto — sin poster_path no hay QA útil
    with_img = [r for r in rows if r["img"]]
    no_img = [r for r in rows if not r["img"]]
    no_out = QA / "corpus_filter_no_poster.csv"
    no_out.parent.mkdir(parents=True, exist_ok=True)
    with no_out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "title", "year", "vote_count", "imdb_id"])
        w.writeheader()
        for r in no_img:
            w.writerow(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "year": r["year"] if r["year"] != 9999 else "",
                    "vote_count": r["vote_count"],
                    "imdb_id": r["imdb_id"],
                }
            )
    print(
        f"poster gate: with_img={len(with_img):,} no_img={len(no_img):,} → {no_out.name}"
    )
    return with_img


def main() -> None:
    rows = build_ids()
    SET_OUT.parent.mkdir(parents=True, exist_ok=True)
    with SET_OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["id", "title", "year", "vote_count", "imdb_id"]
        )
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "year": r["year"] if r["year"] != 9999 else "",
                    "vote_count": r["vote_count"],
                    "imdb_id": r["imdb_id"],
                }
            )

    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).replace(
        "<", "\\u003c"
    )
    html = HTML.replace("__N__", f"{len(rows):,}").replace("__DATA__", payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    with_img = sum(1 for r in rows if r["img"])
    print(
        f"Wrote {OUT} ({len(rows):,} cases, with_img={with_img:,}, "
        f"ids→{SET_OUT})"
    )


HTML = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Corpus filter QA — __N__</title>
<style>
:root{--bg:#0a0a0c;--bg2:#141416;--ink:#e8e4da;--dim:#9a958a;--line:#2a2a30;
  --amber:#e5a00d}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"Source Serif 4",Georgia,serif;min-height:100vh}
.wrap{max-width:1040px;margin:0 auto;padding:20px 20px 90px}
.top{display:flex;flex-wrap:wrap;gap:12px 20px;align-items:baseline;
  border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:14px}
h1{font-family:"Anton",Impact,sans-serif;font-size:24px;letter-spacing:.02em;
  text-transform:uppercase;margin:0;font-weight:400}
.meta{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--dim)}
.progress{flex:1;min-width:160px;height:6px;background:#1a1a1e;border-radius:3px;overflow:hidden}
.progress i{display:block;height:100%;background:var(--amber);width:0%}
.filter{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
.filter button{font-family:ui-monospace,Menlo,monospace;font-size:11px;background:transparent;
  color:var(--dim);border:1px solid var(--line);border-radius:3px;padding:5px 8px;cursor:pointer}
.filter button.on{color:var(--amber);border-color:var(--amber)}
.stage{display:grid;grid-template-columns:minmax(0,340px) 1fr;gap:28px;align-items:start}
@media(max-width:760px){.stage{grid-template-columns:1fr}}
.poster-wrap{position:relative;width:100%}
.poster{width:100%;aspect-ratio:2/3;object-fit:cover;border-radius:4px;
  box-shadow:0 20px 50px rgba(0,0,0,.6);background:#1a1a1e;display:block}
.poster.missing{opacity:0}
.poster-fallback{display:none;position:absolute;inset:0;align-items:center;justify-content:center;
  text-align:center;padding:20px;border-radius:4px;background:#1a1a1e;border:1px dashed #333;
  font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--dim);line-height:1.5}
.poster-wrap.noimg .poster-fallback{display:flex}
.panel h2{font-family:"Anton",Impact,sans-serif;font-size:32px;line-height:1.05;
  text-transform:uppercase;margin:0 0 8px;font-weight:400}
.year{font-family:ui-monospace,Menlo,monospace;color:var(--amber);font-size:13px;margin-bottom:10px}
.year a{color:var(--amber)}
.votes{font-family:"Anton",Impact,sans-serif;font-size:22px;color:var(--amber);margin:0 0 12px}
.hint{color:var(--dim);font-size:14px;line-height:1.45;max-width:40em;margin:0 0 16px}
.hint b{color:var(--ink)}
.actions{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0}
.actions button{font-family:ui-monospace,Menlo,monospace;font-size:13px;letter-spacing:.03em;
  border:1px solid var(--line);background:var(--bg2);color:var(--ink);padding:12px 14px;
  border-radius:4px;cursor:pointer}
.actions button:hover{border-color:#555}
.actions button.otherlang{border-color:#30466a;color:#a8c4f0}
.actions button.exadult{border-color:#6a3060;color:#e8a0d4}
.actions button.exquality{border-color:#4a4a30;color:#c8c090}
.actions button.nav{opacity:.85}
.actions button.is-selected{outline:2px solid var(--amber);outline-offset:2px;font-weight:700}
.mine{margin-top:8px;padding:12px 14px;border:1px solid var(--line);border-radius:4px;
  font-family:ui-monospace,Menlo,monospace;font-size:13px;color:var(--dim)}
.mine.marked{border-color:rgba(229,160,13,.45);background:rgba(229,160,13,.08);color:var(--ink)}
.mine b{color:var(--amber);text-transform:uppercase}
.keys{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--dim);line-height:1.6;margin-top:12px}
kbd{background:#1a1a1e;border:1px solid #333;border-radius:3px;padding:1px 5px;color:var(--ink)}
.toolbar{display:flex;flex-wrap:wrap;gap:10px;margin-top:28px;padding-top:16px;border-top:1px solid var(--line)}
.toolbar button{font-family:ui-monospace,Menlo,monospace;font-size:12px;background:#1a1a1e;
  color:var(--ink);border:1px solid var(--line);border-radius:4px;padding:8px 12px;cursor:pointer}
.status{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--dim);margin-left:auto}
.cloud{margin-top:18px;padding:14px;border:1px solid var(--line);border-radius:4px;background:var(--bg2)}
.cloud h3{font-family:ui-monospace,Menlo,monospace;font-size:12px;letter-spacing:.06em;
  text-transform:uppercase;color:var(--amber);margin:0 0 10px;font-weight:600}
.cloud .row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:8px}
.cloud input[type=password],.cloud input[type=text]{
  flex:1;min-width:220px;background:#0a0a0c;border:1px solid var(--line);border-radius:3px;
  color:var(--ink);padding:8px 10px;font-family:ui-monospace,Menlo,monospace;font-size:12px}
.cloud .hint2{font-size:12px;color:var(--dim);line-height:1.45;margin:0}
.cloud .hint2 a{color:var(--amber)}
.cloud .msg{font-family:ui-monospace,Menlo,monospace;font-size:12px;margin-top:8px;min-height:1.2em}
.cloud .msg.ok{color:#8fd4ad}.cloud .msg.err{color:#f0a0a8}
</style>
<link href="https://fonts.googleapis.com/css2?family=Anton&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap" rel="stylesheet">
</head>
<body>
<div class="wrap">
  <div class="top">
    <h1>Corpus filter QA</h1>
    <span class="meta" id="counter">0 / __N__</span>
    <div class="progress" aria-hidden="true"><i id="bar"></i></div>
  </div>
  <div class="filter" id="filters">
    <button type="button" data-f="all" class="on">all</button>
    <button type="button" data-f="todo">sin marcar</button>
    <button type="button" data-f="done">marcados</button>
    <button type="button" data-f="other_lang">otro idioma</button>
    <button type="button" data-f="exclude_adult">adulto</button>
    <button type="button" data-f="exclude_quality">calidad</button>
  </div>
  <div class="stage">
    <div class="poster-wrap" id="posterWrap">
      <img class="poster" id="poster" alt="" referrerpolicy="no-referrer">
      <div class="poster-fallback" id="posterFallback">Sin imagen TMDB<br>para este id</div>
    </div>
    <div class="panel">
      <h2 id="title">—</h2>
      <div class="year" id="year">—</div>
      <div class="votes" id="votes">—</div>
      <p class="hint">Marcá si hay que <b>sacar</b> del set (toggle, varias a la vez):
        <b>otro idioma</b> · <b>adulto</b> · <b>calidad</b> (arte/póster no usable).
        Si está bien, dejala sin marcar y pasá a la siguiente.</p>
      <div class="actions">
        <button type="button" class="otherlang" data-pick="other_lang" title="1">1 · otro idioma</button>
        <button type="button" class="exadult" data-pick="exclude_adult" title="2">2 · adulto</button>
        <button type="button" class="exquality" data-pick="exclude_quality" title="3">3 · calidad</button>
        <button type="button" class="nav" id="btnPrev" title="←">← Prev</button>
        <button type="button" class="nav" id="btnNext" title="→ / Enter / Space">Next →</button>
      </div>
      <div class="mine" id="mine">Tu veredicto: <b>—</b></div>
      <p class="keys">Atajos: <kbd>1</kbd> idioma · <kbd>2</kbd> adulto · <kbd>3</kbd> calidad ·
        <kbd>←</kbd><kbd>→</kbd>/<kbd>Enter</kbd>/<kbd>Space</kbd> navegar · <kbd>U</kbd> limpiar</p>
    </div>
  </div>
  <div class="toolbar">
    <button type="button" id="btnExport">Exportar CSV (backup)</button>
    <button type="button" id="btnOtherLang">Exportar otro idioma</button>
    <button type="button" id="btnExAdult">Exportar adulto</button>
    <button type="button" id="btnExQuality">Exportar calidad</button>
    <button type="button" id="btnClear">Borrar progreso local</button>
    <span class="status" id="status"></span>
  </div>
  <div class="cloud">
    <h3>Guardar en el repo (GitHub)</h3>
    <p class="hint2">PAT fine-grained con <b>Contents: Read and write</b> en
      <code>juanpduque/what-fear-looks-like</code>. Token solo en este navegador.
      Archivo: <code>pipeline/data/qa/corpus_filter_qa_labels.json</code></p>
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
const STORE = "aof-corpus-filter-qa-v1";
const TOKEN_STORE = "aof-corpus-filter-qa-gh-token";
const GH_REPO = "juanpduque/what-fear-looks-like";
const GH_PATH = "pipeline/data/qa/corpus_filter_qa_labels.json";
const GH_BRANCH = "main";
const LABELS = ["other_lang","exclude_adult","exclude_quality"];
let filter = "all";
let idx = 0;
let verdicts = {};

function normalizeEntry(v){
  if(!v || typeof v !== "object") return null;
  let labels = Array.isArray(v.labels) ? v.labels.slice() : null;
  if(!labels) labels = v.label ? [v.label] : [];
  labels = LABELS.filter(x => labels.includes(x));
  return {
    id: v.id, title: v.title, year: v.year, vote_count: v.vote_count,
    imdb_id: v.imdb_id,
    labels: labels,
    label: labels.join("+") || "",
    ts: v.ts || Date.now()
  };
}

function loadVerdicts(){
  let raw = {};
  try { raw = JSON.parse(localStorage.getItem(STORE) || "{}") || {}; } catch(e){ raw = {}; }
  const out = {};
  Object.keys(raw).forEach(id => {
    const n = normalizeEntry(raw[id]);
    if(n && n.labels.length) out[id] = n;
  });
  return out;
}
verdicts = loadVerdicts();
try { localStorage.setItem(STORE, JSON.stringify(verdicts)); } catch(e){}
try { window.__ghTokenInit = localStorage.getItem(TOKEN_STORE) || ""; } catch(e){}

function save(){ localStorage.setItem(STORE, JSON.stringify(verdicts)); updateStatus(); }
function getLabels(v){ return v ? normalizeEntry(v).labels : []; }
function hasLabel(v, lab){ return getLabels(v).includes(lab); }

function filtered(){
  return DATA.filter(d => {
    const v = verdicts[d.id];
    if(filter==="todo") return !getLabels(v).length;
    if(filter==="done") return getLabels(v).length;
    if(LABELS.includes(filter)) return hasLabel(v, filter);
    return true;
  });
}

function show(){
  const list = filtered();
  const img = document.getElementById("poster");
  const wrap = document.getElementById("posterWrap");
  if(!list.length){
    document.getElementById("title").textContent = "No hay casos en este filtro";
    img.removeAttribute("src");
    wrap.classList.add("noimg");
    document.getElementById("mine").innerHTML = "Tu veredicto: <b>—</b>";
    document.getElementById("mine").className = "mine";
    return;
  }
  if(idx >= list.length) idx = list.length - 1;
  if(idx < 0) idx = 0;
  const d = list[idx];
  const src = d.img || "";
  img.onload = () => { wrap.classList.remove("noimg"); img.classList.remove("missing"); };
  img.onerror = () => { wrap.classList.add("noimg"); img.classList.add("missing"); };
  if(src){
    wrap.classList.remove("noimg");
    img.classList.remove("missing");
    img.src = src;
  } else {
    img.removeAttribute("src");
    wrap.classList.add("noimg");
    img.classList.add("missing");
  }
  img.alt = d.title;
  document.getElementById("title").textContent = d.title;
  const y = d.year===9999 ? "sin año" : d.year;
  const imdb = d.imdb_id
    ? ' · <a href="https://www.imdb.com/title/'+d.imdb_id+'/" target="_blank" rel="noopener">'+d.imdb_id+'</a>'
    : "";
  document.getElementById("year").innerHTML =
    y + " · id " + d.id +
    ' · <a href="https://www.themoviedb.org/movie/'+d.id+'" target="_blank" rel="noopener">TMDB</a>' +
    imdb;
  document.getElementById("votes").textContent = "TMDB votes " + (d.vote_count||0);
  document.querySelectorAll(".actions button[data-pick]").forEach(b => b.classList.remove("is-selected"));
  const labs = getLabels(verdicts[d.id]);
  const mine = document.getElementById("mine");
  if(!labs.length){
    mine.className = "mine";
    mine.innerHTML = "Tu veredicto: <b>sin marcar</b> (ok en el set)";
  } else {
    mine.className = "mine marked";
    mine.innerHTML = "Tu veredicto: <b>" + labs.join(" + ") + "</b>";
    labs.forEach(lab => {
      const pick = document.querySelector('.actions button[data-pick="'+lab+'"]');
      if(pick) pick.classList.add("is-selected");
    });
  }
  document.getElementById("counter").textContent =
    (idx+1) + " / " + list.length + "  (set " + DATA.length + ")";
  const done = DATA.filter(x => getLabels(verdicts[x.id]).length).length;
  document.getElementById("bar").style.width = (100 * done / DATA.length) + "%";
  updateStatus();
}

function toggleLabel(label){
  const list = filtered();
  if(!list.length || !LABELS.includes(label)) return;
  const d = list[idx];
  let next = getLabels(verdicts[d.id]).slice();
  if(next.includes(label)) next = next.filter(x => x !== label);
  else next.push(label);
  next = LABELS.filter(x => next.includes(x));
  if(!next.length) delete verdicts[d.id];
  else {
    verdicts[d.id] = {
      id: d.id, title: d.title, year: d.year, vote_count: d.vote_count,
      imdb_id: d.imdb_id, labels: next, label: next.join("+"), ts: Date.now()
    };
  }
  save();
  show();
}

function undo(){
  const list = filtered();
  if(!list.length) return;
  delete verdicts[list[idx].id];
  save();
  show();
}

function updateStatus(){
  const counts = {other_lang:0, exclude_adult:0, exclude_quality:0};
  let done = 0;
  DATA.forEach(d => {
    const labs = getLabels(verdicts[d.id]);
    if(!labs.length) return;
    done++;
    labs.forEach(lab => { if(counts[lab]!=null) counts[lab]++; });
  });
  document.getElementById("status").textContent =
    "marcados " + done + "/" + DATA.length +
    " · idioma " + counts.other_lang +
    " · adulto " + counts.exclude_adult +
    " · calidad " + counts.exclude_quality;
}

function download(name, text){
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], {type:"text/csv"}));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

function toCSV(rows){
  const cols = ["id","title","year","vote_count","imdb_id","labels","other_lang","exclude_adult","exclude_quality"];
  const esc = v => {
    const s = String(v==null?"":v);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g,'""') + '"' : s;
  };
  return cols.join(",") + "\n" + rows.map(r => {
    const labs = getLabels(r);
    const row = {
      id: r.id, title: r.title, year: r.year, vote_count: r.vote_count, imdb_id: r.imdb_id,
      labels: labs.join("|"),
      other_lang: labs.includes("other_lang") ? 1 : 0,
      exclude_adult: labs.includes("exclude_adult") ? 1 : 0,
      exclude_quality: labs.includes("exclude_quality") ? 1 : 0
    };
    return cols.map(c => esc(row[c])).join(",");
  }).join("\n");
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
    const labs = LABELS.filter(x => getLabels(a).includes(x) || getLabels(b).includes(x));
    const base = ((b.ts||0) >= (a.ts||0)) ? b : a;
    out[id] = Object.assign({}, base, {
      labels: labs, label: labs.join("+"), ts: Math.max(a.ts||0, b.ts||0)
    });
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
      message: "chore(qa): update corpus filter QA labels (" + n + ")",
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
    verdicts = merged;
    save();
    show();
    ghMsg("Guardado en GitHub · " + n + " labels → " + GH_PATH, true);
  } catch(e){ ghMsg(String(e.message || e), false); }
}

async function pullFromGitHub(){
  const token = getToken();
  if(!token){ ghMsg("Pegá un PAT primero.", false); return; }
  ghMsg("Cargando…");
  try {
    const remote = await ghGetFile(token);
    if(!remote.exists){ ghMsg("Aún no hay archivo en el repo. Guardá primero.", false); return; }
    const before = Object.keys(verdicts).length;
    verdicts = mergeVerdicts(verdicts, remote.verdicts);
    save();
    show();
    ghMsg("Cargado · local " + before + " → " + Object.keys(verdicts).length, true);
  } catch(e){ ghMsg(String(e.message || e), false); }
}

document.getElementById("filters").addEventListener("click", e => {
  const b = e.target.closest("button[data-f]");
  if(!b) return;
  filter = b.getAttribute("data-f");
  document.querySelectorAll("#filters button").forEach(x => x.classList.toggle("on", x===b));
  idx = 0;
  show();
});
document.querySelectorAll(".actions button[data-pick]").forEach(b => {
  b.addEventListener("click", () => toggleLabel(b.getAttribute("data-pick")));
});
document.getElementById("btnPrev").onclick = () => { idx--; show(); };
document.getElementById("btnNext").onclick = () => { idx++; show(); };
document.getElementById("btnExport").onclick = () => {
  download("corpus_filter_qa.csv", toCSV(DATA.map(d => verdicts[d.id]).filter(v => getLabels(v).length)));
};
document.getElementById("btnOtherLang").onclick = () => {
  download("corpus_filter_qa_other_lang.csv", toCSV(DATA.map(d => verdicts[d.id]).filter(v => hasLabel(v, "other_lang"))));
};
document.getElementById("btnExAdult").onclick = () => {
  download("corpus_filter_qa_exclude_adult.csv", toCSV(DATA.map(d => verdicts[d.id]).filter(v => hasLabel(v, "exclude_adult"))));
};
document.getElementById("btnExQuality").onclick = () => {
  download("corpus_filter_qa_exclude_quality.csv", toCSV(DATA.map(d => verdicts[d.id]).filter(v => hasLabel(v, "exclude_quality"))));
};
document.getElementById("btnClear").onclick = () => {
  if(!confirm("¿Borrar todo el progreso local de esta QA?")) return;
  verdicts = {}; save(); idx = 0; show();
};
document.getElementById("btnSaveToken").onclick = () => {
  const t = getToken();
  if(!t){ ghMsg("Token vacío.", false); return; }
  localStorage.setItem(TOKEN_STORE, t);
  ghMsg("Token guardado en este navegador.", true);
};
document.getElementById("btnClearToken").onclick = () => {
  localStorage.removeItem(TOKEN_STORE);
  document.getElementById("ghToken").value = "";
  ghMsg("Token olvidado.", true);
};
document.getElementById("btnPushGh").onclick = () => pushToGitHub();
document.getElementById("btnPullGh").onclick = () => pullFromGitHub();
document.addEventListener("keydown", e => {
  if(e.target && /input|textarea/i.test(e.target.tagName)) return;
  if(e.key==="1") toggleLabel("other_lang");
  else if(e.key==="2") toggleLabel("exclude_adult");
  else if(e.key==="3") toggleLabel("exclude_quality");
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
    main()
