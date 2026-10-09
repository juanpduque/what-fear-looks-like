#!/usr/bin/env python3
"""Reconcile creature chain; write published labels for the Jev pilot.

  python3 jev_labels.py

Reads results.csv (latest ok row per id×question). Writes labels.csv with
raw present/type plus published (reconciled) columns. Isolation mismatches
are kept as flags, not overwritten in results.csv.

Rule (see jev_battery.reconcile_creature):
  type=none → present=no (Smile)
  present=no + masked_killer → no/none (Halloween knife)
  present=no + other type → yes + type (Alien egg)
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from jev_battery import reconcile_creature

PIPE = Path(__file__).resolve().parent
OUT = PIPE / "data" / "qa" / "jev_pilot"
JEV_FULL_RESULTS = PIPE / "data" / "qa" / "jev_full" / "results_qwen3vl235b.csv"


def latest_ok(results: pd.DataFrame) -> pd.DataFrame:
    ok = results[results["status"] == "ok"].copy()
    ok["id"] = ok["id"].astype(int)
    return ok.drop_duplicates(subset=["id", "question"], keep="last")


def published_creatures(results_path: Path | None = None) -> dict[int, tuple[str, str]]:
    """Latest ok present/type per id, reconciled. Empty dict if the CSV is missing."""
    path = Path(results_path) if results_path else JEV_FULL_RESULTS
    if not path.is_file():
        return {}
    results = pd.read_csv(path, usecols=["id", "question", "pred", "status"])
    ok = latest_ok(results)
    ok = ok[ok["question"].isin(("creature_present", "creature_type"))]
    wide = ok.pivot_table(index="id", columns="question", values="pred", aggfunc="last")
    out: dict[int, tuple[str, str]] = {}
    for pid, r in wide.iterrows():
        raw_p = None if pd.isna(r.get("creature_present")) else str(r.get("creature_present"))
        raw_t = None if pd.isna(r.get("creature_type")) else str(r.get("creature_type"))
        pub_p, pub_t = reconcile_creature(raw_p, raw_t)
        if pub_p or pub_t:
            out[int(pid)] = (pub_p or "", pub_t or "")
    return out


def main() -> None:
    results = pd.read_csv(OUT / "results.csv")
    ok = latest_ok(results)
    wide = ok.pivot_table(index="id", columns="question", values="pred", aggfunc="last")
    p_wide = ok.pivot_table(index="id", columns="question", values="p_pred", aggfunc="last")
    p_wide = p_wide.add_prefix("p_")

    rows = []
    n_flip = 0
    for pid, r in wide.iterrows():
        raw_p = None if pd.isna(r.get("creature_present")) else str(r.get("creature_present"))
        raw_t = None if pd.isna(r.get("creature_type")) else str(r.get("creature_type"))
        pub_p, pub_t = reconcile_creature(raw_p, raw_t)
        flipped = (pub_p != raw_p) or (pub_t != raw_t)
        n_flip += int(flipped)
        rec = {
            "id": int(pid),
            "creature_present_raw": raw_p or "",
            "creature_type_raw": raw_t or "",
            "creature_present": pub_p or "",
            "creature_type": pub_t or "",
            "creature_flipped": int(flipped),
            "medium": "" if pd.isna(r.get("medium")) else str(r.get("medium")),
            "blood": "" if pd.isna(r.get("blood")) else str(r.get("blood")),
            "title_band": "" if pd.isna(r.get("title_band")) else str(r.get("title_band")),
            "sheet_kind": "" if pd.isna(r.get("sheet_kind")) else str(r.get("sheet_kind")),
            "lettering": "" if pd.isna(r.get("lettering")) else str(r.get("lettering")),
        }
        prow = p_wide.loc[pid] if pid in p_wide.index else None
        for col in (
            "p_creature_present",
            "p_creature_type",
            "p_medium",
            "p_blood",
            "p_title_band",
            "p_sheet_kind",
        ):
            if prow is None or col not in p_wide.columns or pd.isna(prow.get(col)):
                rec[col] = ""
            else:
                rec[col] = prow[col]
        rows.append(rec)

    labels = pd.DataFrame(rows).sort_values("id")
    dest = OUT / "labels.csv"
    labels.to_csv(dest, index=False)
    print(f"wrote {dest} n={len(labels)} flipped={n_flip}", flush=True)
    flips = labels[labels["creature_flipped"] == 1]
    if len(flips):
        print("flips:", flush=True)
        for _, r in flips.iterrows():
            print(
                f"  {int(r['id'])} {r['creature_present_raw']}/{r['creature_type_raw']}"
                f" → {r['creature_present']}/{r['creature_type']}",
                flush=True,
            )

    gold_path = OUT / "gold.json"
    if gold_path.is_file():
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        gold_ids = {int(k) for k in gold if str(k).isdigit()}
        g = labels[labels["id"].isin(gold_ids)]
        n_p = n_t = hit_p = hit_t = 0
        for _, r in g.iterrows():
            spec = gold[str(int(r["id"]))]
            if spec.get("creature_present"):
                n_p += 1
                hit_p += int(r["creature_present"] == spec["creature_present"])
            okset = set(spec.get("creature_ok") or [])
            if spec.get("creature_type") or okset:
                n_t += 1
                pred = r["creature_type"]
                hit_t += int(pred in okset or pred == spec.get("creature_type"))
        print(f"gold reconciled present {hit_p}/{n_p} type {hit_t}/{n_t}", flush=True)


if __name__ == "__main__":
    main()
