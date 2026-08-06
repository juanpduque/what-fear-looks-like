#!/usr/bin/env python3
"""Prevent Rekognition double-billing: local community enrich vs EC2 community-72k Labels.

Strategy:
  - Upload PAUSE_LABELS + patched worker (wait_if_pause_labels + refresh_skip_from_s3).
  - Continuously rebuild skip_labels from rekognition.csv + sidecar and push to S3.
  - Poll PROGRESS.json every ~90s.
  - After enumerate (during download / before labels): hot-reload EC2 worker via SSM so the
    running --phase all process picks up pause+skip refresh (old process never re-reads skip).
  - Never touch IMDb posters instances.
  - Clear PAUSE only when local enrich is done (or FORCE_RESUME=1).

Status → pipeline/data/qa/rekognition_overlap_guard.json
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # pipeline/
DATA = ROOT / "data"
QA = DATA / "qa"
STATUS_PATH = QA / "rekognition_overlap_guard.json"
WORKER = ROOT / "community_72k_aws_worker.py"
LOCAL_PID_FILE = QA / "rekognition_community_enrich.pid"
LOCAL_SIDECAR = QA / "rekognition_community_enrich.csv"
LOCAL_MAIN = DATA / "rekognition.csv"
LOCAL_LOG = QA / "rekognition_community_enrich.log"

BUCKET = os.environ.get("BUCKET", "sagemaker-studio-a5572760")
PREFIX = os.environ.get("PREFIX", "wflike-community-72k")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
PROFILE = os.environ.get("AWS_PROFILE", "sandbox")
INSTANCE_ID = os.environ.get("COMMUNITY_72K_IID", "i-022c95cd59018a6a3")
PROTECT = {
    "i-0d70c936e1e39759b",
    "i-0f04b405308589396",
    "i-00bbaab197dd951d5",  # imdb posters
}
POLL_SECS = float(os.environ.get("GUARD_POLL_SECS", "90"))
ONCE = os.environ.get("GUARD_ONCE", "").strip() in ("1", "true", "yes")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def aws_base() -> list[str]:
    env = os.environ.copy()
    for k in (
        "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
        "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy",
    ):
        env.pop(k, None)
    return env


def run_aws(args: list[str], check: bool = False, timeout: int = 120) -> subprocess.CompletedProcess:
    cmd = ["aws", "--profile", PROFILE, "--region", REGION, *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=aws_base(),
        timeout=timeout,
        check=check,
    )


def write_status(doc: dict) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = {**doc, "updated_at": utc_now()}
    STATUS_PATH.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def ids_from_csv(path: Path) -> set[int]:
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


def rebuild_skip() -> tuple[Path, int, dict]:
    labels = set()
    labels |= ids_from_csv(LOCAL_MAIN)
    labels |= ids_from_csv(LOCAL_SIDECAR)
    out_dir = QA / "community_72k"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "skip_labels_ids.txt"
    path.write_text("\n".join(str(i) for i in sorted(labels)) + ("\n" if labels else ""), encoding="utf-8")
    meta = {
        "skip_labels": len(labels),
        "from_main": len(ids_from_csv(LOCAL_MAIN)),
        "from_sidecar": len(ids_from_csv(LOCAL_SIDECAR)),
        "built_at": utc_now(),
        "note": "overlap guard — includes live local enrich sidecar",
    }
    (out_dir / "skip_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return path, len(labels), meta


def upload_file(local: Path, key: str) -> bool:
    r = run_aws(["s3", "cp", str(local), f"s3://{BUCKET}/{key}"])
    return r.returncode == 0


def upload_text(key: str, body: str) -> bool:
    tmp = QA / "community_72k" / ("_tmp_" + key.replace("/", "_"))
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(body, encoding="utf-8")
    ok = upload_file(tmp, key)
    try:
        tmp.unlink()
    except Exception:
        pass
    return ok


def delete_s3(key: str) -> bool:
    r = run_aws(["s3", "rm", f"s3://{BUCKET}/{key}"])
    return r.returncode == 0


def get_progress() -> dict | None:
    r = run_aws(["s3", "cp", f"s3://{BUCKET}/{PREFIX}/results/PROGRESS.json", "-"])
    if r.returncode != 0:
        return {"_error": (r.stderr or r.stdout or "")[-300:]}
    try:
        return json.loads(r.stdout)
    except Exception as e:
        return {"_error": str(e), "_raw": r.stdout[:200]}


def local_enrich_running() -> dict:
    pid = None
    if LOCAL_PID_FILE.exists():
        try:
            pid = int(LOCAL_PID_FILE.read_text().strip())
        except Exception:
            pid = None
    alive = False
    cmd = ""
    if pid:
        try:
            os.kill(pid, 0)
            alive = True
        except ProcessLookupError:
            alive = False
        except PermissionError:
            alive = True  # exists but restricted
        except Exception:
            alive = False
        try:
            r = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
                timeout=5,
            )
            cmd = (r.stdout or "").strip()
            if r.returncode == 0 and cmd:
                alive = True
        except Exception:
            pass
    sidecar_n = sum(1 for _ in LOCAL_SIDECAR.open()) - 1 if LOCAL_SIDECAR.exists() else 0
    log_tail = ""
    if LOCAL_LOG.exists():
        lines = LOCAL_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        log_tail = lines[-1] if lines else ""
    # Heuristic: if log recently advanced and sidecar growing, treat as running
    return {
        "pid": pid,
        "alive": alive,
        "cmd": cmd[:120],
        "sidecar_rows": max(0, sidecar_n),
        "log_tail": log_tail[:160],
    }


def ensure_pause(set_pause: bool) -> str:
    key = f"{PREFIX}/results/PAUSE_LABELS"
    if set_pause:
        body = (
            f"PAUSE set by rekognition_overlap_guard at {utc_now()}\n"
            "Worker with wait_if_pause_labels will block before DetectLabels.\n"
            "Delete this object (or clear via guard) to resume.\n"
        )
        return "set" if upload_text(key, body) else "set_failed"
    return "cleared" if delete_s3(key) else "clear_failed"


def upload_worker() -> bool:
    return upload_file(WORKER, f"{PREFIX}/code/community_72k_aws_worker.py")


def ssm_available() -> bool:
    r = run_aws([
        "ssm", "describe-instance-information",
        "--filters", f"Key=InstanceIds,Values={INSTANCE_ID}",
        "--query", "InstanceInformationList[0].PingStatus",
        "--output", "text",
    ])
    return r.returncode == 0 and (r.stdout or "").strip() == "Online"


def hot_reload_worker() -> dict:
    """Kill community_72k python on EC2, sync code+skip, resume --phase all (resume-safe).

    Only call after enumerate has finished (ids CSV on S3). Does NOT touch other instances.
    """
    if INSTANCE_ID in PROTECT:
        return {"ok": False, "error": "refusing protected instance"}
    if not ssm_available():
        return {"ok": False, "error": "ssm_not_online", "hint": "will rely on stop/relaunch or wait"}

    # shell script executed on instance
    remote = r"""
set -euo pipefail
export BUCKET='""" + BUCKET + r"""'
export PREFIX='""" + PREFIX + r"""'
export AWS_DEFAULT_REGION='""" + REGION + r"""'
export PATH=/usr/local/bin:$PATH
ROOT=/home/ubuntu/aof
PIPE=$ROOT/pipeline
QA=$PIPE/data/qa/community_72k
VENV=$ROOT/.venv
LOG=$QA/hot_reload_guard.log
mkdir -p "$QA"
{
  echo "=== hot reload $(date -u) ==="
  # stop only community_72k worker (not other projects)
  pgrep -af community_72k_aws_worker.py || true
  pkill -f community_72k_aws_worker.py || true
  sleep 2
  pkill -9 -f community_72k_aws_worker.py || true
  # stop chain if waiting; userdata may exit — we re-exec worker only
  pkill -f community_72k_chain.sh || true
  sleep 1
  aws s3 sync "s3://${BUCKET}/${PREFIX}/code/" "$PIPE/"
  aws s3 cp "s3://${BUCKET}/${PREFIX}/input/qa/skip_labels_ids.txt" "$QA/skip_labels_ids.txt" || true
  aws s3 cp "s3://${BUCKET}/${PREFIX}/input/qa/skip_detecttext_ids.txt" "$QA/skip_detecttext_ids.txt" || true
  if [ -f /tmp/community_72k_env ]; then set -a; source /tmp/community_72k_env; set +a; fi
  aws s3 cp "s3://${BUCKET}/${PREFIX}/ENV" /tmp/community_72k_env 2>/dev/null || true
  if [ -f /tmp/community_72k_env ]; then set -a; source /tmp/community_72k_env; set +a; fi
  if [ -z "${TMDB_API_KEY:-}" ]; then
    aws s3 cp "s3://${BUCKET}/${PREFIX}/input/qa/tmdb_api_key" "$QA/tmdb_api_key" 2>/dev/null || true
    export TMDB_API_KEY="$(cat "$QA/tmdb_api_key" 2>/dev/null || true)"
  fi
  source "$VENV/bin/activate"
  cd "$PIPE"
  nohup env BUCKET="$BUCKET" PREFIX="$PREFIX" TMDB_API_KEY="$TMDB_API_KEY" \
    AWS_DEFAULT_REGION="$AWS_DEFAULT_REGION" \
    "$VENV/bin/python" -u community_72k_aws_worker.py --phase all \
    --download-workers "${DOWNLOAD_WORKERS:-24}" \
    --rek-workers "${REK_WORKERS:-10}" \
    --min-interval "${MIN_INTERVAL:-0.04}" \
    --save-every "${SAVE_EVERY:-25}" \
    --skip-labels-file "$QA/skip_labels_ids.txt" \
    --skip-text-file "$QA/skip_detecttext_ids.txt" \
    >> "$QA/community_72k_aws.log" 2>&1 &
  echo "restarted pid=$!"
  echo "=== hot reload done $(date -u) ==="
} >> "$LOG" 2>&1
aws s3 cp "$LOG" "s3://${BUCKET}/${PREFIX}/results/hot_reload_guard.log" || true
aws s3 cp "$QA/community_72k_aws.log" "s3://${BUCKET}/${PREFIX}/results/community_72k_aws.log" || true
"""
    # Use JSON parameters file to avoid quoting hell
    params = {
        "commands": [remote],
    }
    params_path = QA / "community_72k" / "_ssm_hot_reload.json"
    params_path.write_text(json.dumps(params), encoding="utf-8")
    r = run_aws([
        "ssm", "send-command",
        "--instance-ids", INSTANCE_ID,
        "--document-name", "AWS-RunShellScript",
        "--comment", "wflike overlap guard: reload worker with PAUSE+fresh skip",
        "--parameters", f"file://{params_path}",
        "--query", "Command.CommandId",
        "--output", "text",
    ], timeout=60)
    if r.returncode != 0:
        return {"ok": False, "error": (r.stderr or r.stdout or "")[-500:]}
    cmd_id = (r.stdout or "").strip()
    # brief wait for status
    time.sleep(8)
    st = run_aws([
        "ssm", "get-command-invocation",
        "--command-id", cmd_id,
        "--instance-id", INSTANCE_ID,
        "--query", "{Status:Status,Stdout:StandardOutputContent,Stderr:StandardErrorContent}",
        "--output", "json",
    ], timeout=60)
    detail = {}
    if st.returncode == 0 and st.stdout.strip():
        try:
            detail = json.loads(st.stdout)
        except Exception:
            detail = {"raw": st.stdout[:400]}
    return {"ok": True, "command_id": cmd_id, "invocation": detail}


def arm_once() -> dict:
    skip_path, n_skip, skip_meta = rebuild_skip()
    up_skip = upload_file(skip_path, f"{PREFIX}/input/qa/skip_labels_ids.txt")
    up_meta = upload_file(QA / "community_72k" / "skip_meta.json", f"{PREFIX}/input/qa/skip_meta.json")
    up_worker = upload_worker()
    # also stage path used by stage script
    staged = QA / "community_72k" / "_stage" / "code" / "community_72k_aws_worker.py"
    if staged.parent.exists():
        try:
            staged.write_text(WORKER.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            pass
    local = local_enrich_running()
    pause_action = ensure_pause(set_pause=bool(local["alive"] or local["sidecar_rows"] < 11000))
    # keep pause while local likely still working (11680 target); if clearly done, still pause until explicit clear after final skip
    progress = get_progress()
    return {
        "armed_at": utc_now(),
        "bucket": BUCKET,
        "prefix": PREFIX,
        "instance_id": INSTANCE_ID,
        "protect_instances": sorted(PROTECT),
        "skip_upload_ok": up_skip,
        "skip_meta_upload_ok": up_meta,
        "worker_upload_ok": up_worker,
        "skip": skip_meta,
        "pause": pause_action,
        "pause_key": f"s3://{BUCKET}/{PREFIX}/results/PAUSE_LABELS",
        "local_enrich": local,
        "progress": progress,
        "worker_features": ["wait_if_pause_labels", "refresh_skip_from_s3"],
        "note": (
            "Worker on EC2 must be hot-reloaded after enumerate to pick up pause/skip refresh. "
            "IMDb posters instance is protected."
        ),
    }


def should_hot_reload(progress: dict | None, state: dict) -> bool:
    if state.get("hot_reload_done"):
        return False
    if not progress or progress.get("_error"):
        return False
    phase = (progress.get("phase") or "").lower()
    status = (progress.get("status") or "").lower()
    # After enumerate done, or already in download / labels paused / labels start
    if phase == "enumerate" and status == "done":
        return True
    if phase == "download":
        return True
    if phase == "labels" and status in ("running", "start", "paused", "pause_cleared", "skip_refreshed"):
        return True
    if phase == "all" and status == "start":
        return False
    return False


def maybe_clear_pause(local: dict, state: dict) -> str | None:
    """Clear PAUSE when local enrich finished and final skip uploaded."""
    if os.environ.get("FORCE_RESUME", "").strip() in ("1", "true", "yes"):
        ensure_pause(False)
        return "force_resume"
    # Target from log like [4300/11680]
    target = 11680
    rows = int(local.get("sidecar_rows") or 0)
    alive = bool(local.get("alive"))
    if alive:
        return None
    # Consider done if sidecar reached near target or log says complete
    log_tail = local.get("log_tail") or ""
    done_hint = any(x in log_tail.lower() for x in ("done", "finished", "complete", "all ok"))
    if rows >= target - 5 or done_hint or (not alive and rows > 0 and state.get("saw_local_alive")):
        # Only clear if we previously saw it alive (avoid clearing before start)
        if state.get("saw_local_alive") and not alive:
            skip_path, n_skip, _ = rebuild_skip()
            upload_file(skip_path, f"{PREFIX}/input/qa/skip_labels_ids.txt")
            ensure_pause(False)
            return f"cleared_after_local_done skip={n_skip}"
    return None


def loop() -> int:
    state = {
        "hot_reload_done": False,
        "saw_local_alive": False,
        "actions": [],
    }
    arm = arm_once()
    if arm["local_enrich"].get("alive"):
        state["saw_local_alive"] = True
    doc = {
        "status": "armed",
        "strategy": "pause_flag + skip_reload + ssm_hot_reload_after_enumerate",
        **arm,
        "hot_reload": None,
        "poll_secs": POLL_SECS,
    }
    write_status(doc)
    print(json.dumps({"event": "armed", "skip": arm["skip"], "pause": arm["pause"], "progress": arm["progress"]}, indent=2))

    if ONCE:
        return 0

    while True:
        time.sleep(POLL_SECS)
        local = local_enrich_running()
        if local.get("alive"):
            state["saw_local_alive"] = True
        skip_path, n_skip, skip_meta = rebuild_skip()
        up_skip = upload_file(skip_path, f"{PREFIX}/input/qa/skip_labels_ids.txt")
        # Keep pause while local running
        if local.get("alive"):
            ensure_pause(True)
        progress = get_progress()
        action = None
        if should_hot_reload(progress if isinstance(progress, dict) else None, state):
            # Ensure pause + latest worker before reload
            ensure_pause(True)
            upload_worker()
            hr = hot_reload_worker()
            state["hot_reload_done"] = bool(hr.get("ok"))
            action = {"hot_reload": hr, "at": utc_now()}
            state["actions"].append(action)
            print(json.dumps({"event": "hot_reload", **hr}, indent=2))

        cleared = maybe_clear_pause(local, state)
        if cleared:
            state["actions"].append({"clear_pause": cleared, "at": utc_now()})
            print(json.dumps({"event": "clear_pause", "detail": cleared}, indent=2))

        phase = (progress or {}).get("phase") if isinstance(progress, dict) else None
        # Emergency: if labels running WITHOUT pause support (old worker) and local alive → try reload ASAP
        if (
            isinstance(progress, dict)
            and (progress.get("phase") or "") == "labels"
            and (progress.get("status") or "") == "running"
            and local.get("alive")
            and not state.get("emergency_reload")
        ):
            ensure_pause(True)
            upload_worker()
            hr = hot_reload_worker()
            state["emergency_reload"] = True
            state["hot_reload_done"] = bool(hr.get("ok"))
            state["actions"].append({"emergency_reload": hr, "at": utc_now()})
            print(json.dumps({"event": "emergency_reload", **hr}, indent=2))

        doc = {
            "status": "monitoring",
            "strategy": "pause_flag + skip_reload + ssm_hot_reload_after_enumerate",
            "bucket": BUCKET,
            "prefix": PREFIX,
            "instance_id": INSTANCE_ID,
            "protect_instances": sorted(PROTECT),
            "skip": skip_meta,
            "skip_upload_ok": up_skip,
            "pause_key": f"s3://{BUCKET}/{PREFIX}/results/PAUSE_LABELS",
            "local_enrich": local,
            "progress": progress,
            "hot_reload_done": state["hot_reload_done"],
            "actions": state["actions"][-10:],
            "poll_secs": POLL_SECS,
            "worker_features": ["wait_if_pause_labels", "refresh_skip_from_s3"],
        }
        if cleared:
            doc["status"] = "pause_cleared_local_done"
        write_status(doc)

        # Exit when community done
        if isinstance(progress, dict) and progress.get("phase") == "all" and progress.get("status") == "done":
            doc["status"] = "community_done"
            write_status(doc)
            return 0
        # Or DONE object
        r = run_aws(["s3", "ls", f"s3://{BUCKET}/{PREFIX}/results/DONE"])
        if r.returncode == 0 and "DONE" in (r.stdout or ""):
            doc["status"] = "community_done"
            write_status(doc)
            return 0


if __name__ == "__main__":
    try:
        raise SystemExit(loop())
    except KeyboardInterrupt:
        write_status({"status": "interrupted", "at": utc_now()})
        raise SystemExit(130)
