#!/usr/bin/env python3
"""Build a painted-vs-photo label QA page for Custom Labels prep.

Samples ~300 posters: uncertain mid-scores + confident extremes, stratified
by decade. Writes site/label-qa-painted.html (self-contained + localStorage).

  python3 build_label_qa_painted.py
  open ../site/label-qa-painted.html   # or any static server
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = ROOT.parent / "site" / "label-qa-painted.html"

N_MID = 180
N_PAINTED = 60
N_PHOTO = 60
MID = (0.35, 0.65)
HI_PAINTED = 0.70
HI_PHOTO = 0.25
SEED = 42


def stratified(df: pd.DataFrame, n: int) -> pd.DataFrame:
    if df.empty or n <= 0:
        return df.iloc[0:0]
    df = df.copy()
    df["decade"] = (df["year"] // 10 * 10).astype(int)
    decades = sorted(df["decade"].unique())
    if not decades:
        return df.sample(min(n, len(df)), random_state=SEED)
    per = max(1, n // len(decades))
    parts = []
    for d in decades:
        g = df[df.decade == d]
        parts.append(g.sample(min(len(g), per), random_state=SEED + int(d)))
    out = pd.concat(parts).drop_duplicates("id")
    if len(out) < n:
        rest = df[~df.id.isin(out.id)]
        need = min(n - len(out), len(rest))
        if need:
            out = pd.concat([out, rest.sample(need, random_state=SEED)])
    return out.sample(frac=1, random_state=SEED).head(n)


def main():
    med = pd.read_csv(DATA / "medium.csv")
    post = pd.read_csv(DATA / "posters.csv", usecols=["id", "title", "year"])
    paths: dict[int, str] = {}
    hm = DATA / "horror_movies.csv"
    if hm.exists():
        for r in pd.read_csv(hm, usecols=lambda c: c in {"id", "poster_path"}).itertuples(index=False):
            p = getattr(r, "poster_path", None)
            if isinstance(p, str) and p.startswith("/"):
                paths[int(r.id)] = p

    # medium already has year; prefer posters title
    df = med.drop(columns=["year"], errors="ignore").merge(post, on="id", how="inner")
    df = df.dropna(subset=["p_painted", "year", "title"])
    df["year"] = df["year"].astype(int)
    df["proposed"] = df["p_painted"].apply(lambda x: "painted" if x >= 0.5 else "photo")

    mid = df[(df.p_painted >= MID[0]) & (df.p_painted <= MID[1])]
    painted = df[df.p_painted >= HI_PAINTED]
    photo = df[df.p_painted <= HI_PHOTO]

    sample = pd.concat([
        stratified(mid, N_MID),
        stratified(painted, N_PAINTED),
        stratified(photo, N_PHOTO),
    ]).drop_duplicates("id")
    sample = sample.sample(frac=1, random_state=SEED)

    rows = []
    missing_path = 0
    for r in sample.itertuples(index=False):
        path = paths.get(int(r.id))
        if not path:
            missing_path += 1
        rows.append({
            "id": int(r.id),
            "title": str(r.title),
            "year": int(r.year),
            "p": round(float(r.p_painted), 4),
            "proposed": r.proposed,
            "band": (
                "mid" if MID[0] <= r.p_painted <= MID[1]
                else ("painted_hi" if r.p_painted >= HI_PAINTED else "photo_hi")
            ),
            "path": path,
        })

    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    html = HTML_TEMPLATE.replace("__N__", str(len(rows))).replace("__DATA__", payload)
    OUT.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT} ({len(rows)} posters, {len(rows)-missing_path} with TMDB path)")
    print(sample.groupby(
        sample.p_painted.apply(
            lambda x: "mid" if MID[0] <= x <= MID[1]
            else ("painted_hi" if x >= HI_PAINTED else "photo_hi")
        )
    ).size().to_string())


HTML_TEMPLATE = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Label QA — painted vs photo (__N__)</title>
<style>
:root{--bg:#0a0a0c;--bg2:#141416;--ink:#e8e4da;--dim:#9a958a;--line:#2a2a30;
  --blood:#c1121f;--amber:#e5a00d;--ok:#3d9a6a;--bad:#c1121f;--doubt:#c4a35a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"Source Serif 4",Georgia,serif;min-height:100vh}
.wrap{max-width:980px;margin:0 auto;padding:20px 20px 80px}
.top{display:flex;flex-wrap:wrap;gap:12px 20px;align-items:baseline;
  border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:18px}
h1{font-family:"Anton",Impact,sans-serif;font-size:28px;letter-spacing:.02em;
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
.year{font-family:ui-monospace,Menlo,monospace;color:var(--amber);font-size:13px;margin-bottom:18px}
.badge{display:inline-block;font-family:ui-monospace,Menlo,monospace;font-size:12px;
  letter-spacing:.08em;text-transform:uppercase;padding:6px 10px;border-radius:3px;
  border:1px solid var(--line);margin-right:8px;margin-bottom:8px}
.badge.painted{color:#f0d9a8;border-color:#6a5630;background:#1a1610}
.badge.photo{color:#a8c4f0;border-color:#30466a;background:#10141a}
.badge.mid{color:var(--doubt)}
.badge.painted_hi,.badge.photo_hi{color:var(--dim)}
.score{font-size:42px;font-family:"Anton",Impact,sans-serif;color:var(--amber);margin:8px 0 4px}
.hint{color:var(--dim);font-size:14px;line-height:1.45;max-width:36em;margin:0 0 22px}
.actions{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0}
.actions button{font-family:ui-monospace,Menlo,monospace;font-size:13px;letter-spacing:.04em;
  border:1px solid var(--line);background:var(--bg2);color:var(--ink);padding:12px 16px;
  border-radius:4px;cursor:pointer}
.actions button:hover{border-color:#555}
.actions button.ok{border-color:#2d6a4a;color:#8fd4ad}
.actions button.bad{border-color:#7a1a22;color:#f0a0a8}
.actions button.doubt{border-color:#6a5630;color:#e5c97a}
.actions button.nav{opacity:.85}
.keys{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--dim);line-height:1.6}
kbd{background:#1a1a1e;border:1px solid #333;border-radius:3px;padding:1px 5px;color:var(--ink)}
.verdict{font-family:ui-monospace,Menlo,monospace;font-size:13px;margin-top:14px;min-height:1.2em}
.verdict.correct{color:var(--ok)}.verdict.incorrect{color:var(--bad)}.verdict.doubtful{color:var(--doubt)}
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
    <h1>Painted vs photo</h1>
    <span class="meta" id="counter">0 / __N__</span>
    <div class="progress" aria-hidden="true"><i id="bar"></i></div>
  </div>
  <div class="filter" id="filters">
    <button type="button" data-f="all" class="on">all</button>
    <button type="button" data-f="mid">uncertain mid</button>
    <button type="button" data-f="painted_hi">confident painted</button>
    <button type="button" data-f="photo_hi">confident photo</button>
    <button type="button" data-f="todo">unreviewed</button>
    <button type="button" data-f="done">reviewed</button>
  </div>
  <div class="stage">
    <img class="poster" id="poster" alt="">
    <div class="panel">
      <h2 id="title">—</h2>
      <div class="year" id="year">—</div>
      <div>
        <span class="badge" id="propBadge">—</span>
        <span class="badge" id="bandBadge">—</span>
      </div>
      <div class="score" id="score">—</div>
      <p class="hint">¿La etiqueta propuesta describe el <em>medio</em> del arte (ilustración/pintura vs fotografía)?
        No juzgues el género ni la calidad — solo painted vs photo. Casos mixtos → doubtful.
        El progreso se guarda en este navegador; exportá el CSV al terminar.</p>
      <div class="actions">
        <button type="button" class="ok" id="btnOk" title="1">1 · Correcta</button>
        <button type="button" class="bad" id="btnBad" title="2">2 · Incorrecta (flip)</button>
        <button type="button" class="doubt" id="btnDoubt" title="3">3 · Dudosa</button>
        <button type="button" class="nav" id="btnPrev" title="←">← Prev</button>
        <button type="button" class="nav" id="btnNext" title="→">Next →</button>
      </div>
      <div class="verdict" id="verdict"></div>
      <p class="keys">Atajos: <kbd>1</kbd> correcta · <kbd>2</kbd> incorrecta · <kbd>3</kbd> dudosa ·
        <kbd>←</kbd><kbd>→</kbd> navegar · <kbd>U</kbd> deshacer</p>
    </div>
  </div>
  <div class="toolbar">
    <button type="button" id="btnExport">Exportar CSV (veredictos)</button>
    <button type="button" id="btnGold">Exportar gold set (solo correctas)</button>
    <button type="button" id="btnClear">Borrar progreso local</button>
    <span class="status" id="status"></span>
  </div>
</div>
<script>
const DATA = __DATA__;
const STORE = "aof-label-qa-painted-v1";
let filter = "all";
let idx = 0;
let verdicts = {};
try { verdicts = JSON.parse(localStorage.getItem(STORE) || "{}") || {}; } catch(e){ verdicts = {}; }

function save(){ localStorage.setItem(STORE, JSON.stringify(verdicts)); updateStatus(); }

function filtered(){
  return DATA.filter(d => {
    const v = verdicts[d.id];
    if(filter==="mid") return d.band==="mid";
    if(filter==="painted_hi") return d.band==="painted_hi";
    if(filter==="photo_hi") return d.band==="photo_hi";
    if(filter==="todo") return !v;
    if(filter==="done") return !!v;
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
  const pb = document.getElementById("propBadge");
  pb.textContent = "proposed: " + d.proposed;
  pb.className = "badge " + d.proposed;
  const bb = document.getElementById("bandBadge");
  bb.textContent = d.band.replace("_"," ");
  bb.className = "badge " + d.band;
  document.getElementById("score").textContent = "p_painted " + d.p.toFixed(3);
  const v = verdicts[d.id];
  const verd = document.getElementById("verdict");
  if(!v){ verd.textContent = "Sin revisar"; verd.className = "verdict"; }
  else {
    const flip = v.verdict==="incorrect" ? (" → " + (d.proposed==="painted"?"photo":"painted")) : "";
    verd.textContent = v.verdict + flip + (v.final ? " · final=" + v.final : "");
    verd.className = "verdict " + v.verdict;
  }
  document.getElementById("counter").textContent = (idx+1) + " / " + list.length + "  (set " + DATA.length + ")";
  const done = DATA.filter(x => verdicts[x.id]).length;
  document.getElementById("bar").style.width = (100 * done / DATA.length) + "%";
  updateStatus();
}

function setVerdict(kind){
  const list = filtered();
  if(!list.length) return;
  const d = list[idx];
  let final = d.proposed;
  if(kind==="incorrect") final = d.proposed==="painted" ? "photo" : "painted";
  if(kind==="doubtful") final = "";
  verdicts[d.id] = {
    id: d.id, title: d.title, year: d.year, p: d.p,
    proposed: d.proposed, band: d.band,
    verdict: kind, final: final, ts: Date.now()
  };
  save();
  // advance
  if(idx < list.length - 1) idx++;
  show();
}

function undo(){
  const list = filtered();
  if(!list.length) return;
  const d = list[idx];
  delete verdicts[d.id];
  save(); show();
}

function updateStatus(){
  const n = DATA.length;
  const done = DATA.filter(d => verdicts[d.id]).length;
  const ok = DATA.filter(d => verdicts[d.id]?.verdict==="correct").length;
  const bad = DATA.filter(d => verdicts[d.id]?.verdict==="incorrect").length;
  const doubt = DATA.filter(d => verdicts[d.id]?.verdict==="doubtful").length;
  document.getElementById("status").textContent =
    done + "/" + n + " · ok " + ok + " · flip " + bad + " · doubt " + doubt;
}

function toCSV(rows){
  const cols = ["id","title","year","p_painted","proposed","band","verdict","final_label"];
  const esc = s => '"' + String(s).replace(/"/g,'""') + '"';
  const lines = [cols.join(",")];
  rows.forEach(r => {
    lines.push([r.id, esc(r.title), r.year, r.p, r.proposed, r.band, r.verdict, r.final||""].join(","));
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

document.getElementById("btnOk").onclick = () => setVerdict("correct");
document.getElementById("btnBad").onclick = () => setVerdict("incorrect");
document.getElementById("btnDoubt").onclick = () => setVerdict("doubtful");
document.getElementById("btnPrev").onclick = () => { idx--; show(); };
document.getElementById("btnNext").onclick = () => { idx++; show(); };
document.getElementById("btnExport").onclick = () => {
  const rows = Object.values(verdicts);
  if(!rows.length){ alert("Aún no hay veredictos"); return; }
  download("label_qa_painted.csv", toCSV(rows));
};
document.getElementById("btnGold").onclick = () => {
  const rows = Object.values(verdicts).filter(v => v.verdict==="correct" && v.final);
  if(!rows.length){ alert("No hay correctas aún"); return; }
  download("label_qa_painted_gold.csv", toCSV(rows));
};
document.getElementById("btnClear").onclick = () => {
  if(confirm("¿Borrar todo el progreso guardado en este navegador?")){
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
  if(e.key==="1") setVerdict("correct");
  else if(e.key==="2") setVerdict("incorrect");
  else if(e.key==="3") setVerdict("doubtful");
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
