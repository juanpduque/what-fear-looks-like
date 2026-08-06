#!/usr/bin/env python3
"""Build OCR article ladders, ablations, and figures from existing QA pilots.

Outputs under data/qa/ocr_article/:
  ladder_n100.csv, ladder_hard12.csv, ablations.csv, winner.json, figures/*.png

Applies QA title overrides + exclude ids from:
  data/qa/ocr_qa_title_overrides.csv
  data/qa/ocr_qa_exclude_ids.csv
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ocr_metrics import title_overlap_score

PIPE = Path(__file__).resolve().parent
QA = PIPE / "data" / "qa"
OUT = QA / "ocr_article"
FIGS = OUT / "figures"

HARD_IDS_FILE = QA / "ocr_qwen_hard" / "sample_ids.txt"
OVERRIDES_CSV = QA / "ocr_qa_title_overrides.csv"
EXCLUDE_CSV = QA / "ocr_qa_exclude_ids.csv"


def load_title_overrides() -> dict[int, str]:
    if not OVERRIDES_CSV.exists():
        return {}
    return {
        int(r["id"]): str(r["title"]).strip()
        for r in csv.DictReader(OVERRIDES_CSV.open(encoding="utf-8"))
    }


def load_exclude_ids() -> set[int]:
    if not EXCLUDE_CSV.exists():
        return set()
    return {
        int(r["id"])
        for r in csv.DictReader(EXCLUDE_CSV.open(encoding="utf-8"))
    }


TITLE_OVERRIDES = load_title_overrides()
EXCLUDE_IDS = load_exclude_ids()


def effective_title(pid: int, fallback: str = "") -> str:
    return TITLE_OVERRIDES.get(int(pid), fallback)


def rescore_row(r: dict | pd.Series, *, force: bool = False) -> float:
    """Score one result row.

    Prefer the stored title_overlap_score unless this id has a title override
    (or force=True). Historical pilot CSVs sometimes store literal ``\\n`` in
    the text field; re-tokenizing those drifts from the published ladder.
    """
    pid = int(r["id"])
    if force or pid in TITLE_OVERRIDES:
        title = effective_title(pid, str(r.get("title") or ""))
        text = str(r.get("text") or "").replace("\\n", "\n")
        if text.strip():
            return float(title_overlap_score(text, title))
    try:
        return float(r.get("title_overlap_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def rescore_hard_row(r: dict | pd.Series) -> float:
    """Hard-set scoring: stored score, except title-override ids."""
    return rescore_row(r, force=False)

# Rough mid-point USD/img for scatter (from summary cost_note heuristics)
COST_USD_PER_IMG = {
    "gpt4o": 0.03,
    "gemini-flash": 0.00125,
    "pixtral": 0.005,
    "llama4-scout": 0.0025,
    "nova-pro": 0.005,
    "nova-lite": 0.0005,
    "google": 0.0015,
    "rekognition": 0.0015,
    "qwen": 0.0008,  # amortized g4dn
    "deepseek": 0.001,
    "paddle": 0.002,
    "ppocr": 0.0002,
    "easyocr": 0.0001,
    "florence": 0.0008,
    "nova-pro": 0.005,
}


def load_hard_ids() -> list[int]:
    return [int(x) for x in HARD_IDS_FILE.read_text().split() if x.strip()]


def wtl(a: pd.Series, b: pd.Series, eps: float = 1e-9) -> tuple[int, int, int]:
    """Win/tie/loss of a vs b on aligned index."""
    win = tie = loss = 0
    for x, y in zip(a.tolist(), b.tolist()):
        if abs(x - y) <= eps:
            tie += 1
        elif x > y:
            win += 1
        else:
            loss += 1
    return win, tie, loss


def ladder_n100() -> pd.DataFrame:
    """Rescored n≈100 ladder with title overrides; excludes non-EN poster ids."""
    res = pd.read_csv(QA / "ocr_pilot_v2" / "results.csv")
    res["id"] = res["id"].astype(int)
    res = res[~res["id"].isin(EXCLUDE_IDS)].copy()
    res["status"] = res["status"].fillna("ok").astype(str)
    res = res[res["status"].isin(["ok", ""])].copy()
    res["title_overlap_score"] = res.apply(rescore_row, axis=1)

    # optional gemma31 full-v2 run
    gpath = QA / "ocr_pilot_v2_gemma31" / "results.csv"
    if gpath.exists():
        g = pd.read_csv(gpath)
        g["id"] = g["id"].astype(int)
        g = g[~g["id"].isin(EXCLUDE_IDS)].copy()
        g["status"] = g["status"].fillna("ok").astype(str)
        g = g[g["status"].isin(["ok", ""])].copy()
        g["title_overlap_score"] = g.apply(rescore_row, axis=1)
        res = pd.concat([res, g], ignore_index=True)

    rows = []
    for model, g in res.groupby("model"):
        vals = g["title_overlap_score"].astype(float)
        lat = pd.to_numeric(g.get("latency_s"), errors="coerce")
        rows.append(
            {
                "model": model,
                "n": int(len(g)),
                "n_ok": int(len(g)),
                "mean_overlap": round(float(vals.mean()), 4),
                "median_overlap": round(float(vals.median()), 4),
                "title_hit_rate": round(float((vals >= 1.0 - 1e-9).mean()), 4),
                "mean_latency_s": round(float(lat.mean()), 4) if lat.notna().any() else "",
                "cost_note": "",
            }
        )
    s = pd.DataFrame(rows)
    s = s[s["n_ok"] > 0].copy()
    s = s.sort_values("mean_overlap", ascending=False).reset_index(drop=True)
    s.insert(0, "rank", range(1, len(s) + 1))
    return s


def collect_hard_scores(hard_ids: list[int]) -> pd.DataFrame:
    """Long-form id, model, title_overlap_score for hard set (rescored)."""
    rows: list[dict] = []
    hard_set = set(hard_ids)

    def add(df: pd.DataFrame, model_map: dict[str, str] | None = None) -> None:
        df = df.copy()
        df["id"] = df["id"].astype(int)
        df = df[df["id"].isin(hard_set)]
        for _, r in df.iterrows():
            status = str(r.get("status") or "ok")
            if status not in ("ok", ""):
                continue
            m = str(r["model"])
            if model_map and m in model_map:
                m = model_map[m]
            elif model_map is not None and m not in model_map:
                continue
            rows.append(
                {
                    "id": int(r["id"]),
                    "model": m,
                    "title_overlap_score": rescore_hard_row(r),
                    "status": status,
                }
            )

    v2 = pd.read_csv(QA / "ocr_pilot_v2" / "results.csv")
    cloud_models = {
        "pixtral": "pixtral",
        "gpt4o": "gpt4o",
        "gemini-flash": "gemini-flash",
        "llama4-scout": "llama4-scout",
        "nova-lite": "nova-lite",
        "nova-pro": "nova-pro",
        "qwen": "qwen-v2",
        "google": "google",
        "rekognition": "rekognition",
        "deepseek": "deepseek",
        "paddle": "paddle-vl",
        "ppocr": "ppocr",
        "easyocr": "easyocr",
        "florence": "florence",
    }
    add(v2, cloud_models)

    for rel in (
        "ocr_qwen_hard/results.csv",
        "ocr_kimi_hard/results.csv",
        "ocr_ppocrv6_hard/results.csv",
        "ocr_qwen_hard_crop/results.csv",
        "ocr_hard12_openrouter/results.csv",
        "ocr_pilot_v2_gemma31/results.csv",
    ):
        path = QA / rel
        if path.exists():
            add(pd.read_csv(path))

    return pd.DataFrame(rows)


def ladder_hard12(scores: pd.DataFrame, hard_ids: list[int]) -> pd.DataFrame:
    g = (
        scores.groupby("model")["title_overlap_score"]
        .agg(n="count", mean_overlap="mean", median_overlap="median")
        .reset_index()
    )
    g = g[g["n"] >= len(hard_ids) - 1]  # allow 1 miss
    g = g.sort_values("mean_overlap", ascending=False).reset_index(drop=True)
    g.insert(0, "rank", range(1, len(g) + 1))

    # W/T/L vs best OSS among kimi / qwen7b
    pivot = scores.pivot_table(
        index="id", columns="model", values="title_overlap_score", aggfunc="first"
    )
    oss_candidates = [
        c
        for c in (
            "gemma4-31b-hard",
            "gemma4-31b",
            "kimi-vl-hard",
            "qwen7b-hard",
            "qwen2b-hard",
        )
        if c in pivot.columns
    ]
    best_oss_col = max(oss_candidates, key=lambda c: pivot[c].mean()) if oss_candidates else None
    ref = pivot[best_oss_col] if best_oss_col else None

    wtls = []
    for m in g["model"]:
        if ref is None or m not in pivot.columns:
            wtls.append({"win": "", "tie": "", "loss": "", "vs_oss": best_oss_col or ""})
            continue
        # align on intersection
        both = pivot[[m]].join(ref.rename("_ref"), how="inner").dropna()
        w, t, l = wtl(both[m], both["_ref"])
        wtls.append({"win": w, "tie": t, "loss": l, "vs_oss": best_oss_col})
    wtl_df = pd.DataFrame(wtls)
    out = pd.concat([g.reset_index(drop=True), wtl_df], axis=1)
    out["family"] = out["model"].map(_family)
    return out


def _family(model: str) -> str:
    m = model.lower()
    if m in {
        "pixtral",
        "gpt4o",
        "gemini-flash",
        "llama4-scout",
        "nova-lite",
        "nova-pro",
        "gemini-2.5-flash-or-hard",
    }:
        return "cloud"
    if m in {"google", "rekognition"}:
        return "classic_api"
    if "crop" in m:
        return "ablation_crop"
    if m in {"qwen-homolog"}:
        return "ablation_homolog"
    if m in {"ppocrv6-medium", "ppocr", "easyocr"}:
        return "classic_oss"
    if m.startswith("gemma") or "qwen3-vl" in m:
        return "vlm_oss"
    return "vlm_oss"


def ablations_table(hard_ids: list[int]) -> pd.DataFrame:
    rows = []

    # Homolog vs v2 qwen on intersection (35 ids in homolog run)
    hom = pd.read_csv(QA / "ocr_qwen_homolog" / "results.csv")
    hom["id"] = hom["id"].astype(int)
    hom["title_overlap_score"] = pd.to_numeric(hom["title_overlap_score"], errors="coerce")
    v2 = pd.read_csv(QA / "ocr_pilot_v2" / "results.csv")
    v2["id"] = v2["id"].astype(int)
    v2["title_overlap_score"] = pd.to_numeric(v2["title_overlap_score"], errors="coerce")
    qv2 = v2[v2["model"] == "qwen"].set_index("id")["title_overlap_score"]
    hh = hom.set_index("id")["title_overlap_score"]
    both = hh.to_frame("homolog").join(qv2.rename("w342"), how="inner").dropna()
    w, t, l = wtl(both["homolog"], both["w342"])
    rows.append(
        {
            "ablation": "homolog_letterbox_1000x1500",
            "model": "qwen-homolog",
            "baseline": "qwen-v2-w342",
            "n": len(both),
            "mean": round(both["homolog"].mean(), 4),
            "baseline_mean": round(both["w342"].mean(), 4),
            "delta_mean": round(both["homolog"].mean() - both["w342"].mean(), 4),
            "win": w,
            "tie": t,
            "loss": l,
            "verdict": "leve; mediana ya en techo",
        }
    )

    hard_scores = collect_hard_scores(hard_ids)
    pivot = hard_scores.pivot_table(
        index="id", columns="model", values="title_overlap_score", aggfunc="first"
    )

    def pair(name: str, model: str, baseline: str, verdict: str) -> None:
        if model not in pivot.columns or baseline not in pivot.columns:
            return
        both = pivot[[model, baseline]].dropna()
        w, t, l = wtl(both[model], both[baseline])
        rows.append(
            {
                "ablation": name,
                "model": model,
                "baseline": baseline,
                "n": len(both),
                "mean": round(both[model].mean(), 4),
                "baseline_mean": round(both[baseline].mean(), 4),
                "delta_mean": round(both[model].mean() - both[baseline].mean(), 4),
                "win": w,
                "tie": t,
                "loss": l,
                "verdict": verdict,
            }
        )

    pair("qwen7b_vs_qwen2b_hard", "qwen7b-hard", "qwen2b-hard", "7B ayuda en duros")
    pair("kimi_vs_qwen7b_hard", "kimi-vl-hard", "qwen7b-hard", "mejor OSS hard")
    pair("ppocrv6_vs_qwen7b_hard", "ppocrv6-medium", "qwen7b-hard", "no supera 7B")
    pair("crop_vs_full_qwen7b", "qwen7b-crop", "qwen7b-hard", "crop empeora")
    pair("crop_vs_full_qwen2b", "qwen2b-crop", "qwen2b-hard", "crop empeora")
    pair("pixtral_vs_kimi_hard", "pixtral", "kimi-vl-hard", "cloud gana en hard")
    pair("gpt4o_vs_kimi_hard", "gpt4o", "kimi-vl-hard", "cloud competitivo")
    pair("gemini_vs_kimi_hard", "gemini-flash", "kimi-vl-hard", "cloud competitivo")

    return pd.DataFrame(rows)


def pick_winner(hard_ladder: pd.DataFrame) -> dict:
    # Primary: highest mean among cloud on hard12
    cloud = hard_ladder[hard_ladder["family"] == "cloud"].copy()
    if cloud.empty:
        top = hard_ladder.iloc[0]
        primary = str(top["model"])
        reason = "no cloud rows; took overall #1"
    else:
        top = cloud.sort_values("mean_overlap", ascending=False).iloc[0]
        primary = str(top["model"])
        # tie-break: if within 0.005 of gemini-flash and gemini present, prefer gemini for cost
        # Plan says: highest mean; empate → Gemini Flash. Only apply if truly tied.
        gf = cloud[cloud["model"] == "gemini-flash"]
        if not gf.empty:
            gmean = float(gf.iloc[0]["mean_overlap"])
            if abs(float(top["mean_overlap"]) - gmean) < 1e-6:
                primary = "gemini-flash"
                top = gf.iloc[0]
        reason = (
            f"mayor mean_overlap en hard12 entre cloud "
            f"({float(top['mean_overlap']):.4f})"
        )

    best_oss = hard_ladder[hard_ladder["family"] == "vlm_oss"]
    best_oss_model = (
        str(best_oss.sort_values("mean_overlap", ascending=False).iloc[0]["model"])
        if not best_oss.empty
        else ""
    )

    return {
        "primary_cloud": primary,
        "primary_mean_hard12": round(float(top["mean_overlap"]), 4),
        "recipe": "full-frame poster, no crop, OCR/extract-all-text prompt",
        "best_oss_hard": best_oss_model,
        "reason": reason,
        "do_not": ["aggressive text crop", "PP-OCRv6 as primary", "homolog as main lever"],
    }


def style_bars() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "#faf9f7",
            "axes.edgecolor": "#333333",
            "axes.labelcolor": "#222222",
            "xtick.color": "#222222",
            "ytick.color": "#222222",
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.titleweight": "bold",
        }
    )


def fig_ladder_n100(df: pd.DataFrame) -> None:
    style_bars()
    # drop failed zeros already filtered
    plot = df.sort_values("mean_overlap", ascending=True)
    colors = [
        "#c45c26"
        if m in {"pixtral", "gpt4o", "gemini-flash", "llama4-scout"}
        else "#4a6fa5"
        if m in {"qwen", "deepseek", "paddle", "florence"}
        else "#6b6b6b"
        for m in plot["model"]
    ]
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.barh(plot["model"], plot["mean_overlap"], color=colors)
    ax.set_xlabel("mean title_overlap")
    n = int(plot["n"].max()) if "n" in plot.columns and len(plot) else 100
    ax.set_title(f"OCR pilot v2 — n={n} (QC: overrides + exclusiones)")
    ax.set_xlim(0, 1.05)
    ax.axvline(0.9, color="#999", ls="--", lw=0.8)
    fig.tight_layout()
    fig.savefig(FIGS / "ladder_n100.png", dpi=160)
    plt.close(fig)


def fig_ladder_hard(df: pd.DataFrame) -> None:
    style_bars()
    # focus on article-relevant models
    keep = {
        "pixtral",
        "gpt4o",
        "gemini-flash",
        "llama4-scout",
        "kimi-vl-hard",
        "qwen7b-hard",
        "ppocrv6-medium",
        "qwen2b-hard",
        "qwen7b-crop",
        "qwen-v2",
        "gemma4-31b",
        "gemma4-31b-hard",
        "gemini-2.5-flash-or-hard",
        "qwen3-vl-32b-hard",
        "gemma4-26b-free-hard",
    }
    plot = df[df["model"].isin(keep)].sort_values("mean_overlap", ascending=True)
    color_map = {
        "cloud": "#c45c26",
        "vlm_oss": "#4a6fa5",
        "classic_oss": "#6b6b6b",
        "ablation_crop": "#a33",
        "classic_api": "#888",
    }
    colors = [color_map.get(f, "#555") for f in plot["family"]]
    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.barh(plot["model"], plot["mean_overlap"], color=colors)
    ax.set_xlabel("mean title_overlap")
    n_hard = int(plot["n"].max()) if "n" in plot.columns and len(plot) else 0
    ax.set_title(f"Subset duro n={n_hard} (QC regenerado)")
    ax.set_xlim(0, 1.05)
    fig.tight_layout()
    fig.savefig(FIGS / "ladder_hard12.png", dpi=160)
    plt.close(fig)


def fig_cost_quality(n100: pd.DataFrame) -> None:
    style_bars()
    rows = []
    for _, r in n100.iterrows():
        m = r["model"]
        if m not in COST_USD_PER_IMG:
            continue
        rows.append((m, float(r["mean_overlap"]), COST_USD_PER_IMG[m]))
    if not rows:
        return
    labels, ys, xs = zip(*rows)
    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.scatter(xs, ys, s=80, c="#c45c26", zorder=3)
    for lab, x, y in zip(labels, xs, ys):
        ax.annotate(lab, (x, y), textcoords="offset points", xytext=(6, 4), fontsize=8)
    ax.set_xscale("log")
    ax.set_xlabel("costo estimado USD / imagen (log)")
    ax.set_ylabel("mean title_overlap (n=100)")
    ax.set_title("Costo × calidad (estimados del piloto)")
    ax.set_ylim(0.3, 1.0)
    ax.grid(True, which="both", ls=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(FIGS / "cost_vs_quality_n100.png", dpi=160)
    plt.close(fig)


def fig_ablations(abl: pd.DataFrame) -> None:
    style_bars()
    # key ablations only
    keys = [
        "homolog_letterbox_1000x1500",
        "crop_vs_full_qwen7b",
        "kimi_vs_qwen7b_hard",
        "ppocrv6_vs_qwen7b_hard",
        "pixtral_vs_kimi_hard",
    ]
    plot = abl[abl["ablation"].isin(keys)].copy()
    if plot.empty:
        return
    fig, ax = plt.subplots(figsize=(9, 4.5))
    y = np.arange(len(plot))
    colors = ["#2d6a4f" if d > 0 else "#9b2226" for d in plot["delta_mean"]]
    ax.barh(y, plot["delta_mean"], color=colors)
    ax.set_yticks(y)
    ax.set_yticklabels(plot["ablation"])
    ax.axvline(0, color="#333", lw=0.8)
    ax.set_xlabel("Δ mean title_overlap (modelo − baseline)")
    ax.set_title("Ablations: qué ayudó y qué no")
    fig.tight_layout()
    fig.savefig(FIGS / "ablations_delta.png", dpi=160)
    plt.close(fig)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    FIGS.mkdir(parents=True, exist_ok=True)
    hard_ids = load_hard_ids()
    if len(hard_ids) < 1:
        raise SystemExit(f"empty hard ids at {HARD_IDS_FILE}")
    print(
        f"hard n={len(hard_ids)} ids={hard_ids} "
        f"overrides={TITLE_OVERRIDES} exclude={sorted(EXCLUDE_IDS)}",
        flush=True,
    )

    n100 = ladder_n100()
    n100.to_csv(OUT / "ladder_n100.csv", index=False)

    scores = collect_hard_scores(hard_ids)
    scores.to_csv(OUT / "hard12_scores_long.csv", index=False)
    scores.to_csv(OUT / "hard_scores_long.csv", index=False)

    hard = ladder_hard12(scores, hard_ids)
    hard.to_csv(OUT / "ladder_hard12.csv", index=False)
    hard.to_csv(OUT / f"ladder_hard{len(hard_ids)}.csv", index=False)

    abl = ablations_table(hard_ids)
    abl.to_csv(OUT / "ablations.csv", index=False)

    winner = pick_winner(hard)
    winner["hard_n"] = len(hard_ids)
    winner["hard_ids"] = hard_ids
    winner["title_overrides"] = {str(k): v for k, v in TITLE_OVERRIDES.items()}
    winner["exclude_ids"] = sorted(EXCLUDE_IDS)
    (OUT / "winner.json").write_text(json.dumps(winner, indent=2) + "\n", encoding="utf-8")

    fig_ladder_n100(n100)
    fig_ladder_hard(hard)
    fig_cost_quality(n100)
    fig_ablations(abl)

    print("OUT", OUT)
    print("winner", json.dumps(winner, indent=2))
    print("hard top:")
    print(hard.head(8).to_string(index=False))
    print("n100 top:")
    print(n100.head(8).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
