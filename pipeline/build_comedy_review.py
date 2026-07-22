#!/usr/bin/env python3
"""Build a manual review page for TMDB Comedy-tagged horror posters.

Default: all checked = exclude from corpus. Uncheck the ones you want to KEEP.

  python3 build_comedy_review.py
  open ../site/comedy-review.html
"""
from __future__ import annotations

import html
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = ROOT.parent / "site" / "comedy-review.html"
POSTERS = DATA / "posters"


def main():
    posts = pd.read_csv(DATA / "posters.csv", usecols=["id", "title", "year"])
    hm = pd.read_csv(
        DATA / "horror_movies.csv",
        usecols=lambda c: c in {
            "id", "title", "release_date", "poster_path", "vote_count",
            "popularity", "genre_names",
        },
    )
    hm["id"] = hm["id"].astype(int)
    posts["id"] = posts["id"].astype(int)
    m = posts.merge(hm, on="id", how="left", suffixes=("", "_hm"))

    def has_comedy(g):
        if not isinstance(g, str):
            return False
        return "Comedy" in {x.strip() for x in g.split(",")}

    d = m[m["genre_names"].map(has_comedy)].copy()
    d["year"] = d["year"].fillna(0).astype(int)
    d["vote_count"] = d["vote_count"].fillna(0).astype(int)
    d["popularity"] = d["popularity"].fillna(0).astype(float)
    d["decade"] = (d["year"] // 10) * 10
    d = d.sort_values(["decade", "year", "title"])

    cards = []
    prev_dec = None
    for r in d.itertuples(index=False):
        dec = int(r.decade)
        if dec != prev_dec:
            cards.append(f'<div class="dec-head">{dec}s</div>')
            prev_dec = dec
        title = html.escape(str(r.title))
        genres = html.escape(str(r.genre_names or ""))
        path = r.poster_path if isinstance(r.poster_path, str) and r.poster_path.startswith("/") else ""
        local = POSTERS / f"{int(r.id)}.jpg"
        if path:
            img = f"https://image.tmdb.org/t/p/w342{path}"
        elif local.exists():
            img = f"../pipeline/data/posters/{int(r.id)}.jpg"
        else:
            img = ""
        img_tag = (
            f'<img loading="lazy" src="{img}" alt="{title}">'
            if img else '<div class="noimg">sin póster</div>'
        )
        votes = int(r.vote_count)
        cards.append(f"""<div class="card checked" data-id="{int(r.id)}" data-votes="{votes}" data-year="{int(r.year)}">
  <label>
    <input type="checkbox" class="rm" value="{int(r.id)}" checked
      onchange="onToggle(this)">
    {img_tag}
    <div class="cap"><b>{title}</b><br>{int(r.year)} · votos {votes}<br>
      <span class="g">{genres}</span></div>
  </label>
</div>""")

    n = len(d)
    body = "\n".join(cards)
    page = TEMPLATE.replace("__N__", str(n)).replace("__CARDS__", body)
    OUT.write_text(page, encoding="utf-8")
    print(f"Wrote {OUT} ({n} comedy-tagged posters in current corpus)")
    print(d.groupby("decade").size().to_string())


TEMPLATE = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Revisión Comedy (__N__)</title>
<style>
body{background:#0a0a0c;color:#e8e4da;font-family:-apple-system,BlinkMacSystemFont,sans-serif;margin:0;padding:24px}
h1{font-size:20px;font-weight:600;margin:0 0 8px}
.lead{color:#9a958a;font-size:13px;max-width:760px;line-height:1.45;margin:0 0 16px}
.toolbar{position:sticky;top:0;background:#0a0a0c;padding:12px 0;z-index:10;
  border-bottom:1px solid #2a2a30;margin-bottom:16px;display:flex;gap:10px;align-items:center;
  flex-wrap:wrap;font-size:13px}
.toolbar button{background:#1a1a1e;color:#e8e4da;border:1px solid #3a3a40;border-radius:4px;
  padding:6px 12px;cursor:pointer;font-size:12px}
.toolbar button:hover{background:#2a2a30}
.toolbar button.primary{border-color:#6a5630;color:#f0d9a8}
#count{color:#e5a00d} #keep{color:#8fd4ad}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:14px}
.card{background:#141416;border-radius:6px;overflow:hidden;border:1px solid #222}
.card img,.card .noimg{width:100%;aspect-ratio:2/3;object-fit:cover;display:block;background:#1a1a1e}
.card .noimg{display:flex;align-items:center;justify-content:center;color:#555;font-size:11px}
.cap{font-size:10px;line-height:1.3;color:#9a958a;padding:6px 7px}
.cap b{color:#e8e4da;font-size:11px}
.cap .g{opacity:.75}
label{display:block;cursor:pointer;position:relative}
input.rm{position:absolute;top:6px;left:6px;width:18px;height:18px;z-index:2;accent-color:#c1121f}
.card.checked{outline:2px solid #c1121f}
.card.checked img,.card.checked .noimg{opacity:.4}
.card:not(.checked){outline:2px solid #2d6a4a}
.dec-head{grid-column:1/-1;font-size:13px;letter-spacing:.08em;text-transform:uppercase;
  color:#e5a00d;margin:22px 0 4px;border-bottom:1px solid #2a2a30;padding-bottom:4px}
.toast{position:fixed;bottom:18px;right:18px;background:#1a3a28;color:#b8f0cf;border:1px solid #2d6a4a;
  padding:10px 14px;border-radius:4px;font-size:12px;opacity:0;transition:opacity .2s;pointer-events:none}
.toast.show{opacity:1}
</style>
</head>
<body>
<div class="toolbar">
  <span><b id="count">0</b> quitar · <b id="keep">0</b> conservar · de __N__</span>
  <button class="primary" onclick="exportExclude()">Exportar CSV a quitar</button>
  <button onclick="exportKeep()">Exportar CSV a conservar</button>
  <button onclick="copyIds(true)">Copiar IDs a quitar</button>
  <button onclick="markAll(true)">Marcar todas (quitar)</button>
  <button onclick="markAll(false)">Desmarcar todas (conservar)</button>
  <button onclick="markLowVotes()">Marcar &lt;20 votos</button>
  <button onclick="clearSaved()">Reset guardado</button>
</div>
<h1>__N__ pósters con género oficial “Comedy” (TMDB)</h1>
<p class="lead">
  Checkbox marcado = <b>quitar</b> del corpus (rojo). Desmarcado = <b>conservar</b> (verde),
  para horror-comedias que sí aportan al análisis del miedo.
  Por defecto vienen todas marcadas para quitar. Tu selección se guarda en este navegador.
</p>
<div class="grid">
__CARDS__
</div>
<div class="toast" id="toast"></div>
<script>
const STORE = "aof-comedy-review-v1";
const TOTAL = __N__;

function toast(msg){
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 1600);
}

function onToggle(el){
  el.closest(".card").classList.toggle("checked", el.checked);
  save();
  updateCount();
}

function selectedExclude(){
  return [...document.querySelectorAll(".rm:checked")].map(c => +c.value);
}
function selectedKeep(){
  return [...document.querySelectorAll(".rm:not(:checked)")].map(c => +c.value);
}

function updateCount(){
  const ex = selectedExclude().length;
  document.getElementById("count").textContent = ex;
  document.getElementById("keep").textContent = TOTAL - ex;
}

function save(){
  const state = {};
  document.querySelectorAll(".rm").forEach(c => { state[c.value] = c.checked; });
  localStorage.setItem(STORE, JSON.stringify(state));
}

function restore(){
  let state = null;
  try { state = JSON.parse(localStorage.getItem(STORE) || "null"); } catch(e){ state = null; }
  if(!state){ updateCount(); return; }
  document.querySelectorAll(".rm").forEach(c => {
    if(state[c.value] != null){
      c.checked = !!state[c.value];
      c.closest(".card").classList.toggle("checked", c.checked);
    }
  });
  updateCount();
}

function markAll(on){
  document.querySelectorAll(".rm").forEach(c => {
    c.checked = on;
    c.closest(".card").classList.toggle("checked", on);
  });
  save(); updateCount();
}

function markLowVotes(){
  document.querySelectorAll(".card").forEach(card => {
    const v = +card.dataset.votes;
    const c = card.querySelector(".rm");
    if(v < 20){
      c.checked = true;
      card.classList.add("checked");
    }
  });
  save(); updateCount();
}

function clearSaved(){
  if(!confirm("¿Borrar la selección guardada y volver a marcar todas para quitar?")) return;
  localStorage.removeItem(STORE);
  markAll(true);
  toast("Reiniciado");
}

function metaFor(id){
  const card = document.querySelector('.card[data-id="'+id+'"]');
  const b = card ? card.querySelector(".cap b") : null;
  const year = card ? card.dataset.year : "";
  return {id, title: b ? b.textContent : "", year};
}

function toCSV(rows){
  const cols = ["id","title","year"];
  const esc = v => '"' + String(v??"").replaceAll('"','""') + '"';
  return [cols.join(",")].concat(rows.map(r => cols.map(c => esc(r[c])).join(","))).join("\n");
}

function download(name, text){
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], {type:"text/csv"}));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

function exportExclude(){
  const rows = selectedExclude().map(metaFor);
  download("excluded_comedy_review.csv", toCSV(rows));
  toast(rows.length + " a quitar → CSV");
}
function exportKeep(){
  const rows = selectedKeep().map(metaFor);
  download("kept_comedy_review.csv", toCSV(rows));
  toast(rows.length + " a conservar → CSV");
}
function copyIds(exclude){
  const ids = (exclude ? selectedExclude() : selectedKeep()).join("\n");
  navigator.clipboard.writeText(ids).then(() => toast("IDs copiados")).catch(() => {
    prompt("Copia:", ids);
  });
}

restore();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
