#!/usr/bin/env python3
"""Build a second-pass medium QA page from pass-1 labels.

Reads pipeline/data/label_qa_medium_pass1.csv (from the first labeling run),
attaches TMDB poster paths, and writes site/label-qa-medium-r2.html.

  python3 build_label_qa_medium_r2.py
  open ../site/label-qa-medium-r2.html
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PASS1 = DATA / "label_qa_medium_pass1.csv"
OUT = ROOT.parent / "site" / "label-qa-medium-r2.html"


def main():
    df = pd.read_csv(PASS1)
    need = {"id", "title", "year", "p_painted", "clip_proposed", "band", "final_label"}
    missing = need - set(df.columns)
    if missing:
        raise SystemExit(f"pass1 CSV missing columns: {sorted(missing)}")

    paths: dict[int, str] = {}
    hm = DATA / "horror_movies.csv"
    if hm.exists():
        for r in pd.read_csv(hm, usecols=lambda c: c in {"id", "poster_path"}).itertuples(index=False):
            p = getattr(r, "poster_path", None)
            if isinstance(p, str) and p.startswith("/"):
                paths[int(r.id)] = p

    rows = []
    missing_path = 0
    for r in df.itertuples(index=False):
        path = paths.get(int(r.id))
        if not path:
            missing_path += 1
        rows.append({
            "id": int(r.id),
            "title": str(r.title),
            "year": int(r.year),
            "p": round(float(r.p_painted), 4),
            "proposed": str(r.clip_proposed),
            "band": str(r.band),
            "pass1": str(r.final_label),
            "path": path,
        })

    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    html = HTML_TEMPLATE.replace("__N__", str(len(rows))).replace("__DATA__", payload)
    OUT.write_text(html, encoding="utf-8")
    vc = df["final_label"].value_counts()
    print(f"Wrote {OUT} ({len(rows)} posters, {len(rows)-missing_path} with TMDB path)")
    print(vc.to_string())


HTML_TEMPLATE = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Label QA r2 — medium review (__N__)</title>
<style>
:root{--bg:#0a0a0c;--bg2:#141416;--ink:#e8e4da;--dim:#9a958a;--line:#2a2a30;
  --blood:#c1121f;--amber:#e5a00d;--ok:#3d9a6a;--doubt:#c4a35a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"Source Serif 4",Georgia,serif;min-height:100vh}
.wrap{max-width:980px;margin:0 auto;padding:20px 20px 80px}
.top{display:flex;flex-wrap:wrap;gap:12px 20px;align-items:baseline;
  border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:18px}
h1{font-family:"Anton",Impact,sans-serif;font-size:26px;letter-spacing:.02em;
  text-transform:uppercase;margin:0;font-weight:400}
.meta{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--dim)}
.progress{flex:1;min-width:160px;height:6px;background:#1a1a1e;border-radius:3px;overflow:hidden}
.progress i{display:block;height:100%;background:var(--amber);width:0%}
.stage{display:grid;grid-template-columns:minmax(0,320px) 1fr;gap:28px;align-items:start}
@media(max-width:720px){.stage{grid-template-columns:1fr}}
.poster{width:100%;aspect-ratio:2/3;object-fit:cover;border-radius:4px;
  box-shadow:0 20px 50px rgba(0,0,0,.6);background:#1a1a1e;display:block}
.panel h2{font-family:"Anton",Impact,sans-serif;font-size:34px;line-height:1;
  text-transform:uppercase;margin:0 0 8px;font-weight:400}
.year{font-family:ui-monospace,Menlo,monospace;color:var(--amber);font-size:13px;margin-bottom:14px}
.badge{display:inline-block;font-family:ui-monospace,Menlo,monospace;font-size:12px;
  letter-spacing:.08em;text-transform:uppercase;padding:6px 10px;border-radius:3px;
  border:1px solid var(--line);margin-right:8px;margin-bottom:8px}
.badge.painted{color:#f0d9a8;border-color:#6a5630;background:#1a1610}
.badge.photo{color:#a8c4f0;border-color:#30466a;background:#10141a}
.badge.composite{color:#d4b8ea;border-color:#5a406e;background:#161018}
.badge.doubtful{color:var(--doubt)}
.badge.clip{color:var(--dim)}
.badge.ok{color:#8fd4ad;border-color:#2d6a4a}
.badge.changed{color:#f0a0a8;border-color:#7a1a22}
.pass1-box{margin:10px 0 16px;padding:12px 14px;border:1px solid var(--line);
  border-radius:4px;background:var(--bg2);font-family:ui-monospace,Menlo,monospace;font-size:13px}
.pass1-box b{color:var(--amber)}
.score{font-size:28px;font-family:"Anton",Impact,sans-serif;color:var(--amber);margin:4px 0 8px}
.hint{color:var(--dim);font-size:14px;line-height:1.45;max-width:38em;margin:0 0 18px}
.hint b{color:var(--ink);font-weight:600}
.actions{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0}
.actions button{font-family:ui-monospace,Menlo,monospace;font-size:13px;letter-spacing:.04em;
  border:1px solid var(--line);background:var(--bg2);color:var(--ink);padding:12px 16px;
  border-radius:4px;cursor:pointer}
.actions button:hover{border-color:#555}
.actions button.confirm{border-color:#2d6a4a;color:#8fd4ad;background:#101814}
.actions button.painted{border-color:#6a5630;color:#f0d9a8}
.actions button.photo{border-color:#30466a;color:#a8c4f0}
.actions button.composite{border-color:#5a406e;color:#d4b8ea}
.actions button.doubt{border-color:#6a5630;color:#e5c97a}
.actions button.nav{opacity:.85}
.keys{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--dim);line-height:1.6}
kbd{background:#1a1a1e;border:1px solid #333;border-radius:3px;padding:1px 5px;color:var(--ink)}
.verdict{font-family:ui-monospace,Menlo,monospace;font-size:13px;margin-top:14px;min-height:1.2em}
.verdict.painted{color:#f0d9a8}.verdict.photo{color:#a8c4f0}
.verdict.composite{color:#d4b8ea}.verdict.doubtful{color:var(--doubt)}
.verdict.ok{color:var(--ok)}
.toolbar{display:flex;flex-wrap:wrap;gap:10px;margin-top:28px;padding-top:16px;border-top:1px solid var(--line)}
.toolbar button{font-family:ui-monospace,Menlo,monospace;font-size:12px;background:#1a1a1e;
  color:var(--ink);border:1px solid var(--line);border-radius:4px;padding:8px 12px;cursor:pointer}
.toolbar button:hover{background:#222}
.status{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--dim);margin-left:auto}
.filter{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
.filter button{font-family:ui-monospace,Menlo,monospace;font-size:11px;background:transparent;
  color:var(--dim);border:1px solid var(--line);border-radius:3px;padding:5px 8px;cursor:pointer}
.filter button.on{color:var(--amber);border-color:var(--amber)}
</style>
<link href="https://fonts.googleapis.com/css2?family=Anton&family=Source+Serif+4:wght@400;600&display=swap" rel="stylesheet">
</head>
<body>
<div class="wrap">
  <div class="top">
    <h1>Medium · revisión r2</h1>
    <span class="meta" id="counter">0 / __N__</span>
    <div class="progress" aria-hidden="true"><i id="bar"></i></div>
  </div>
  <div class="filter" id="filters">
    <button type="button" data-f="all" class="on">all</button>
    <button type="button" data-f="todo">sin r2</button>
    <button type="button" data-f="done">con r2</button>
    <button type="button" data-f="confirmed">confirmadas</button>
    <button type="button" data-f="changed">cambiadas</button>
    <button type="button" data-f="p1_painted">pass1 painted</button>
    <button type="button" data-f="p1_photo">pass1 photo</button>
    <button type="button" data-f="p1_composite">pass1 composite</button>
    <button type="button" data-f="neq_clip">≠ CLIP</button>
  </div>
  <div class="stage">
    <img class="poster" id="poster" alt="">
    <div class="panel">
      <h2 id="title">—</h2>
      <div class="year" id="year">—</div>
      <div>
        <span class="badge" id="pass1Badge">—</span>
        <span class="badge clip" id="propBadge">—</span>
        <span class="badge clip" id="bandBadge">—</span>
      </div>
      <div class="pass1-box" id="pass1Box">pass1: —</div>
      <div class="score" id="score">—</div>
      <p class="hint">Segunda pasada: mirá el póster y <b>confirmá</b> la etiqueta de la primera revisión,
        o <b>cambiala</b> si no estás de acuerdo.
        <b>painted</b> = ilustración principal · <b>photo</b> = foto con edición liviana ·
        <b>composite</b> = foto + intervención fuerte. Progreso local; exportá al terminar.</p>
      <div class="actions">
        <button type="button" class="confirm" id="btnConfirm" title="Enter">↵ · Confirmar pass1</button>
        <button type="button" class="painted" id="btnPainted" title="1">1 · painted</button>
        <button type="button" class="photo" id="btnPhoto" title="2">2 · photo</button>
        <button type="button" class="composite" id="btnComposite" title="3">3 · composite</button>
        <button type="button" class="doubt" id="btnDoubt" title="4">4 · doubtful</button>
        <button type="button" class="nav" id="btnPrev" title="←">← Prev</button>
        <button type="button" class="nav" id="btnNext" title="→">Next →</button>
      </div>
      <div class="verdict" id="verdict"></div>
      <p class="keys">Atajos: <kbd>Enter</kbd>/<kbd>Space</kbd> confirmar pass1 ·
        <kbd>1</kbd>–<kbd>4</kbd> cambiar · <kbd>←</kbd><kbd>→</kbd> navegar · <kbd>U</kbd> deshacer</p>
    </div>
  </div>
  <div class="toolbar">
    <button type="button" id="btnExport">Exportar CSV r2</button>
    <button type="button" id="btnGold">Exportar gold (acuerdo r1=r2, sin doubt)</button>
    <button type="button" id="btnChanged">Exportar solo cambiadas</button>
    <button type="button" id="btnClear">Borrar progreso r2 local</button>
    <span class="status" id="status"></span>
  </div>
</div>
<script>
const DATA = __DATA__;
const STORE = "aof-label-qa-medium-r2-v1";
const LABELS = ["painted","photo","composite","doubtful"];
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
    if(filter==="confirmed") return v && v.pass2===d.pass1;
    if(filter==="changed") return v && v.pass2!==d.pass1;
    if(filter==="p1_painted") return d.pass1==="painted";
    if(filter==="p1_photo") return d.pass1==="photo";
    if(filter==="p1_composite") return d.pass1==="composite";
    if(filter==="neq_clip") return d.pass1!==d.proposed;
    return true;
  });
}

function posterSrc(d){
  if(d && d.path) return "https://image.tmdb.org/t/p/w500" + d.path;
  return "../pipeline/data/posters/" + d.id + ".jpg";
}

function show(){
  const list = filtered();
  if(!list.length){
    document.getElementById("title").textContent = "No hay posters en este filtro";
    document.getElementById("poster").removeAttribute("src");
    document.getElementById("verdict").textContent = "";
    document.getElementById("pass1Box").textContent = "";
    return;
  }
  if(idx >= list.length) idx = list.length - 1;
  if(idx < 0) idx = 0;
  const d = list[idx];
  const img = document.getElementById("poster");
  img.src = posterSrc(d);
  img.alt = d.title;
  document.getElementById("title").textContent = d.title;
  document.getElementById("year").textContent = d.year + " · id " + d.id;
  const p1b = document.getElementById("pass1Badge");
  p1b.textContent = "pass1: " + d.pass1;
  p1b.className = "badge " + d.pass1;
  const pb = document.getElementById("propBadge");
  pb.textContent = "CLIP: " + d.proposed;
  pb.className = "badge clip " + d.proposed;
  const bb = document.getElementById("bandBadge");
  bb.textContent = "band " + d.band.replace("_"," ");
  bb.className = "badge clip";
  document.getElementById("pass1Box").innerHTML =
    "Primera validación: <b>" + d.pass1 + "</b>" +
    (d.pass1===d.proposed ? " · coincide con CLIP" : " · ≠ CLIP (" + d.proposed + ")");
  document.getElementById("score").textContent = "p_painted " + d.p.toFixed(3);
  const v = verdicts[d.id];
  const verd = document.getElementById("verdict");
  if(!v){ verd.textContent = "Sin revisión r2"; verd.className = "verdict"; }
  else if(v.pass2===d.pass1){
    verd.textContent = "r2: confirmada → " + v.pass2;
    verd.className = "verdict ok";
  } else {
    verd.textContent = "r2: cambiada " + d.pass1 + " → " + v.pass2;
    verd.className = "verdict " + v.pass2;
  }
  document.getElementById("counter").textContent = (idx+1) + " / " + list.length + "  (set " + DATA.length + ")";
  const done = DATA.filter(x => verdicts[x.id]).length;
  document.getElementById("bar").style.width = (100 * done / DATA.length) + "%";
  updateStatus();
}

function setPass2(pass2){
  const list = filtered();
  if(!list.length) return;
  if(!LABELS.includes(pass2)) return;
  const d = list[idx];
  verdicts[d.id] = {
    id: d.id, title: d.title, year: d.year, p: d.p,
    proposed: d.proposed, band: d.band,
    pass1: d.pass1, pass2: pass2,
    changed: pass2!==d.pass1,
    ts: Date.now()
  };
  save();
  if(idx < list.length - 1) idx++;
  show();
}

function confirmPass1(){
  const list = filtered();
  if(!list.length) return;
  setPass2(list[idx].pass1);
}

function undo(){
  const list = filtered();
  if(!list.length) return;
  delete verdicts[list[idx].id];
  save(); show();
}

function updateStatus(){
  const n = DATA.length;
  const done = DATA.filter(d => verdicts[d.id]).length;
  const conf = DATA.filter(d => verdicts[d.id] && verdicts[d.id].pass2===d.pass1).length;
  const ch = DATA.filter(d => verdicts[d.id] && verdicts[d.id].pass2!==d.pass1).length;
  document.getElementById("status").textContent =
    done + "/" + n + " · confirm " + conf + " · changed " + ch;
}

function toCSV(rows){
  const cols = ["id","title","year","p_painted","clip_proposed","band","pass1_label","pass2_label","changed"];
  const esc = s => '"' + String(s).replace(/"/g,'""') + '"';
  const lines = [cols.join(",")];
  rows.forEach(r => {
    lines.push([
      r.id, esc(r.title), r.year, r.p, r.proposed, r.band,
      r.pass1, r.pass2||"", r.changed ? "1" : "0"
    ].join(","));
  });
  return lines.join("\n");
}

function download(name, text){
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], {type:"text/csv"}));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

document.getElementById("btnConfirm").onclick = confirmPass1;
document.getElementById("btnPainted").onclick = () => setPass2("painted");
document.getElementById("btnPhoto").onclick = () => setPass2("photo");
document.getElementById("btnComposite").onclick = () => setPass2("composite");
document.getElementById("btnDoubt").onclick = () => setPass2("doubtful");
document.getElementById("btnPrev").onclick = () => { idx--; show(); };
document.getElementById("btnNext").onclick = () => { idx++; show(); };
document.getElementById("btnExport").onclick = () => {
  const rows = Object.values(verdicts);
  if(!rows.length){ alert("Aún no hay revisiones r2"); return; }
  download("label_qa_medium_r2.csv", toCSV(rows));
};
document.getElementById("btnGold").onclick = () => {
  const rows = Object.values(verdicts).filter(v =>
    v.pass2 && v.pass2!=="doubtful" && v.pass2===v.pass1);
  if(!rows.length){ alert("No hay acuerdos r1=r2 aún"); return; }
  download("label_qa_medium_gold_r2.csv", toCSV(rows));
};
document.getElementById("btnChanged").onclick = () => {
  const rows = Object.values(verdicts).filter(v => v.changed);
  if(!rows.length){ alert("No hay cambios aún"); return; }
  download("label_qa_medium_r2_changed.csv", toCSV(rows));
};
document.getElementById("btnClear").onclick = () => {
  if(confirm("¿Borrar el progreso de la revisión r2 en este navegador?")){
    verdicts = {}; save(); show();
  }
};
document.getElementById("filters").onclick = (e) => {
  const b = e.target.closest("button[data-f]");
  if(!b) return;
  filter = b.dataset.f;
  document.querySelectorAll("#filters button").forEach(x => x.classList.toggle("on", x===b));
  idx = 0; show();
};
document.addEventListener("keydown", (e) => {
  if(e.target.matches("input,textarea")) return;
  if(e.key==="Enter" || e.key===" "){ e.preventDefault(); confirmPass1(); }
  else if(e.key==="1") setPass2("painted");
  else if(e.key==="2") setPass2("photo");
  else if(e.key==="3") setPass2("composite");
  else if(e.key==="4") setPass2("doubtful");
  else if(e.key==="ArrowRight"){ idx++; show(); }
  else if(e.key==="ArrowLeft"){ idx--; show(); }
  else if(e.key==="u" || e.key==="U") undo();
});
show();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
