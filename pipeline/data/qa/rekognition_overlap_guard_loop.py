#!/usr/bin/env python3
"""Overlap guard monitor (boto3): keep skip fresh, hold PAUSE until local enrich done.

Run:
  AWS_PROFILE=sandbox python3 pipeline/data/qa/rekognition_overlap_guard_loop.py
"""
from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
QA = DATA / "qa"
STATUS = QA / "rekognition_overlap_guard.json"
PIDF = QA / "rekognition_community_enrich.pid"
SIDECAR = QA / "rekognition_community_enrich.csv"
MAIN = DATA / "rekognition.csv"
LOG = QA / "rekognition_community_enrich.log"

BUCKET = os.environ.get("BUCKET", "sagemaker-studio-a5572760")
PREFIX = os.environ.get("PREFIX", "wflike-community-72k")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
PROFILE = os.environ.get("AWS_PROFILE", "sandbox")
POLL = float(os.environ.get("GUARD_POLL_SECS", "90"))
TARGET = int(os.environ.get("LOCAL_ENRICH_TARGET", "11680"))


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def strip_proxy() -> None:
    for k in list(os.environ):
        if "proxy" in k.lower():
            del os.environ[k]


def clients():
    strip_proxy()
    os.environ.setdefault("AWS_PROFILE", PROFILE)
    os.environ.setdefault("AWS_DEFAULT_REGION", REGION)
    import boto3
    from botocore.config import Config

    cfg = Config(retries={"max_attempts": 8, "mode": "adaptive"})
    return (
        boto3.Session(profile_name=PROFILE, region_name=REGION).client("s3", config=cfg),
        boto3.Session(profile_name=PROFILE, region_name=REGION).client("ec2", config=cfg),
    )


def ids_from(path: Path) -> set[int]:
    out: set[int] = set()
    if not path.exists():
        return out
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                out.add(int(float(r["id"])))
            except Exception:
                pass
    return out


def rebuild_and_upload(s3) -> dict:
    labels = ids_from(MAIN) | ids_from(SIDECAR)
    out = QA / "community_72k"
    out.mkdir(parents=True, exist_ok=True)
    p = out / "skip_labels_ids.txt"
    p.write_text("\n".join(str(i) for i in sorted(labels)) + ("\n" if labels else ""), encoding="utf-8")
    meta = {
        "skip_labels": len(labels),
        "from_main": len(ids_from(MAIN)),
        "from_sidecar": len(ids_from(SIDECAR)),
        "built_at": utc(),
    }
    (out / "skip_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    s3.upload_file(str(p), BUCKET, f"{PREFIX}/input/qa/skip_labels_ids.txt")
    s3.upload_file(str(out / "skip_meta.json"), BUCKET, f"{PREFIX}/input/qa/skip_meta.json")
    return meta


def ensure_pause(s3, on: bool) -> str:
    key = f"{PREFIX}/results/PAUSE_LABELS"
    if on:
        s3.put_object(Bucket=BUCKET, Key=key, Body=f"PAUSE {utc()} overlap guard\n".encode())
        return "set"
    try:
        s3.delete_object(Bucket=BUCKET, Key=key)
        return "cleared"
    except Exception as e:
        return f"clear_err:{e}"


def get_progress(s3) -> dict:
    try:
        body = s3.get_object(Bucket=BUCKET, Key=f"{PREFIX}/results/PROGRESS.json")["Body"].read()
        return json.loads(body)
    except Exception as e:
        return {"_error": str(e)}


def local_state() -> dict:
    pid = None
    if PIDF.exists():
        try:
            pid = int(PIDF.read_text().strip())
        except Exception:
            pid = None
    alive = False
    if pid:
        try:
            os.kill(pid, 0)
            alive = True
        except ProcessLookupError:
            alive = False
        except PermissionError:
            alive = True
    rows = 0
    if SIDECAR.exists():
        rows = max(0, sum(1 for _ in SIDECAR.open()) - 1)
    tail = ""
    if LOG.exists():
        lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = lines[-1] if lines else ""
    return {"pid": pid, "alive": alive, "sidecar_rows": rows, "log_tail": tail[:180]}


def current_iid(ec2) -> str | None:
    r = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Name", "Values": ["wflike-community-72k"]},
            {"Name": "instance-state-name", "Values": ["running", "pending"]},
        ]
    )
    for res in r.get("Reservations") or []:
        for inst in res.get("Instances") or []:
            return inst["InstanceId"]
    return None


def write_status(doc: dict) -> None:
    doc = {**doc, "updated_at": utc()}
    STATUS.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    s3, ec2 = clients()
    saw_alive = False
    cleared = False
    print(f"guard loop start poll={POLL}s", flush=True)
    while True:
        try:
            local = local_state()
            if local["alive"]:
                saw_alive = True
            skip = rebuild_and_upload(s3)
            if local["alive"] or (not cleared and saw_alive is False):
                pause = ensure_pause(s3, True)
            elif saw_alive and not local["alive"] and local["sidecar_rows"] >= TARGET - 20 and not cleared:
                rebuild_and_upload(s3)
                pause = ensure_pause(s3, False)
                cleared = True
            elif saw_alive and not local["alive"] and ("done" in (local["log_tail"] or "").lower()) and not cleared:
                rebuild_and_upload(s3)
                pause = ensure_pause(s3, False)
                cleared = True
            else:
                pause = "set" if not cleared else "cleared"
                if not cleared:
                    ensure_pause(s3, True)

            # FORCE_RESUME
            if os.environ.get("FORCE_RESUME", "").strip() in ("1", "true", "yes"):
                rebuild_and_upload(s3)
                pause = ensure_pause(s3, False)
                cleared = True

            prog = get_progress(s3)
            iid = current_iid(ec2)
            doc = {
                "status": "monitoring" if not cleared else "pause_cleared_local_done",
                "strategy": "PAUSE_LABELS + refresh_skip_from_s3 on patched worker; relaunched i-0c9df56ab11bf8b4b",
                "bucket": BUCKET,
                "prefix": PREFIX,
                "instance_id": iid,
                "protect_instances": [
                    "i-00bbaab197dd951d5",
                    "i-0d70c936e1e39759b",
                    "i-0f04b405308589396",
                ],
                "pause": pause,
                "pause_key": f"s3://{BUCKET}/{PREFIX}/results/PAUSE_LABELS",
                "skip": skip,
                "local_enrich": local,
                "progress": prog,
                "worker_features": ["wait_if_pause_labels", "refresh_skip_from_s3"],
                "poll_secs": POLL,
            }
            write_status(doc)
            phase = (prog or {}).get("phase")
            status = (prog or {}).get("status")
            print(
                f"[{utc()}] phase={phase}/{status} skip={skip['skip_labels']} "
                f"local={local['sidecar_rows']} alive={local['alive']} pause={pause} iid={iid}",
                flush=True,
            )
            if phase == "all" and status == "done":
                doc["status"] = "community_done"
                write_status(doc)
                return 0
            try:
                s3.head_object(Bucket=BUCKET, Key=f"{PREFIX}/results/DONE")
                doc["status"] = "community_done"
                write_status(doc)
                return 0
            except Exception:
                pass
        except Exception as e:
            write_status({"status": "monitor_error", "error": str(e)[:400]})
            print(f"ERR {e}", flush=True)
        time.sleep(POLL)


if __name__ == "__main__":
    raise SystemExit(main())
