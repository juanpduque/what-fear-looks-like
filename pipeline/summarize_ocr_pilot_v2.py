#!/usr/bin/env python3
"""Summarize OCR pilot v2 results for Medium (exploratory, n≈100).

Reads data/qa/ocr_pilot_v2/results.csv and writes:
  summary.csv  — per-model metrics + bootstrap CI
  summary.md   — Spanish caveats + ranking table

  python3 summarize_ocr_pilot_v2.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ocr_metrics import (
    bootstrap_mean_ci,
    title_fuzzy_score,
    title_hit,
    title_overlap_score,
)

DATA = Path(__file__).resolve().parent / "data"
DEFAULT_OUT = DATA / "qa" / "ocr_pilot_v2"

MODEL_ORDER = [
    "claude",
    "gpt4o",
    "gemini-flash",
    "nova-pro",
    "nova-lite",
    "nova-2-lite",
    "pixtral",
    "llama4-scout",
    "gemma3",
    "qwen",
    "google",
    "qianfan",
    "paddle",
    "rekognition",
    "ppocr",
    "deepseek",
    "got",
    "easyocr",
    "florence",
]

COST_NOTES = {
    "claude": "~$0.003–0.02/img (Bedrock Claude Sonnet vision; Marketplace card required)",
    "gpt4o": "~$0.01–0.05/img (OpenAI gpt-4o vision detail=high; ~$2.50/1M in + $10/1M out; rough)",
    "gemini-flash": "~$0.0005–0.002/img (Vertex gemini-2.5-flash vision, thinkingBudget=0; rough)",
    "nova-lite": "~$0.0001–0.001/img (Bedrock Nova Lite vision, rough; first-party credits)",
    "nova-pro": "~$0.001–0.01/img (Bedrock Nova Pro vision, rough; first-party credits)",
    "nova-2-lite": "~$0.0001–0.001/img (Bedrock Nova 2 Lite vision, rough; first-party credits)",
    "pixtral": "~$0.001–0.01/img (Bedrock Pixtral Large vision, rough)",
    "llama4-scout": "~$0.0005–0.005/img (Bedrock Llama 4 Scout vision, rough)",
    "gemma3": "~$0.0001–0.001/img (Bedrock Gemma 3 4B vision, rough)",
    "google": "~$0.0015/img (Vision TEXT_DETECTION, rough)",
    "rekognition": "~$0.0015/img (DetectText, rough)",
    "easyocr": "cached corpus OCR (no incremental API cost)",
    "ppocr": "local CPU/self-host (EC2 time if remote)",
    "florence": "local/self-host (EC2 or laptop GPU/MPS time)",
    "got": "HF self-host on GPU EC2 (g4dn time)",
    "deepseek": "HF self-host on GPU EC2 (g4dn time)",
    "paddle": "HF self-host on GPU EC2 (g4dn time)",
    "qianfan": "HF self-host on GPU EC2 (g4dn time; larger VRAM risk)",
    "qwen": "HF self-host on GPU EC2 (g4dn time)",
}


def _raw_text(s: str) -> str:
    return str(s or "").replace("\\n", "\n")


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["title_overlap_score"] = pd.to_numeric(out["title_overlap_score"], errors="coerce")
    out["chars"] = pd.to_numeric(out["chars"], errors="coerce")
    out["latency_s"] = pd.to_numeric(out["latency_s"], errors="coerce")
    # recompute overlap + fuzzy from text for consistency
    fuzzy = []
    hits = []
    overlaps = []
    for _, r in out.iterrows():
        ok = str(r.get("status") or "") == "ok"
        text = _raw_text(r.get("text") or "") if ok else ""
        title = str(r.get("title") or "")
        if ok:
            overlaps.append(title_overlap_score(text, title))
            fuzzy.append(title_fuzzy_score(text, title))
            hits.append(1 if title_hit(text, title) else 0)
        else:
            overlaps.append(0.0)
            fuzzy.append(0.0)
            hits.append(0)
    out["title_overlap_score"] = overlaps
    out["title_fuzzy_score"] = fuzzy
    out["title_hit"] = hits
    return out


def summarize_model(g: pd.DataFrame, seed: int = 42) -> dict:
    n = len(g)
    ok = g["status"].astype(str).eq("ok")
    n_ok = int(ok.sum())
    ov_all = g["title_overlap_score"].astype(float)
    mean_ov, lo, hi = bootstrap_mean_ci(ov_all, n_resamples=1000, seed=seed)
    ov_ok = g.loc[ok, "title_overlap_score"].astype(float)
    std_ov = float(ov_ok.std(ddof=1)) if n_ok > 1 else 0.0
    mean_fuzzy = float(g.loc[ok, "title_fuzzy_score"].mean()) if n_ok else float("nan")
    hit_rate = float(g.loc[ok, "title_hit"].mean()) if n_ok else float("nan")
    mean_chars = float(g.loc[ok, "chars"].mean()) if n_ok else float("nan")
    mean_lat = float(g.loc[ok, "latency_s"].mean()) if n_ok else float("nan")
    model = str(g["model"].iloc[0])
    return {
        "model": model,
        "n": n,
        "n_ok": n_ok,
        "ok_rate": round(n_ok / n, 4) if n else 0.0,
        "mean_overlap": round(mean_ov, 4),
        "std_overlap": round(std_ov, 4),
        "overlap_ci95_lo": round(lo, 4),
        "overlap_ci95_hi": round(hi, 4),
        "mean_fuzzy": round(mean_fuzzy, 4) if n_ok else None,
        "title_hit_rate": round(hit_rate, 4) if n_ok else None,
        "mean_chars": round(mean_chars, 1) if n_ok else None,
        "mean_latency_s": round(mean_lat, 3) if n_ok else None,
        "cost_note": COST_NOTES.get(model, "see notes"),
    }


def write_md(summary: pd.DataFrame, out_path: Path, n_sample: int) -> None:
    ranked = summary.sort_values("mean_overlap", ascending=False, na_position="last")
    lines = []
    lines.append("# OCR pilot v2 — resumen para Medium")
    lines.append("")
    lines.append("## Caveats (español)")
    lines.append("")
    lines.append(
        "Este benchmark es **exploratorio**, no un paper. Usamos **n≈100** pósters "
        "de terror (muestra estratificada por década y text_area alto/bajo, corpus "
        f"preferentemente en inglés, seed=42; n efectivo={n_sample}). "
        "La métrica principal es el solapamiento de tokens del título de catálogo "
        "en el OCR; la secundaria es fuzzy / «el título aparece» tras normalizar "
        "caracteres no alfanuméricos (útil cuando Florence pega tokens). "
        "Reportamos media ± desvío y un intervalo bootstrap 95% de la media de "
        "overlap. Costos de API son aproximados (~$0.0015/img para Google Vision / "
        "Rekognition); los VLM de Hugging Face se midieron en GPU EC2 y el costo "
        "es tiempo de instancia, no por imagen. No generalizar a otros géneros, "
        "idiomas o layouts sin una muestra más grande y un protocolo de anotación "
        "humana."
    )
    lines.append("")
    lines.append("## Ranking (mean title_overlap, all rows)")
    lines.append("")
    lines.append(
        "| rank | model | ok_rate | mean overlap ± std | bootstrap 95% CI | "
        "mean fuzzy | title_hit | mean chars | mean latency (s) | cost |"
    )
    lines.append("|---:|:---|---:|---:|---:|---:|---:|---:|---:|:---|")
    for i, r in enumerate(ranked.itertuples(index=False), 1):
        ci = f"[{r.overlap_ci95_lo:.3f}, {r.overlap_ci95_hi:.3f}]"
        ov = f"{r.mean_overlap:.3f} ± {r.std_overlap:.3f}"
        fuzzy = f"{r.mean_fuzzy:.3f}" if r.mean_fuzzy is not None else "—"
        hit = f"{r.title_hit_rate:.3f}" if r.title_hit_rate is not None else "—"
        chars = f"{r.mean_chars:.0f}" if r.mean_chars is not None else "—"
        lat = f"{r.mean_latency_s:.2f}" if r.mean_latency_s is not None else "—"
        lines.append(
            f"| {i} | {r.model} | {r.ok_rate:.2f} | {ov} | {ci} | "
            f"{fuzzy} | {hit} | {chars} | {lat} | {r.cost_note} |"
        )
    lines.append("")
    lines.append("## Notas de costo / latencia")
    lines.append("")
    lines.append(
        "- **API** (google, rekognition): ~$0.0015 por imagen; latencia de red "
        "dominante (~0.5–2 s típico)."
    )
    lines.append(
        "- **Gemini Flash** (Vertex `gemini-2.5-flash`, thinkingBudget=0): VLM "
        "multimodal vía ADC; coste ≈ tokens imagen+prompt+salida (~$0.0005–0.002/img "
        "rough); latencia de red/modelo (~1–4 s típico)."
    )
    lines.append(
        "- **GPT-4o** (OpenAI `gpt-4o`, vision `detail=high`, temperature=0): techo "
        "VLM de pago vía API; coste ≈ tokens imagen+prompt+salida "
        "(~$2.50/1M in + $10/1M out; ~$0.01–0.05/img rough con high detail); "
        "latencia de red/modelo (~1–5 s típico)."
    )
    lines.append(
        "- **Claude** (Bedrock Sonnet 4.5/4.6, Converse + imagen): techo VLM de pago; "
        "costo ≈ tokens de entrada (imagen + prompt) + salida; mucho más caro "
        "que Vision/Rekognition por imagen. Requiere instrumento de pago válido "
        "en AWS Marketplace para Anthropic (INVALID_PAYMENT_INSTRUMENT)."
    )
    lines.append(
        "- **Bedrock vision no-Anthropic** (nova-lite/pro, nova-2-lite, pixtral, "
        "llama4-scout, gemma3): Converse + imagen; Amazon Nova es first-party "
        "(créditos Bedrock aplican). Pixtral/Llama/Gemma son Marketplace pero "
        "en smoke no exigieron tarjeta como Claude."
    )
    lines.append(
        "- **EasyOCR**: reutilizado desde `poster_ocr.csv` (sin re-inferencia); "
        "latencia ≈ 0 en este piloto."
    )
    lines.append(
        "- **HF / self-host** (qwen, deepseek, paddle, qianfan, got, florence, ppocr): "
        "costo = tiempo de GPU/CPU (p. ej. g4dn.xlarge on-demand). Comparar "
        "latencia media por imagen en la tabla; OOM o load_error bajan ok_rate."
    )
    lines.append("")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    out = Path(args.out_dir)
    results = out / "results.csv"
    if not results.exists():
        raise SystemExit(f"missing {results}")

    df = enrich(pd.read_csv(results))
    rows = []
    models = list(df["model"].unique())
    ordered = [m for m in MODEL_ORDER if m in models] + sorted(
        m for m in models if m not in MODEL_ORDER
    )
    for i, m in enumerate(ordered):
        rows.append(summarize_model(df[df["model"] == m], seed=args.seed + i))
    summary = pd.DataFrame(rows)
    summary.to_csv(out / "summary.csv", index=False)

    n_sample = int(df["id"].nunique()) if len(df) else 0
    write_md(summary, out / "summary.md", n_sample)
    print(summary.to_string(index=False), flush=True)
    print(f"\nLISTO → {out / 'summary.csv'}", flush=True)
    print(f"LISTO → {out / 'summary.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
