#!/usr/bin/env python3
"""Train Rekognition Custom Labels (medium) and compare F1 vs CLIP+LogReg.

Uses the same gold set + stratified split (seed=42, test=25%) for a fair
macro-F1 comparison on the held-out test ids.

Writes:
  data/qa/medium_custom_labels/
    gold_merged.csv
    split.csv
    logreg_metrics.json
    custom_labels_run.json
    compare_f1.json   (when Custom Labels finishes)

  export AWS_PROFILE=sandbox
  python3 aws_custom_labels_medium.py --prepare-only
  python3 aws_custom_labels_medium.py --train
  python3 aws_custom_labels_medium.py --poll
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import boto3
import joblib
import numpy as np
from botocore.exceptions import ClientError
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, f1_score
from sklearn.model_selection import StratifiedShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"
GOLD_OLD = DATA / "label_qa_medium_train.csv"
GOLD_R3 = DATA / "qa" / "medium_qa_r3_labels.json"
EMB = DATA / "clip_embeddings.npz"
OUT = DATA / "qa" / "medium_custom_labels"
CLASSES = ["painted", "photo", "composite"]
REGION = "us-east-1"
BUCKET_DEFAULT = "sagemaker-studio-a5572760"
PREFIX_DEFAULT = "wflike-custom-labels/medium"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def load_gold() -> dict[int, str]:
    out: dict[int, str] = {}
    if GOLD_OLD.exists():
        with GOLD_OLD.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                lab = (r.get("final_label") or "").strip().lower()
                if lab not in CLASSES:
                    continue
                try:
                    out[int(r["id"])] = lab
                except Exception:
                    pass
    if GOLD_R3.exists():
        d = json.loads(GOLD_R3.read_text(encoding="utf-8"))
        for kid, v in (d.get("verdicts") or {}).items():
            lab = (v.get("label") if isinstance(v, dict) else v) or ""
            lab = str(lab).strip().lower()
            if lab not in CLASSES:
                continue
            try:
                out[int(kid)] = lab
            except Exception:
                pass
    return out


def load_emb() -> tuple[dict[int, np.ndarray], np.ndarray, np.ndarray]:
    z = np.load(EMB, allow_pickle=True)
    ids = np.asarray(z["ids"], dtype=np.int64)
    vecs = np.asarray(z["vecs"], dtype=np.float32)
    norms = np.clip(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-8, None)
    vecs = vecs / norms
    by = {int(i): v for i, v in zip(ids, vecs)}
    return by, ids, vecs


def make_split(gold: dict[int, str], seed: int, test_size: float) -> tuple[list[int], list[int]]:
    ids = sorted(gold)
    y = [gold[i] for i in ids]
    sss = StratifiedShuffleSplit(n_splits=1, test_size=test_size, random_state=seed)
    tr, te = next(sss.split(ids, y))
    return [ids[i] for i in tr], [ids[i] for i in te]


def train_logreg(
    gold: dict[int, str],
    emb: dict[int, np.ndarray],
    train_ids: list[int],
    test_ids: list[int],
    out_dir: Path,
) -> dict:
    Xtr = np.stack([emb[i] for i in train_ids if i in emb])
    ytr = [gold[i] for i in train_ids if i in emb]
    Xte = np.stack([emb[i] for i in test_ids if i in emb])
    yte = [gold[i] for i in test_ids if i in emb]
    pipe = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    C=2.0, max_iter=2000, multi_class="multinomial", class_weight="balanced"
                ),
            ),
        ]
    )
    t0 = time.time()
    pipe.fit(Xtr, ytr)
    pred = pipe.predict(Xte)
    report = classification_report(yte, pred, labels=CLASSES, output_dict=True, zero_division=0)
    metrics = {
        "model": "clip_logreg",
        "n_train": len(ytr),
        "n_test": len(yte),
        "train_seconds": round(time.time() - t0, 3),
        "macro_f1_test": float(f1_score(yte, pred, labels=CLASSES, average="macro", zero_division=0)),
        "report": report,
        "class_counts_train": dict(Counter(ytr)),
        "class_counts_test": dict(Counter(yte)),
    }
    joblib.dump(pipe, out_dir / "logreg_model.joblib")
    (out_dir / "logreg_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    # predictions on test for later compare
    with (out_dir / "logreg_test_preds.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "gold", "pred"])
        w.writeheader()
        for i, g, p in zip([x for x in test_ids if x in emb], yte, pred):
            w.writerow({"id": i, "gold": g, "pred": p})
    return metrics


def write_manifest(path: Path, rows: list[tuple[int, str]], bucket: str, prefix: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for pid, lab in rows:
            s3 = f"s3://{bucket}/{prefix}/images/{pid}.jpg"
            meta = {
                "confidence": 1,
                "job-name": "medium-qa-gold",
                "class-name": lab,
                "human-annotated": "yes",
                "creation-date": utc_now(),
                "type": "groundtruth/image-classification",
            }
            obj = {"source-ref": s3, lab: 1, f"{lab}-metadata": meta}
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def upload_images(
    s3,
    bucket: str,
    prefix: str,
    ids: list[int],
) -> tuple[int, int]:
    ok = miss = 0
    for pid in ids:
        src = POSTERS / f"{pid}.jpg"
        key = f"{prefix}/images/{pid}.jpg"
        if not src.exists():
            miss += 1
            continue
        s3.upload_file(str(src), bucket, key)
        ok += 1
        if ok % 50 == 0:
            print(f"  uploaded {ok}/{len(ids)}", flush=True)
    return ok, miss


def prepare(args) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    gold = load_gold()
    print(f"gold usable: {len(gold)} {dict(Counter(gold.values()))}", flush=True)
    with (OUT / "gold_merged.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "final_label"])
        w.writeheader()
        for pid, lab in sorted(gold.items()):
            w.writerow({"id": pid, "final_label": lab})

    train_ids, test_ids = make_split(gold, args.seed, args.test_size)
    with (OUT / "split.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "final_label", "split"])
        w.writeheader()
        for pid in train_ids:
            w.writerow({"id": pid, "final_label": gold[pid], "split": "train"})
        for pid in test_ids:
            w.writerow({"id": pid, "final_label": gold[pid], "split": "test"})

    emb, _, _ = load_emb()
    logreg = train_logreg(gold, emb, train_ids, test_ids, OUT)
    print(f"LogReg macro-F1 test={logreg['macro_f1_test']:.4f}", flush=True)

    # manifests + upload
    s3 = boto3.client("s3", region_name=args.region)
    all_ids = train_ids + test_ids
    print(f"upload images → s3://{args.bucket}/{args.prefix}/images/ ({len(all_ids)})", flush=True)
    ok, miss = upload_images(s3, args.bucket, args.prefix, all_ids)
    print(f"uploaded={ok} miss={miss}", flush=True)

    write_manifest(
        OUT / "train.manifest",
        [(i, gold[i]) for i in train_ids],
        args.bucket,
        args.prefix,
    )
    write_manifest(
        OUT / "test.manifest",
        [(i, gold[i]) for i in test_ids],
        args.bucket,
        args.prefix,
    )
    s3.upload_file(str(OUT / "train.manifest"), args.bucket, f"{args.prefix}/train.manifest")
    s3.upload_file(str(OUT / "test.manifest"), args.bucket, f"{args.prefix}/test.manifest")
    s3.upload_file(str(OUT / "logreg_metrics.json"), args.bucket, f"{args.prefix}/logreg_metrics.json")

    state = {
        "bucket": args.bucket,
        "prefix": args.prefix,
        "region": args.region,
        "n_gold": len(gold),
        "n_train": len(train_ids),
        "n_test": len(test_ids),
        "uploaded": ok,
        "miss_jpg": miss,
        "logreg_macro_f1": logreg["macro_f1_test"],
        "train_manifest": f"s3://{args.bucket}/{args.prefix}/train.manifest",
        "test_manifest": f"s3://{args.bucket}/{args.prefix}/test.manifest",
        "prepared_at": utc_now(),
    }
    (OUT / "prepare.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def ensure_project(client, name: str) -> str:
    for p in client.describe_projects().get("ProjectDescriptions") or []:
        if p.get("ProjectArn", "").endswith(f"/{name}") or name in p.get("ProjectArn", ""):
            # ProjectName match via arn .../project/NAME/version?... actually arn ends with /project/NAME
            arn = p["ProjectArn"]
            if arn.rstrip("/").split("/")[-1] == name or f"/project/{name}" in arn:
                return arn
    resp = client.create_project(ProjectName=name)
    return resp["ProjectArn"]


def train(args) -> dict:
    prep = json.loads((OUT / "prepare.json").read_text(encoding="utf-8"))
    client = boto3.client("rekognition", region_name=args.region)
    project_name = args.project_name
    print(f"create/find project {project_name}", flush=True)
    try:
        project_arn = ensure_project(client, project_name)
    except ClientError as e:
        # fallback CreateProject
        print(f"ensure_project: {e}", flush=True)
        project_arn = client.create_project(ProjectName=project_name)["ProjectArn"]
    print(f"project={project_arn}", flush=True)

    # Datasets — Custom Labels API (2021+): CreateDataset with ProjectArn
    def _mk_ds(dtype: str, manifest: str) -> str:
        parts = manifest[5:].split("/", 1)
        bucket, key = parts[0], parts[1]
        try:
            r = client.create_dataset(
                DatasetType=dtype,
                ProjectArn=project_arn,
                DatasetSource={
                    "GroundTruthManifest": {"S3Object": {"Bucket": bucket, "Name": key}}
                },
            )
            return r["DatasetArn"]
        except TypeError:
            # SDK variant with ProjectName/DatasetName
            r = client.create_dataset(
                DatasetName=f"{project_name}-{dtype.lower()}",
                DatasetType=dtype,
                ProjectName=project_name,
                DatasetSource={
                    "GroundTruthManifest": {"S3Object": {"Bucket": bucket, "Name": key}}
                },
            )
            return r["DatasetArn"]
        except ClientError as e:
            msg = str(e)
            if "already" in msg.lower() or "ResourceAlreadyExists" in msg:
                # describe datasets in project
                try:
                    ds = client.describe_datasets(ProjectArn=project_arn)
                    for d in ds.get("DatasetDescriptions") or []:
                        if d.get("DatasetType") == dtype:
                            return d["DatasetArn"]
                except Exception:
                    pass
            raise

    train_arn = _mk_ds("TRAIN", prep["train_manifest"])
    test_arn = _mk_ds("TEST", prep["test_manifest"])
    print(f"datasets train={train_arn} test={test_arn}", flush=True)

    # wait CREATE_COMPLETE
    for arn, label in ((train_arn, "TRAIN"), (test_arn, "TEST")):
        for _ in range(60):
            d = client.describe_dataset(DatasetArn=arn)["DatasetDescription"]
            st = d.get("Status")
            print(f"  dataset {label} status={st}", flush=True)
            if st in ("CREATE_COMPLETE", "UPDATE_COMPLETE"):
                break
            if st in ("CREATE_FAILED", "UPDATE_FAILED"):
                raise SystemExit(f"dataset {label} failed: {d.get('StatusMessage')}")
            time.sleep(10)

    version = args.version_name or f"v{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"
    print(f"start training version={version}", flush=True)
    resp = client.create_project_version(
        ProjectArn=project_arn,
        VersionName=version,
        OutputConfig={
            "S3Bucket": prep["bucket"],
            "S3KeyPrefix": f"{prep['prefix']}/output",
        },
    )
    version_arn = resp["ProjectVersionArn"]
    run = {
        **prep,
        "project_arn": project_arn,
        "project_name": project_name,
        "train_dataset_arn": train_arn,
        "test_dataset_arn": test_arn,
        "version_name": version,
        "version_arn": version_arn,
        "training_started_at": utc_now(),
        "status": "TRAINING",
    }
    (OUT / "custom_labels_run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    print(f"TRAINING started → {version_arn}", flush=True)
    return run


def poll(args) -> dict:
    run = json.loads((OUT / "custom_labels_run.json").read_text(encoding="utf-8"))
    client = boto3.client("rekognition", region_name=args.region)
    arn = run["version_arn"]
    while True:
        desc = client.describe_project_versions(
            ProjectArn=run["project_arn"], VersionNames=[run["version_name"]]
        )
        vers = (desc.get("ProjectVersionDescriptions") or [None])[0]
        if not vers:
            raise SystemExit("version not found")
        st = vers.get("Status")
        print(f"status={st} msg={vers.get('StatusMessage','')[:120]}", flush=True)
        run["status"] = st
        run["status_message"] = vers.get("StatusMessage")
        if st == "TRAINING_COMPLETED":
            ev = vers.get("EvaluationResult") or {}
            f1 = (ev.get("F1Score") if isinstance(ev, dict) else None) or ev.get("F1Score")
            # EvaluationResult has F1Score at top level in some API versions
            cl_f1 = None
            if isinstance(ev, dict):
                cl_f1 = ev.get("F1Score")
                run["evaluation"] = ev
            run["custom_labels_f1"] = cl_f1
            run["finished_at"] = utc_now()
            (OUT / "custom_labels_run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
            compare = {
                "logreg_macro_f1_test": run.get("logreg_macro_f1"),
                "custom_labels_f1": cl_f1,
                "n_train": run.get("n_train"),
                "n_test": run.get("n_test"),
                "note": (
                    "Custom Labels F1 is the service-reported score on its TEST dataset "
                    "(same images we uploaded as test.manifest). LogReg macro-F1 is "
                    "sklearn on the same stratified test ids via CLIP embeddings."
                ),
                "version_arn": arn,
            }
            (OUT / "compare_f1.json").write_text(json.dumps(compare, indent=2), encoding="utf-8")
            print(json.dumps(compare, indent=2), flush=True)
            return compare
        if st in ("TRAINING_FAILED", "FAILED"):
            (OUT / "custom_labels_run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
            raise SystemExit(f"training failed: {vers.get('StatusMessage')}")
        if not args.wait:
            (OUT / "custom_labels_run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
            return run
        time.sleep(args.poll_seconds)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", default=REGION)
    ap.add_argument("--bucket", default=BUCKET_DEFAULT)
    ap.add_argument("--prefix", default=PREFIX_DEFAULT)
    ap.add_argument("--project-name", default="wflike-medium-clf")
    ap.add_argument("--version-name", default="")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--test-size", type=float, default=0.25)
    ap.add_argument("--prepare-only", action="store_true")
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--poll", action="store_true")
    ap.add_argument("--wait", action="store_true", help="with --poll, block until done")
    ap.add_argument("--poll-seconds", type=int, default=60)
    ap.add_argument("--all", action="store_true", help="prepare + train + poll --wait")
    args = ap.parse_args()

    if args.all:
        prepare(args)
        train(args)
        args.wait = True
        poll(args)
        return 0
    if args.prepare_only or (not args.train and not args.poll):
        prepare(args)
        if args.prepare_only:
            return 0
    if args.train:
        if not (OUT / "prepare.json").exists():
            prepare(args)
        train(args)
    if args.poll:
        poll(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
