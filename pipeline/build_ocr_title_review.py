#!/usr/bin/env python3
"""Build manual cover-validation UI for OCR title mismatches.

Reads data/qa/poster_ocr_title_mismatch.csv (score < 0.65 vs TMDB title)
and writes site/ocr-title-review.html — local labeling with localStorage + CSV export.

  python3 build_ocr_title_review.py
  open ../site/ocr-title-review.html
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SRC = DATA / "qa" / "poster_ocr_title_mismatch.csv"
OUT = ROOT.parent / "site" / "ocr-title-review.html"


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


def main() -> None:
    if not SRC.exists():
        raise SystemExit(
            f"falta {SRC} — regenerá el mismatch CSV desde poster_ocr.csv primero"
        )
    df = pd.read_csv(SRC)
    need = {"id", "title", "year", "score", "full_ocr"}
    missing = need - set(df.columns)
    if missing:
        raise SystemExit(f"CSV sin columnas: {sorted(missing)}")

    paths = load_paths()
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
                "path": path,
            }
        )

    # worst score first — more likely wrong covers
    rows.sort(key=lambda x: (x["score"], x["year"], x["id"]))
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    html = HTML.replace("__N__", str(len(rows))).replace("__DATA__", payload)
    OUT.write_text(html, encoding="utf-8")
    print(
        f"Wrote {OUT} ({len(rows):,} cases, {len(rows) - miss_path:,} with TMDB path, "
        f"{miss_path:,} local-jpg fallback)"
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
.poster{width:100%;aspect-ratio:2/3;object-fit:cover;border-radius:4px;
  box-shadow:0 20px 50px rgba(0,0,0,.6);background:#1a1a1e;display:block}
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
    <button type="button" data-f="unsure">unsure</button>
    <button type="button" data-f="low">score&lt;0.3</button>
  </div>
  <div class="stage">
    <img class="poster" id="poster" alt="">
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
        <b>unsure</b> = dudoso.</p>
      <div class="actions">
        <button type="button" class="ok" data-pick="ok" title="1">1 · ok</button>
        <button type="button" class="wrong" data-pick="wrong" title="2">2 · wrong</button>
        <button type="button" class="notitle" data-pick="no_title" title="3">3 · no_title</button>
        <button type="button" class="unsure" data-pick="unsure" title="4">4 · unsure</button>
        <button type="button" class="nav" id="btnPrev" title="←">← Prev</button>
        <button type="button" class="nav" id="btnNext" title="→">Next →</button>
      </div>
      <div class="mine" id="mine">Tu veredicto: <b>—</b></div>
      <p class="keys">Atajos: <kbd>1</kbd>–<kbd>4</kbd> etiquetar · <kbd>←</kbd><kbd>→</kbd> navegar · <kbd>U</kbd> deshacer</p>
    </div>
  </div>
  <div class="toolbar">
    <button type="button" id="btnExport">Exportar CSV</button>
    <button type="button" id="btnWrong">Exportar solo wrong</button>
    <button type="button" id="btnClear">Borrar progreso local</button>
    <span class="status" id="status"></span>
  </div>
</div>
<script>
const DATA = __DATA__;
const STORE = "aof-ocr-title-review-v1";
const LABELS = ["ok","wrong","no_title","unsure"];
let filter = "all";
let idx = 0;
let verdicts = {};
try { verdicts = JSON.parse(localStorage.getItem(STORE) || "{}") || {}; } catch(e){ verdicts = {}; }

function save(){ localStorage.setItem(STORE, JSON.stringify(verdicts)); updateStatus(); }

function filtered(){
  return DATA.filter(d => {
    const v = verdicts[d.id];
    if(filter==="todo") return !v;
    if(filter==="done") return !!v;
    if(filter==="ok" || filter==="wrong" || filter==="no_title" || filter==="unsure")
      return v && v.label===filter;
    if(filter==="low") return d.score < 0.3;
    return true;
  });
}

function posterSrc(d){
  if(d && d.path) return "https://image.tmdb.org/t/p/w500" + d.path;
  return "../pipeline/data/posters/" + d.id + ".jpg";
}

function show(){
  const list = filtered();
  const img = document.getElementById("poster");
  if(!list.length){
    document.getElementById("title").textContent = "No hay casos en este filtro";
    img.removeAttribute("src");
    document.getElementById("ocr").textContent = "—";
    document.getElementById("mine").innerHTML = "Tu veredicto: <b>—</b>";
    document.getElementById("mine").className = "mine";
    return;
  }
  if(idx >= list.length) idx = list.length - 1;
  if(idx < 0) idx = 0;
  const d = list[idx];
  img.src = posterSrc(d);
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
  const counts = {ok:0,wrong:0,no_title:0,unsure:0};
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
document.getElementById("btnClear").onclick = () => {
  if(!confirm("¿Borrar todo el progreso local de esta QA?")) return;
  verdicts = {};
  save();
  idx = 0;
  show();
};
document.addEventListener("keydown", e => {
  if(e.target && /input|textarea/i.test(e.target.tagName)) return;
  if(e.key==="1") setLabel("ok");
  else if(e.key==="2") setLabel("wrong");
  else if(e.key==="3") setLabel("no_title");
  else if(e.key==="4") setLabel("unsure");
  else if(e.key==="ArrowLeft"){ idx--; show(); }
  else if(e.key==="ArrowRight"){ idx++; show(); }
  else if(e.key==="u" || e.key==="U") undo();
});

show();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
