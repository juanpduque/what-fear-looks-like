#!/usr/bin/env python3
"""Build medium labeling QA (r3) for team — uncertain pool + GitHub PAT save.

Sample from medium_pred.csv (exclude existing gold), prioritize composite /
low-confidence. Writes:

  site/label-qa-medium.html          (for GitHub Pages)
  pipeline/qa/label-qa-medium.html   (local mirror)
  pipeline/data/qa/medium_qa_r3_ids.csv
  pipeline/data/qa/medium_qa_r3_labels.json  (stub if missing)

  python3 build_label_qa_medium_r3.py
  python3 build_label_qa_medium_r3.py --n 250
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PRED = DATA / "medium_pred.csv"
GOLD = DATA / "label_qa_medium_train.csv"
HM = DATA / "horror_movies.csv"
BF = DATA / "poster_paths_backfill.csv"
OUT_SITE = ROOT.parent / "site" / "label-qa-medium.html"
OUT_QA = ROOT / "qa" / "label-qa-medium.html"
OUT_IDS = DATA / "qa" / "medium_qa_r3_ids.csv"
OUT_LABELS = DATA / "qa" / "medium_qa_r3_labels.json"
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


def load_gold() -> set[int]:
    out: set[int] = set()
    if not GOLD.exists():
        return out
    with GOLD.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                out.add(int(r["id"]))
            except Exception:
                pass
    return out


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


def pick_sample(n: int, seed: int) -> list[dict]:
    gold = load_gold()
    paths = load_paths()
    meta = load_meta()
    candidates: list[dict] = []
    with PRED.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except Exception:
                continue
            if pid in gold:
                continue
            if (r.get("gold_label") or "").strip():
                continue
            conf = float(r.get("pred_confidence") or 0)
            pp = float(r.get("p_painted") or 0)
            ph = float(r.get("p_photo") or 0)
            pc = float(r.get("p_composite") or 0)
            probs = sorted([pp, ph, pc], reverse=True)
            margin = probs[0] - probs[1]
            pred = (r.get("pred_label") or "").strip()
            # uncertain pool
            if conf >= 0.55 and margin >= 0.15 and pred != "composite":
                # still keep some medium-confidence composite-leaning
                if not (pred == "composite" or pc >= 0.28):
                    continue
            if pid not in paths:
                continue
            m = meta.get(pid, {})
            candidates.append(
                {
                    "id": pid,
                    "title": m.get("title") or f"id {pid}",
                    "year": m.get("year") or "",
                    "pred": pred,
                    "conf": round(conf, 4),
                    "p_painted": round(pp, 4),
                    "p_photo": round(ph, 4),
                    "p_composite": round(pc, 4),
                    "margin": round(margin, 4),
                    "path": paths[pid],
                    "img": IMG + paths[pid],
                }
            )

    # Priority buckets
    by_pred = {"composite": [], "photo": [], "painted": []}
    for c in candidates:
        by_pred.setdefault(c["pred"], []).append(c)
    for k in by_pred:
        # lowest conf / margin first
        by_pred[k].sort(key=lambda x: (x["conf"], x["margin"], -x["p_composite"]))

    # Targets within n: ~40% composite, 30% photo, 30% painted
    n_comp = min(len(by_pred["composite"]), max(1, int(round(n * 0.40))))
    n_photo = min(len(by_pred["photo"]), max(1, int(round(n * 0.30))))
    n_paint = min(len(by_pred["painted"]), n - n_comp - n_photo)
    if n_paint < 0:
        n_paint = 0
    # fill remainder from composite then photo
    picked = by_pred["composite"][:n_comp] + by_pred["photo"][:n_photo] + by_pred["painted"][:n_paint]
    rem = n - len(picked)
    if rem > 0:
        used = {x["id"] for x in picked}
        rest = [c for c in candidates if c["id"] not in used]
        rest.sort(key=lambda x: (0 if x["pred"] == "composite" else 1, x["conf"], x["margin"]))
        picked.extend(rest[:rem])

    # deterministic shuffle for review order (not sorted by class)
    import random

    rng = random.Random(seed)
    rng.shuffle(picked)
    return picked[:n]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=250)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    if not PRED.exists():
        raise SystemExit(f"missing {PRED} — run train_medium_classifier.py first")

    rows = pick_sample(args.n, args.seed)
    from collections import Counter

    print(
        f"sample n={len(rows)} by_pred={dict(Counter(r['pred'] for r in rows))}",
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
                "pred",
                "conf",
                "p_painted",
                "p_photo",
                "p_composite",
                "margin",
                "path",
            ],
        )
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in w.fieldnames})

    if not OUT_LABELS.exists():
        OUT_LABELS.write_text(
            json.dumps(
                {"updated_at": None, "n_labels": 0, "verdicts": {}, "note": "medium QA r3"},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"stub {OUT_LABELS}", flush=True)

    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
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
<title>Label QA · medium r3 (__N__)</title>
<style>
:root{--bg:#0a0a0c;--bg2:#141416;--ink:#e8e4da;--dim:#9a958a;--line:#2a2a30;
  --blood:#c1121f;--amber:#e5a00d;--ok:#3d9a6a;--paint:#c45c26;--photo:#3a7ca5;--comp:#7b68a6}
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
.badge.painted{color:#f0c3a8;border-color:var(--paint)}
.badge.photo{color:#a8d4f0;border-color:var(--photo)}
.badge.composite{color:#d4c4f0;border-color:var(--comp)}
.hint{color:var(--dim);font-size:14px;line-height:1.45}
.actions{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}
.actions button{border:1px solid var(--line);background:var(--bg2);color:var(--ink);
  padding:10px 12px;border-radius:4px;cursor:pointer;font:inherit;font-size:14px}
.actions button.painted{border-color:var(--paint)}
.actions button.photo{border-color:var(--photo)}
.actions button.composite{border-color:var(--comp)}
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
    <h1>Medium · ronda 3 (equipo)</h1>
    <span class="meta" id="counter">0 / __N__</span>
    <div class="progress" aria-hidden="true"><i id="bar"></i></div>
  </div>
  <div class="filter" id="filters">
    <button type="button" data-f="all" class="on">all</button>
    <button type="button" data-f="todo">sin marcar</button>
    <button type="button" data-f="done">marcados</button>
    <button type="button" data-f="pred_composite">pred composite</button>
    <button type="button" data-f="pred_photo">pred photo</button>
    <button type="button" data-f="pred_painted">pred painted</button>
    <button type="button" data-f="lab_painted">→ painted</button>
    <button type="button" data-f="lab_photo">→ photo</button>
    <button type="button" data-f="lab_composite">→ composite</button>
    <button type="button" data-f="lab_doubtful">→ doubtful</button>
  </div>
  <div class="stage">
    <img class="poster" id="poster" alt="">
    <div class="panel">
      <h2 id="title">—</h2>
      <div class="year" id="year">—</div>
      <div>
        <span class="badge" id="predBadge">—</span>
      </div>
      <div class="score" id="score">—</div>
      <p class="hint"><b>painted</b> = ilustración dominante · <b>photo</b> = foto / live-action con edición liviana ·
        <b>composite</b> = foto + intervención fuerte (pintura, collage, tipografía ilustrada dominante).
        <b>doubtful</b> si no estás seguro. Muestra de inciertos del modelo; prioriza composite.</p>
      <div class="actions">
        <button type="button" class="painted" data-pick="painted" title="1">1 · painted</button>
        <button type="button" class="photo" data-pick="photo" title="2">2 · photo</button>
        <button type="button" class="composite" data-pick="composite" title="3">3 · composite</button>
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
      Archivo: <code>pipeline/data/qa/medium_qa_r3_labels.json</code>.
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
const STORE = "aof-label-qa-medium-r3-v1";
const TOKEN_STORE = "aof-medium-qa-r3-gh-token";
const GH_REPO = "juanpduque/what-fear-looks-like";
const GH_PATH = "pipeline/data/qa/medium_qa_r3_labels.json";
const GH_BRANCH = "main";
const LABELS = ["painted","photo","composite","doubtful"];
let filter = "all";
let idx = 0;
let verdicts = {};

function normalizeEntry(v){
  if(!v || typeof v !== "object") return null;
  const lab = (v.label || "").trim();
  if(!LABELS.includes(lab)) return null;
  return {
    id: v.id, title: v.title, year: v.year,
    label: lab, pred: v.pred || "", conf: v.conf,
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
    if(filter==="pred_composite") return d.pred==="composite";
    if(filter==="pred_photo") return d.pred==="photo";
    if(filter==="pred_painted") return d.pred==="painted";
    if(filter==="lab_painted") return v && v.label==="painted";
    if(filter==="lab_photo") return v && v.label==="photo";
    if(filter==="lab_composite") return v && v.label==="composite";
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
  const pb = document.getElementById("predBadge");
  pb.textContent = "modelo: " + d.pred + " (" + Number(d.conf).toFixed(2) + ")";
  pb.className = "badge " + d.pred;
  document.getElementById("score").textContent =
    "p_painted " + Number(d.p_painted).toFixed(3) +
    " · p_photo " + Number(d.p_photo).toFixed(3) +
    " · p_composite " + Number(d.p_composite).toFixed(3);
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
    label: lab, pred: d.pred, conf: d.conf, ts: Date.now()
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
  const counts = {painted:0, photo:0, composite:0, doubtful:0};
  let done = 0;
  DATA.forEach(d => {
    const v = verdicts[d.id];
    if(!v) return;
    done++;
    if(counts[v.label]!=null) counts[v.label]++;
  });
  document.getElementById("status").textContent =
    "marcados " + done + "/" + DATA.length +
    " · painted " + counts.painted +
    " · photo " + counts.photo +
    " · composite " + counts.composite +
    " · doubt " + counts.doubtful;
}
function toCSV(rows){
  const cols = ["id","title","year","label","pred","conf","ts"];
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
      message: "chore(qa): update medium QA r3 labels (" + n + ")",
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
  download("medium_qa_r3_labels.csv", toCSV(rows));
};
document.getElementById("btnClear").onclick = () => {
  if(confirm("¿Borrar el progreso local de medium r3 en este navegador?")){
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
  if(e.key==="1") setLabel("painted");
  else if(e.key==="2") setLabel("photo");
  else if(e.key==="3") setLabel("composite");
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
