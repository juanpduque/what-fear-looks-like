#!/usr/bin/env python3
"""Build manual cover-validation UI for OCR title mismatches.

Reads data/qa/poster_ocr_title_mismatch.csv (score < 0.65 vs TMDB title)
and writes site/ocr-title-review.html — local labeling with localStorage + CSV export.

  python3 build_ocr_title_review.py
  open ../site/ocr-title-review.html

Images use absolute TMDB CDN URLs (required for GitHub Pages). Missing paths
are backfilled via TMDB_API_KEY when available.
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SRC = DATA / "qa" / "poster_ocr_title_mismatch.csv"
OUT = ROOT.parent / "site" / "ocr-title-review.html"
IMG = "https://image.tmdb.org/t/p/w500"
TMDB_MOVIE = "https://api.themoviedb.org/3/movie/{pid}"


def load_paths() -> dict[int, str]:
    paths: dict[int, str] = {}
    hm = DATA / "horror_movies.csv"
    if hm.exists():
        for r in pd.read_csv(hm, usecols=lambda c: c in {"id", "poster_path"}).itertuples(
            index=False
        ):
            p = getattr(r, "poster_path", None)
            if isinstance(p, str) and p.startswith("/"):
                paths[int(r.id)] = p
    bf = DATA / "poster_paths_backfill.csv"
    if bf.exists():
        for r in pd.read_csv(bf).itertuples(index=False):
            try:
                pid = int(r.id)
            except (TypeError, ValueError, AttributeError):
                continue
            if pid in paths:
                continue
            p = getattr(r, "poster_path", None)
            if isinstance(p, str) and p.startswith("/"):
                paths[pid] = p
    return paths


def auth_kwargs(api_key: str) -> dict:
    key = (api_key or "").strip()
    if key.startswith("eyJ"):
        return {"headers": {"Authorization": f"Bearer {key}"}}
    return {"params": {"api_key": key}}


def fetch_poster_path(session: requests.Session, api_key: str, pid: int) -> str | None:
    url = TMDB_MOVIE.format(pid=pid)
    kwargs = auth_kwargs(api_key)
    for attempt in range(4):
        try:
            r = session.get(url, timeout=25, **kwargs)
        except requests.RequestException:
            time.sleep(0.4 * (attempt + 1))
            continue
        if r.status_code == 429:
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            time.sleep(0.3)
            continue
        p = (r.json() or {}).get("poster_path") or ""
        return p if isinstance(p, str) and p.startswith("/") else None
    return None


def backfill_paths(need: list[int], paths: dict[int, str]) -> int:
    api_key = (os.environ.get("TMDB_API_KEY") or "").strip()
    if not api_key or not need:
        return 0
    print(f"TMDB backfill for {len(need):,} missing poster_path…")
    filled = 0
    with requests.Session() as session:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = {
                pool.submit(fetch_poster_path, session, api_key, pid): pid for pid in need
            }
            for i, fut in enumerate(as_completed(futs), 1):
                pid = futs[fut]
                try:
                    p = fut.result()
                except Exception:
                    p = None
                if p:
                    paths[pid] = p
                    filled += 1
                if i % 50 == 0 or i == len(need):
                    print(f"  {i}/{len(need)} filled={filled}", flush=True)
    return filled


def main() -> None:
    if not SRC.exists():
        raise SystemExit(
            f"falta {SRC} — regenerá el mismatch CSV desde poster_ocr.csv primero"
        )
    df = pd.read_csv(SRC)
    need_cols = {"id", "title", "year", "score", "full_ocr"}
    missing = need_cols - set(df.columns)
    if missing:
        raise SystemExit(f"CSV sin columnas: {sorted(missing)}")

    paths = load_paths()
    ids = [int(x) for x in df["id"].tolist()]
    need = sorted({pid for pid in ids if pid not in paths})
    filled = backfill_paths(need, paths)

    rows = []
    miss_path = 0
    for r in df.itertuples(index=False):
        pid = int(r.id)
        path = paths.get(pid)
        if not path:
            miss_path += 1
        year = getattr(r, "year", None)
        try:
            year = int(float(year)) if year == year else 9999
        except (TypeError, ValueError):
            year = 9999
        ocr = str(getattr(r, "full_ocr", "") or "")[:280]
        conf = getattr(r, "mean_conf", None)
        try:
            conf = round(float(conf), 3) if conf == conf else None
        except (TypeError, ValueError):
            conf = None
        n_lines = getattr(r, "n_lines", 0)
        try:
            n_lines = int(float(n_lines))
        except (TypeError, ValueError):
            n_lines = 0
        rows.append(
            {
                "id": pid,
                "title": str(r.title),
                "year": year,
                "score": round(float(r.score), 3),
                "n_lines": n_lines,
                "mean_conf": conf,
                "ocr": ocr,
                # Absolute CDN URL only — relative local JPGs break on GitHub Pages
                "img": (IMG + path) if path else "",
            }
        )

    # Prefer rows with images; within that, worst score first
    rows.sort(key=lambda x: (0 if x["img"] else 1, x["score"], x["year"], x["id"]))
    # Escape < so OCR never breaks </script> embedding
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).replace(
        "<", "\\u003c"
    )
    html = HTML.replace("__N__", str(len(rows))).replace("__DATA__", payload)
    OUT.write_text(html, encoding="utf-8")
    print(
        f"Wrote {OUT} ({len(rows):,} cases, with_img={len(rows) - miss_path:,}, "
        f"no_img={miss_path:,}, tmdb_filled={filled:,})"
    )


HTML = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>OCR title QA — portadas (__N__)</title>
<style>
:root{--bg:#0a0a0c;--bg2:#141416;--ink:#e8e4da;--dim:#9a958a;--line:#2a2a30;
  --amber:#e5a00d;--ok:#3d9a6a;--bad:#c1121f;--mid:#c4a35a}
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
.score{font-size:26px;font-family:"Anton",Impact,sans-serif;color:var(--amber);margin:0 0 10px}
.ocr-box{margin:0 0 14px;padding:12px 14px;border:1px solid var(--line);border-radius:4px;
  background:var(--bg2);font-family:ui-monospace,Menlo,monospace;font-size:12px;
  line-height:1.45;color:#c8c2b6;max-height:9.5em;overflow:auto;white-space:pre-wrap;word-break:break-word}
.ocr-box b{color:var(--amber);display:block;margin-bottom:6px;font-size:10px;
  letter-spacing:.08em;text-transform:uppercase}
.hint{color:var(--dim);font-size:14px;line-height:1.45;max-width:40em;margin:0 0 16px}
.hint b{color:var(--ink)}
.actions{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0}
.actions button{font-family:ui-monospace,Menlo,monospace;font-size:13px;letter-spacing:.03em;
  border:1px solid var(--line);background:var(--bg2);color:var(--ink);padding:12px 14px;
  border-radius:4px;cursor:pointer}
.actions button:hover{border-color:#555}
.actions button.ok{border-color:#2d6a4a;color:#8fd4ad}
.actions button.wrong{border-color:#7a1a22;color:#f0a0a8}
.actions button.notitle{border-color:#6a5630;color:#e5c97a}
.actions button.otherlang{border-color:#30466a;color:#a8c4f0}
.actions button.unsure{border-color:#555;color:var(--dim)}
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
    <h1>Portada · OCR vs título</h1>
    <span class="meta" id="counter">0 / __N__</span>
    <div class="progress" aria-hidden="true"><i id="bar"></i></div>
  </div>
  <div class="filter" id="filters">
    <button type="button" data-f="all" class="on">all</button>
    <button type="button" data-f="todo">sin marcar</button>
    <button type="button" data-f="done">marcados</button>
    <button type="button" data-f="ok">ok</button>
    <button type="button" data-f="wrong">wrong</button>
    <button type="button" data-f="no_title">no_title</button>
    <button type="button" data-f="other_lang">other_lang</button>
    <button type="button" data-f="unsure">unsure</button>
    <button type="button" data-f="low">score&lt;0.3</button>
  </div>
  <div class="stage">
    <div class="poster-wrap" id="posterWrap">
      <img class="poster" id="poster" alt="" referrerpolicy="no-referrer">
      <div class="poster-fallback" id="posterFallback">Sin imagen TMDB<br>para este id</div>
    </div>
    <div class="panel">
      <h2 id="title">—</h2>
      <div class="year" id="year">—</div>
      <div class="score" id="score">—</div>
      <div class="ocr-box"><b>OCR full-text</b><span id="ocr">—</span></div>
      <p class="hint">Casos donde el OCR <b>no</b> encaja bien con el título TMDB (score&lt;0.65).
        Validá si la <b>portada es de esa película</b>.
        <b>ok</b> = sí es la peli (OCR falló o tipografía rara) ·
        <b>wrong</b> = portada equivocada ·
        <b>no_title</b> = es la peli pero el título no está / no se lee ·
        <b>other_lang</b> = portada en otro idioma (no inglés) ·
        <b>unsure</b> = dudoso.</p>
      <div class="actions">
        <button type="button" class="ok" data-pick="ok" title="1">1 · ok</button>
        <button type="button" class="wrong" data-pick="wrong" title="2">2 · wrong</button>
        <button type="button" class="notitle" data-pick="no_title" title="3">3 · no_title</button>
        <button type="button" class="otherlang" data-pick="other_lang" title="4">4 · other_lang</button>
        <button type="button" class="unsure" data-pick="unsure" title="5">5 · unsure</button>
        <button type="button" class="nav" id="btnPrev" title="←">← Prev</button>
        <button type="button" class="nav" id="btnNext" title="→">Next →</button>
      </div>
      <div class="mine" id="mine">Tu veredicto: <b>—</b></div>
      <p class="keys">Atajos: <kbd>1</kbd>–<kbd>5</kbd> etiquetar · <kbd>←</kbd><kbd>→</kbd> navegar · <kbd>U</kbd> deshacer</p>
    </div>
  </div>
  <div class="toolbar">
    <button type="button" id="btnExport">Exportar CSV (backup)</button>
    <button type="button" id="btnWrong">Exportar solo wrong</button>
    <button type="button" id="btnOtherLang">Exportar other_lang</button>
    <button type="button" id="btnClear">Borrar progreso local</button>
    <span class="status" id="status"></span>
  </div>
  <div class="cloud">
    <h3>Guardar en el repo (GitHub)</h3>
    <p class="hint2">Pages es estático: para no descargar CSV, pegá un
      <a href="https://github.com/settings/tokens?type=beta" target="_blank" rel="noopener">PAT fine-grained</a>
      con permiso <b>Contents: Read and write</b> en
      <code>juanpduque/what-fear-looks-like</code>. El token queda solo en este navegador.
      Archivo: <code>pipeline/data/qa/ocr_title_review_labels.json</code></p>
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
const STORE = "aof-ocr-title-review-v1";
const TOKEN_STORE = "aof-ocr-title-review-gh-token";
const GH_REPO = "juanpduque/what-fear-looks-like";
const GH_PATH = "pipeline/data/qa/ocr_title_review_labels.json";
const GH_BRANCH = "main";
const LABELS = ["ok","wrong","no_title","other_lang","unsure"];
let filter = "all";
let idx = 0;
let verdicts = {};
try { verdicts = JSON.parse(localStorage.getItem(STORE) || "{}") || {}; } catch(e){ verdicts = {}; }
try {
  const t = localStorage.getItem(TOKEN_STORE) || "";
  // filled after DOM; see boot()
  window.__ghTokenInit = t;
} catch(e){}

function save(){ localStorage.setItem(STORE, JSON.stringify(verdicts)); updateStatus(); }

function filtered(){
  return DATA.filter(d => {
    const v = verdicts[d.id];
    if(filter==="todo") return !v;
    if(filter==="done") return !!v;
    if(LABELS.includes(filter))
      return v && v.label===filter;
    if(filter==="low") return d.score < 0.3;
    return true;
  });
}

function posterSrc(d){
  // Prefer absolute CDN URL baked at build time
  if(d && d.img) return d.img;
  if(d && d.path) return "https://image.tmdb.org/t/p/w500" + d.path;
  return "";
}

function show(){
  const list = filtered();
  const img = document.getElementById("poster");
  const wrap = document.getElementById("posterWrap");
  if(!list.length){
    document.getElementById("title").textContent = "No hay casos en este filtro";
    img.removeAttribute("src");
    wrap.classList.add("noimg");
    document.getElementById("ocr").textContent = "—";
    document.getElementById("mine").innerHTML = "Tu veredicto: <b>—</b>";
    document.getElementById("mine").className = "mine";
    return;
  }
  if(idx >= list.length) idx = list.length - 1;
  if(idx < 0) idx = 0;
  const d = list[idx];
  const src = posterSrc(d);
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
  document.getElementById("year").innerHTML =
    y + " · id " + d.id +
    ' · <a href="https://www.themoviedb.org/movie/'+d.id+'" target="_blank" rel="noopener">TMDB</a>';
  const conf = (d.mean_conf==null) ? "—" : d.mean_conf;
  document.getElementById("score").textContent =
    "score " + d.score.toFixed(2) + " · lines " + d.n_lines + " · conf " + conf;
  document.getElementById("ocr").textContent = d.ocr || "(vacío)";
  document.querySelectorAll(".actions button[data-pick]").forEach(b => b.classList.remove("is-selected"));
  const v = verdicts[d.id];
  const mine = document.getElementById("mine");
  if(!v){
    mine.className = "mine";
    mine.innerHTML = "Tu veredicto: <b>sin marcar</b>";
  } else {
    mine.className = "mine marked";
    mine.innerHTML = "Tu veredicto: <b>" + v.label + "</b>";
    const pick = document.querySelector('.actions button[data-pick="'+v.label+'"]');
    if(pick) pick.classList.add("is-selected");
  }
  document.getElementById("counter").textContent =
    (idx+1) + " / " + list.length + "  (set " + DATA.length + ")";
  const done = DATA.filter(x => verdicts[x.id]).length;
  document.getElementById("bar").style.width = (100 * done / DATA.length) + "%";
  updateStatus();
}

function setLabel(label){
  const list = filtered();
  if(!list.length || !LABELS.includes(label)) return;
  const d = list[idx];
  verdicts[d.id] = {
    id: d.id, title: d.title, year: d.year, score: d.score,
    label: label, ocr: d.ocr, ts: Date.now()
  };
  save();
  // stay in list; advance within current filter
  const nextList = filtered();
  if(filter==="todo"){
    // item left the todo list; keep same idx
    if(idx >= nextList.length) idx = Math.max(0, nextList.length - 1);
  } else if(idx < list.length - 1) {
    idx++;
  }
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
  const counts = {ok:0,wrong:0,no_title:0,other_lang:0,unsure:0};
  let done = 0;
  DATA.forEach(d => {
    const v = verdicts[d.id];
    if(!v) return;
    done++;
    if(counts[v.label]!=null) counts[v.label]++;
  });
  document.getElementById("status").textContent =
    "marcados " + done + "/" + DATA.length +
    " · ok " + counts.ok +
    " · wrong " + counts.wrong +
    " · no_title " + counts.no_title +
    " · other_lang " + counts.other_lang +
    " · unsure " + counts.unsure;
}

function download(name, text){
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], {type:"text/csv"}));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

function toCSV(rows){
  const cols = ["id","title","year","score","label","ocr"];
  const esc = v => {
    const s = String(v==null?"":v);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g,'""') + '"' : s;
  };
  return cols.join(",") + "\n" + rows.map(r => cols.map(c => esc(r[c])).join(",")).join("\n");
}

function ghMsg(text, ok){
  const el = document.getElementById("ghMsg");
  el.textContent = text || "";
  el.className = "msg " + (ok===true ? "ok" : ok===false ? "err" : "");
}

function getToken(){
  return (document.getElementById("ghToken").value || "").trim();
}

function utf8ToB64(str){
  return btoa(unescape(encodeURIComponent(str)));
}
function b64ToUtf8(str){
  return decodeURIComponent(escape(atob(str)));
}

function mergeVerdicts(remote, local){
  const out = Object.assign({}, remote || {});
  Object.keys(local || {}).forEach(id => {
    const a = out[id], b = local[id];
    if(!a) out[id] = b;
    else if((b.ts||0) >= (a.ts||0)) out[id] = b;
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
  if(!r.ok){
    const t = await r.text();
    throw new Error("GET " + r.status + " " + t.slice(0,180));
  }
  const j = await r.json();
  let parsed = {};
  try {
    const raw = b64ToUtf8(j.content.replace(/\n/g,""));
    const data = JSON.parse(raw);
    parsed = data.verdicts || data || {};
  } catch(e){
    parsed = {};
  }
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
    const bodyObj = {
      updated_at: new Date().toISOString(),
      n_labels: n,
      verdicts: merged
    };
    const payload = {
      message: "chore(qa): update OCR title review labels (" + n + ")",
      content: utf8ToB64(JSON.stringify(bodyObj, null, 2) + "\n"),
      branch: GH_BRANCH
    };
    if(remote.sha) payload.sha = remote.sha;
    const url = "https://api.github.com/repos/" + GH_REPO + "/contents/" + GH_PATH;
    const r = await fetch(url, {
      method: "PUT",
      headers: {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });
    if(!r.ok){
      const t = await r.text();
      throw new Error("PUT " + r.status + " " + t.slice(0,220));
    }
    verdicts = merged;
    save();
    show();
    ghMsg("Guardado en GitHub · " + n + " labels → " + GH_PATH, true);
  } catch(e){
    ghMsg(String(e.message || e), false);
  }
}

async function pullFromGitHub(){
  const token = getToken();
  if(!token){ ghMsg("Pegá un PAT primero.", false); return; }
  ghMsg("Cargando…");
  try {
    const remote = await ghGetFile(token);
    if(!remote.exists){
      ghMsg("Aún no hay archivo en el repo. Guardá primero.", false);
      return;
    }
    const before = Object.keys(verdicts).length;
    verdicts = mergeVerdicts(verdicts, remote.verdicts);
    save();
    show();
    const after = Object.keys(verdicts).length;
    ghMsg("Cargado desde GitHub · local " + before + " → " + after + " (merge por timestamp)", true);
  } catch(e){
    ghMsg(String(e.message || e), false);
  }
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
  b.addEventListener("click", () => setLabel(b.getAttribute("data-pick")));
});
document.getElementById("btnPrev").onclick = () => { idx--; show(); };
document.getElementById("btnNext").onclick = () => { idx++; show(); };
document.getElementById("btnExport").onclick = () => {
  const rows = DATA.map(d => verdicts[d.id]).filter(Boolean);
  download("ocr_title_review.csv", toCSV(rows));
};
document.getElementById("btnWrong").onclick = () => {
  const rows = DATA.map(d => verdicts[d.id]).filter(v => v && v.label==="wrong");
  download("ocr_title_review_wrong.csv", toCSV(rows));
};
document.getElementById("btnOtherLang").onclick = () => {
  const rows = DATA.map(d => verdicts[d.id]).filter(v => v && v.label==="other_lang");
  download("ocr_title_review_other_lang.csv", toCSV(rows));
};
document.getElementById("btnClear").onclick = () => {
  if(!confirm("¿Borrar todo el progreso local de esta QA?")) return;
  verdicts = {};
  save();
  idx = 0;
  show();
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
  if(e.key==="1") setLabel("ok");
  else if(e.key==="2") setLabel("wrong");
  else if(e.key==="3") setLabel("no_title");
  else if(e.key==="4") setLabel("other_lang");
  else if(e.key==="5") setLabel("unsure");
  else if(e.key==="ArrowLeft"){ idx--; show(); }
  else if(e.key==="ArrowRight"){ idx++; show(); }
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
