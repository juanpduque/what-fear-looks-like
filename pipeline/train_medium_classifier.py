#!/usr/bin/env python3
"""Train painted/photo/composite classifier on CLIP embeddings + predict full corpus.

Uses gold labels from label_qa_medium_train.csv (final_label).
Does NOT overwrite labels or census — writes:
  data/qa/medium_clf/split.csv
  data/qa/medium_clf/metrics.json
  data/qa/medium_clf/model.joblib
  data/medium_pred.csv

Designed for CPU or GPU (g4dn). Embedding probe is the right model for N≈300.

  python3 train_medium_classifier.py
  python3 train_medium_classifier.py --embeddings /path/clip_embeddings.npz
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.model_selection import StratifiedShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

DATA = Path(__file__).resolve().parent / "data"
LABELS = DATA / "label_qa_medium_train.csv"
EMB = DATA / "clip_embeddings.npz"
OUT_DIR = DATA / "qa" / "medium_clf"
PRED = DATA / "medium_pred.csv"
CLASSES = ["painted", "photo", "composite"]
LABEL2ID = {c: i for i, c in enumerate(CLASSES)}


def load_embeddings(path: Path) -> tuple[np.ndarray, np.ndarray]:
    z = np.load(path, allow_pickle=True)
    ids = np.asarray(z["ids"], dtype=np.int64)
    vecs = np.asarray(z["vecs"], dtype=np.float32)
    # L2 normalize (CLIP cosine space)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.clip(norms, 1e-8, None)
    vecs = vecs / norms
    return ids, vecs


def load_labels(path: Path) -> dict[int, str]:
    out: dict[int, str] = {}
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            lab = (r.get("final_label") or "").strip().lower()
            if lab not in LABEL2ID:
                continue
            try:
                out[int(r["id"])] = lab
            except Exception:
                continue
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--labels", type=Path, default=LABELS)
    ap.add_argument("--embeddings", type=Path, default=EMB)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--pred-out", type=Path, default=PRED)
    ap.add_argument("--test-size", type=float, default=0.25)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--C", type=float, default=2.0)
    args = ap.parse_args()

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    ids, vecs = load_embeddings(args.embeddings)
    id_to_row = {int(i): r for r, i in enumerate(ids)}
    labels = load_labels(args.labels)

    X_list, y_list, lab_ids = [], [], []
    missing = []
    for pid, lab in labels.items():
        if pid not in id_to_row:
            missing.append(pid)
            continue
        X_list.append(vecs[id_to_row[pid]])
        y_list.append(LABEL2ID[lab])
        lab_ids.append(pid)
    X = np.stack(X_list)
    y = np.asarray(y_list, dtype=np.int64)
    lab_ids_a = np.asarray(lab_ids, dtype=np.int64)

    print(
        f"labeled={len(labels)} usable={len(lab_ids)} missing_emb={len(missing)} "
        f"class_counts={dict(Counter(CLASSES[i] for i in y))}",
        flush=True,
    )

    sss = StratifiedShuffleSplit(n_splits=1, test_size=args.test_size, random_state=args.seed)
    train_idx, test_idx = next(sss.split(X, y))

    split_path = out_dir / "split.csv"
    with split_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "label", "split"])
        w.writeheader()
        for i in train_idx:
            w.writerow({"id": int(lab_ids_a[i]), "label": CLASSES[int(y[i])], "split": "train"})
        for i in test_idx:
            w.writerow({"id": int(lab_ids_a[i]), "label": CLASSES[int(y[i])], "split": "test"})
    print(f"wrote {split_path} train={len(train_idx)} test={len(test_idx)}", flush=True)

    clf = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "lr",
                LogisticRegression(
                    C=args.C,
                    max_iter=2000,
                    multi_class="multinomial",
                    class_weight="balanced",
                    random_state=args.seed,
                ),
            ),
        ]
    )
    t0 = time.time()
    clf.fit(X[train_idx], y[train_idx])
    train_s = time.time() - t0

    y_pred = clf.predict(X[test_idx])
    y_proba = clf.predict_proba(X[test_idx])
    report = classification_report(
        y[test_idx],
        y_pred,
        labels=list(range(len(CLASSES))),
        target_names=CLASSES,
        output_dict=True,
        zero_division=0,
    )
    cm = confusion_matrix(y[test_idx], y_pred, labels=list(range(len(CLASSES)))).tolist()
    macro_f1 = float(f1_score(y[test_idx], y_pred, average="macro", zero_division=0))

    metrics = {
        "n_labeled_usable": int(len(lab_ids)),
        "n_missing_emb": int(len(missing)),
        "missing_emb_ids": missing,
        "train_size": int(len(train_idx)),
        "test_size": int(len(test_idx)),
        "train_seconds": round(train_s, 3),
        "macro_f1_test": macro_f1,
        "report": report,
        "confusion_matrix": cm,
        "classes": CLASSES,
        "model": "clip512_logreg_balanced",
        "seed": args.seed,
        "C": args.C,
        "test_size": args.test_size,
    }
    metrics_path = out_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"test macro_f1={macro_f1:.3f} train_s={train_s:.2f}", flush=True)
    print(classification_report(y[test_idx], y_pred, target_names=CLASSES, zero_division=0), flush=True)

    model_path = out_dir / "model.joblib"
    joblib.dump(
        {
            "pipeline": clf,
            "classes": CLASSES,
            "label2id": LABEL2ID,
            "metrics": metrics,
        },
        model_path,
    )
    print(f"wrote {model_path}", flush=True)

    # Full-corpus prediction
    print(f"predicting full corpus n={len(ids):,}…", flush=True)
    t1 = time.time()
    proba = clf.predict_proba(vecs)
    pred = proba.argmax(axis=1)
    conf = proba.max(axis=1)
    gold = {pid: lab for pid, lab in labels.items()}

    args.pred_out.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "id",
        "pred_label",
        "pred_confidence",
        "p_painted",
        "p_photo",
        "p_composite",
        "gold_label",
        "split",
    ]
    split_map = {}
    with split_path.open() as f:
        for r in csv.DictReader(f):
            split_map[int(r["id"])] = r["split"]

    with args.pred_out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, pid in enumerate(ids):
            pid = int(pid)
            row = {
                "id": pid,
                "pred_label": CLASSES[int(pred[i])],
                "pred_confidence": round(float(conf[i]), 4),
                "p_painted": round(float(proba[i, LABEL2ID["painted"]]), 4),
                "p_photo": round(float(proba[i, LABEL2ID["photo"]]), 4),
                "p_composite": round(float(proba[i, LABEL2ID["composite"]]), 4),
                "gold_label": gold.get(pid, ""),
                "split": split_map.get(pid, ""),
            }
            w.writerow(row)
    print(
        f"wrote {args.pred_out} n={len(ids):,} pred_s={time.time()-t1:.1f} "
        f"pred_counts={dict(Counter(CLASSES[int(p)] for p in pred))}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
