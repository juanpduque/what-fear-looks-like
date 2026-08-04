#!/usr/bin/env python3
"""Poll S3 + local job signals → unified status.json + events.log.

Writes:
  pipeline/data/qa/jobs_dashboard/status.json
  pipeline/data/qa/jobs_dashboard/events.log
  pipeline/data/qa/jobs_dashboard/cache/   (raw S3 snapshots)
  site/jobs-dashboard/status.json          (local Pages mirror, optional)

Also syncs (when AWS profiles work):
  s3://sagemaker-studio-a5572760/wflike-jobs-dashboard/   (private archive)
  s3://amaleli-website/wflike-jobs-dashboard/             (public HTTPS for Pages)

Usage:
  python3 pipeline/jobs_dashboard_poller.py            # loop every 45s
  python3 pipeline/jobs_dashboard_poller.py --once     # single tick
  bash pipeline/aws/start_jobs_dashboard.sh            # nohup + HTTP UI
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
DATA = ROOT / "data"
OUT = DATA / "qa" / "jobs_dashboard"
CACHE = OUT / "cache"
STATUS_PATH = OUT / "status.json"
EVENTS_PATH = OUT / "events.log"
SITE_MIRROR = REPO / "site" / "jobs-dashboard"

SANDBOX_BUCKET = "sagemaker-studio-a5572760"
PUBLIC_BUCKET = "amaleli-website"
DASH_PREFIX = "wflike-jobs-dashboard"
OWL_BUCKET = "aof-owlv2-102516364259"
OWL_TARGET = 19263
REGION = "us-east-1"

WFLIKE_NAME_FILTER = "wflike-*"
PUBLIC_STATUS_URL = f"https://{PUBLIC_BUCKET}.s3.amazonaws.com/{DASH_PREFIX}/status.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_text(path: Path, max_bytes: int = 200_000) -> str | None:
    try:
        if not path.is_file():
            return None
        data = path.read_bytes()[-max_bytes:]
        return data.decode("utf-8", errors="replace")
    except OSError:
        return None


def read_json(path: Path) -> Any | None:
    try:
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_pid(path: Path) -> int | None:
    text = read_text(path)
    if not text:
        return None
    m = re.search(r"\d+", text)
    return int(m.group(0)) if m else None


def run_aws(
    args: list[str],
    profile: str,
    timeout: int = 45,
) -> tuple[int, str, str]:
    env = os.environ.copy()
    env["AWS_PROFILE"] = profile
    env["AWS_DEFAULT_REGION"] = REGION
    # Avoid sandbox proxy leaking into aws cli
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(k, None)
    cmd = ["aws", *args, "--output", "text"]
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", "aws cli not found"


def s3_get_text(profile: str, uri: str, cache_name: str) -> tuple[str | None, str | None]:
    """Fetch S3 object to cache; return (text, error)."""
    cache_path = CACHE / cache_name
    rc, out, err = run_aws(["s3", "cp", uri, str(cache_path), "--quiet"], profile)
    if rc != 0:
        # Keep last good cache if present
        cached = read_text(cache_path)
        if cached is not None:
            return cached, f"stale_cache: {err or out or f'rc={rc}'}"
        return None, err or out or f"rc={rc}"
    return read_text(cache_path), None


def s3_exists(profile: str, uri: str) -> bool:
    rc, _, _ = run_aws(["s3", "ls", uri], profile, timeout=20)
    return rc == 0


def parse_kv_progress(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def append_event(prev: dict[str, Any] | None, cur: dict[str, Any]) -> None:
    prev_jobs = (prev or {}).get("jobs") or {}
    cur_jobs = cur.get("jobs") or {}
    lines: list[str] = []
    ts = cur.get("updated_at") or utc_now()

    for jid, job in cur_jobs.items():
        old = prev_jobs.get(jid) or {}
        interesting = ("state", "phase", "ok", "err", "todo", "detail", "progress_pct")
        changed = any(old.get(k) != job.get(k) for k in interesting)
        if not prev or changed:
            pct = job.get("progress_pct")
            pct_s = f" {pct:.1f}%" if isinstance(pct, (int, float)) else ""
            lines.append(
                f"[{ts}] {jid}: state={job.get('state')} phase={job.get('phase')}"
                f"{pct_s} ok={job.get('ok')} err={job.get('err')} todo={job.get('todo')}"
                f" | {job.get('detail') or ''}"
            )

    # EC2 set changes
    prev_ids = {i.get("instance_id") for i in ((prev or {}).get("ec2") or [])}
    cur_ids = {i.get("instance_id") for i in (cur.get("ec2") or [])}
    for iid in sorted(cur_ids - prev_ids):
        inst = next(i for i in cur["ec2"] if i.get("instance_id") == iid)
        lines.append(f"[{ts}] ec2+: {iid} name={inst.get('name')} state={inst.get('state')}")
    for iid in sorted(prev_ids - cur_ids):
        lines.append(f"[{ts}] ec2-: {iid} (gone or not running)")

    if not lines:
        return
    OUT.mkdir(parents=True, exist_ok=True)
    with EVENTS_PATH.open("a", encoding="utf-8") as f:
        for line in lines:
            f.write(line.rstrip() + "\n")


def eta_from_rate(todo: int | None, rate: float | None) -> str | None:
    if todo is None or rate is None or rate <= 0 or todo <= 0:
        return None
    secs = todo / rate
    if secs < 120:
        return f"~{int(secs)}s"
    if secs < 7200:
        return f"~{secs / 60:.0f}m"
    return f"~{secs / 3600:.1f}h"


def poll_community() -> dict[str, Any]:
    job: dict[str, Any] = {
        "id": "community_72k",
        "label": "Community 72k",
        "state": "unknown",
        "phase": None,
        "ok": None,
        "err": None,
        "todo": None,
        "progress_pct": None,
        "eta": None,
        "detail": None,
        "source": f"s3://{SANDBOX_BUCKET}/wflike-community-72k/results/PROGRESS.json",
        "last_remote_ts": None,
        "error": None,
    }
    text, err = s3_get_text(
        "sandbox",
        f"s3://{SANDBOX_BUCKET}/wflike-community-72k/results/PROGRESS.json",
        "community_PROGRESS.json",
    )
    if err:
        job["error"] = err
    done = s3_exists("sandbox", f"s3://{SANDBOX_BUCKET}/wflike-community-72k/results/DONE")
    fail = s3_exists("sandbox", f"s3://{SANDBOX_BUCKET}/wflike-community-72k/results/FAIL")
    pause = s3_exists("sandbox", f"s3://{SANDBOX_BUCKET}/wflike-community-72k/results/PAUSE_LABELS")

    prog = None
    if text:
        try:
            prog = json.loads(text)
        except json.JSONDecodeError:
            job["error"] = "invalid PROGRESS.json"
    # Fallback: overlap guard snapshot
    if not prog:
        guard = read_json(DATA / "qa" / "rekognition_overlap_guard.json") or {}
        prog = guard.get("progress")

    if prog:
        job["phase"] = prog.get("phase")
        job["ok"] = prog.get("ok")
        job["err"] = prog.get("err")
        job["todo"] = prog.get("todo")
        job["last_remote_ts"] = prog.get("ts")
        rate = prog.get("rate_per_s")
        status = prog.get("status")
        job["detail"] = (
            f"status={status} done_batch={prog.get('done_batch')} "
            f"rate={rate}/s total_rows={prog.get('total_rows')}"
        )
        job["eta"] = eta_from_rate(prog.get("todo"), float(rate) if rate else None)
        # Rough progress for labels/detecttext with known todo
        todo = prog.get("todo")
        ok = prog.get("ok") or 0
        err_n = prog.get("err") or 0
        done_n = ok + err_n
        if isinstance(todo, int) and todo + done_n > 0:
            job["progress_pct"] = round(100.0 * done_n / (todo + done_n), 1)
        job["state"] = "running" if status in (None, "running", "start") else str(status)

    if pause:
        job["state"] = "paused"
        job["detail"] = (job.get("detail") or "") + " | PAUSE_LABELS present"
    if done:
        job["state"] = "done"
        job["progress_pct"] = 100.0
    if fail:
        job["state"] = "failed"
    return job


def poll_owl() -> dict[str, Any]:
    meta = read_json(DATA / "qa" / "owlv2_backfill" / "backfill_meta.json") or {}
    launch = read_json(DATA / "qa" / "owlv2_backfill" / "launch.json") or {}
    target = int(meta.get("n_need") or launch.get("n_ids") or OWL_TARGET)
    job: dict[str, Any] = {
        "id": "owlv2_backfill",
        "label": "OWL CPU/GPU backfill",
        "state": "unknown",
        "phase": "creature+weapon",
        "ok": None,
        "err": None,
        "todo": target,
        "progress_pct": None,
        "eta": None,
        "detail": None,
        "source": f"s3://{OWL_BUCKET}/wflike-owlv2-backfill/results/PROGRESS",
        "last_remote_ts": None,
        "error": None,
        "creature": None,
        "weapon": None,
        "target": target,
    }
    profile = launch.get("aws_profile") or "default"
    text, err = s3_get_text(
        profile,
        f"s3://{OWL_BUCKET}/wflike-owlv2-backfill/results/PROGRESS",
        "owl_PROGRESS",
    )
    if err:
        job["error"] = err
    done = s3_exists(profile, f"s3://{OWL_BUCKET}/wflike-owlv2-backfill/results/DONE")
    fail = s3_exists(profile, f"s3://{OWL_BUCKET}/wflike-owlv2-backfill/results/FAIL")

    creature = weapon = None
    device = None
    if text:
        kv = parse_kv_progress(text)
        # Also accept loose "creature_delta=N"
        if not kv and "creature" in text:
            m = re.search(r"creature[_\w]*=(\d+)", text)
            if m:
                creature = int(m.group(1))
            m = re.search(r"weapon=(\d+)", text)
            if m:
                weapon = int(m.group(1))
            m = re.search(r"ts=(\S+)", text)
            if m:
                job["last_remote_ts"] = m.group(1)
            m = re.search(r"device=(\S+)", text)
            if m:
                device = m.group(1)
        else:
            if "creature_delta" in kv:
                creature = int(float(kv["creature_delta"]))
            elif "creature" in kv:
                creature = int(float(kv["creature"]))
            if "weapon" in kv:
                weapon = int(float(kv["weapon"]))
            job["last_remote_ts"] = kv.get("ts")
            device = kv.get("device")

    job["creature"] = creature
    job["weapon"] = weapon
    if creature is not None:
        job["ok"] = creature
        job["todo"] = max(0, target - creature)
        job["progress_pct"] = round(min(100.0, 100.0 * creature / target), 1)
        eta_h = launch.get("eta_hours_rough")
        if eta_h and creature > 0 and creature < target:
            remaining = (target - creature) / target * float(eta_h)
            job["eta"] = f"~{remaining:.1f}h (rough)"
        job["state"] = "running"
        job["detail"] = (
            f"creature={creature}/{target} weapon={weapon} device={device or launch.get('device')}"
        )
        job["phase"] = f"device={device or launch.get('device') or '?'}"
    elif launch:
        job["state"] = "launched"
        job["detail"] = (
            f"iid={launch.get('instance_id')} type={launch.get('instance_type')} "
            f"awaiting PROGRESS"
        )

    if done:
        job["state"] = "done"
        job["progress_pct"] = 100.0
    if fail:
        job["state"] = "failed"
    return job


def poll_imdb_posters() -> dict[str, Any]:
    local_done = read_text(DATA / "imdb_selenium_s3_pull" / "IMDB_SELENIUM_DONE")
    local_prog = read_text(DATA / "imdb_selenium_s3_pull" / "PROGRESS")
    job: dict[str, Any] = {
        "id": "imdb_posters",
        "label": "IMDb posters",
        "state": "unknown",
        "phase": "posters",
        "ok": None,
        "err": None,
        "todo": None,
        "progress_pct": None,
        "eta": None,
        "detail": None,
        "source": f"s3://{SANDBOX_BUCKET}/wflike-imdb-selenium/results/",
        "last_remote_ts": None,
        "error": None,
    }
    text, err = s3_get_text(
        "sandbox",
        f"s3://{SANDBOX_BUCKET}/wflike-imdb-selenium/results/IMDB_SELENIUM_DONE",
        "imdb_posters_DONE",
    )
    if err and not local_done:
        job["error"] = err
    done_body = text or local_done
    prog_text, _ = s3_get_text(
        "sandbox",
        f"s3://{SANDBOX_BUCKET}/wflike-imdb-selenium/results/PROGRESS",
        "imdb_posters_PROGRESS",
    )
    prog_body = prog_text or local_prog

    hits = DATA / "imdb_selenium_s3_pull" / "imdb_poster_hits.csv"
    miss = DATA / "imdb_selenium_s3_pull" / "imdb_poster_miss.csv"
    n_hits = n_miss = None
    if hits.is_file():
        n_hits = max(0, sum(1 for _ in hits.open(encoding="utf-8", errors="replace")) - 1)
    if miss.is_file():
        n_miss = max(0, sum(1 for _ in miss.open(encoding="utf-8", errors="replace")) - 1)

    if done_body:
        job["state"] = "done"
        job["progress_pct"] = 100.0
        job["detail"] = done_body.strip().splitlines()[0][:120]
        job["last_remote_ts"] = None
        m = re.search(r"(20\d{6}T\d{6}Z)", done_body)
        if m:
            job["last_remote_ts"] = m.group(1)
    elif prog_body:
        job["state"] = "running"
        job["detail"] = prog_body.strip().splitlines()[0][:120]
    else:
        job["state"] = "unknown"
        job["detail"] = "no DONE/PROGRESS"

    if n_hits is not None:
        job["ok"] = n_hits
    if n_miss is not None:
        job["err"] = n_miss
    if n_hits is not None and n_miss is not None:
        job["detail"] = (job.get("detail") or "") + f" | hits={n_hits} miss={n_miss}"
    return job


def poll_imdb_features() -> dict[str, Any]:
    """IMDb features (main or residual). Prefer residual DONE if present."""
    job: dict[str, Any] = {
        "id": "imdb_features",
        "label": "IMDb features",
        "state": "unknown",
        "phase": "features",
        "ok": None,
        "err": None,
        "todo": None,
        "progress_pct": None,
        "eta": None,
        "detail": None,
        "source": f"s3://{SANDBOX_BUCKET}/wflike-imdb-features-residual/results/",
        "last_remote_ts": None,
        "error": None,
    }
    # Try residual first, then main selenium prefix
    for prefix, cache in (
        ("wflike-imdb-features-residual", "imdb_feat_residual_DONE"),
        ("wflike-imdb-selenium", "imdb_feat_main_DONE"),
    ):
        text, err = s3_get_text(
            "sandbox",
            f"s3://{SANDBOX_BUCKET}/{prefix}/results/IMDB_SELENIUM_DONE",
            cache,
        )
        if text:
            job["state"] = "done"
            job["progress_pct"] = 100.0
            job["source"] = f"s3://{SANDBOX_BUCKET}/{prefix}/results/IMDB_SELENIUM_DONE"
            job["detail"] = f"{prefix}: {text.strip().splitlines()[0][:100]}"
            m = re.search(r"(20\d{6}T\d{6}Z)", text)
            if m:
                job["last_remote_ts"] = m.group(1)
            break
        if err and job["error"] is None:
            job["error"] = err

    local_hits = DATA / "imdb_selenium_s3_pull" / "imdb_selenium_features_hits.csv"
    local_miss = DATA / "imdb_selenium_s3_pull" / "imdb_selenium_features_miss.csv"
    if local_hits.is_file():
        job["ok"] = max(0, sum(1 for _ in local_hits.open(encoding="utf-8", errors="replace")) - 1)
    if local_miss.is_file():
        job["err"] = max(0, sum(1 for _ in local_miss.open(encoding="utf-8", errors="replace")) - 1)

    # Local DONE from posters pull also marks selenium job complete historically
    if job["state"] != "done":
        local_done = read_text(DATA / "imdb_selenium_s3_pull" / "IMDB_SELENIUM_DONE")
        if local_done and local_hits.is_file():
            job["state"] = "done"
            job["progress_pct"] = 100.0
            job["detail"] = (job.get("detail") or "local pull") + f" | {local_done.strip()[:80]}"
    if job["state"] == "unknown" and job["ok"] is not None:
        job["state"] = "done" if job.get("ok", 0) > 0 else "unknown"
        if job["state"] == "done":
            job["progress_pct"] = 100.0
    return job


def poll_rekognition_local() -> dict[str, Any]:
    log_path = DATA / "qa" / "rekognition_community_enrich.log"
    pid_path = DATA / "qa" / "rekognition_community_enrich.pid"
    pid = read_pid(pid_path)
    alive = pid_alive(pid)
    log = read_text(log_path) or ""
    job: dict[str, Any] = {
        "id": "rekognition_local",
        "label": "Local rekognition enrich",
        "state": "unknown",
        "phase": "enrich",
        "ok": None,
        "err": None,
        "todo": None,
        "progress_pct": None,
        "eta": None,
        "detail": None,
        "source": str(log_path),
        "last_remote_ts": None,
        "error": None,
        "pid": pid,
        "alive": alive,
    }
    listo = None
    for line in reversed(log.splitlines()):
        if "LISTO" in line:
            listo = line.strip()
            break
    prog = None
    for line in reversed(log.splitlines()):
        m = re.search(r"\[(\d+)/(\d+)\].*ok=(\d+)\s+err=(\d+)", line)
        if m:
            prog = m
            break

    if listo:
        job["state"] = "done"
        job["progress_pct"] = 100.0
        job["detail"] = listo[:160]
        m = re.search(r"ok=(\d+)\s+err=(\d+)", listo)
        if m:
            job["ok"] = int(m.group(1))
            job["err"] = int(m.group(2))
    elif alive and prog:
        cur, total, ok, err_n = map(int, prog.groups())
        job["state"] = "running"
        job["ok"] = ok
        job["err"] = err_n
        job["todo"] = max(0, total - cur)
        job["progress_pct"] = round(100.0 * cur / total, 1) if total else None
        job["detail"] = f"pid={pid} [{cur}/{total}]"
    elif alive:
        job["state"] = "running"
        job["detail"] = f"pid={pid} alive"
    elif prog:
        cur, total, ok, err_n = map(int, prog.groups())
        job["state"] = "stopped"
        job["ok"] = ok
        job["err"] = err_n
        job["detail"] = f"last [{cur}/{total}] pid dead"
    else:
        job["state"] = "unknown"
        job["detail"] = "no LISTO / progress in log"

    # Prefer overlap guard local_enrich if richer
    guard = read_json(DATA / "qa" / "rekognition_overlap_guard.json") or {}
    le = guard.get("local_enrich") or {}
    if le.get("done") and job["state"] != "done":
        job["state"] = "done"
        job["progress_pct"] = 100.0
        job["detail"] = le.get("log_tail") or job["detail"]
    return job


def poll_medium_compare() -> dict[str, Any]:
    base = DATA / "qa" / "medium_backbone_compare"
    log = read_text(base / "pipeline_embed.log") or ""
    pid = read_pid(base / "pipeline_pid.txt")
    alive = pid_alive(pid)
    compare = read_json(base / "compare_f1.json")
    cache = DATA / "qa" / "medium_siglip" / "openclip_vitl14_openai.npz"
    job: dict[str, Any] = {
        "id": "medium_siglip_compare",
        "label": "SigLIP / medium compare",
        "state": "unknown",
        "phase": "embed",
        "ok": None,
        "err": None,
        "todo": None,
        "progress_pct": None,
        "eta": None,
        "detail": None,
        "source": str(base / "pipeline_embed.log"),
        "last_remote_ts": None,
        "error": None,
        "pid": pid,
        "alive": alive,
    }
    # Parse latest vitl N/M
    vitl = None
    for line in reversed(log.splitlines()):
        m = re.search(r"vitl\s+(\d+)/(\d+)", line)
        if m:
            vitl = (int(m.group(1)), int(m.group(2)))
            break
        m = re.search(r"vitl cache=(\d+) todo=(\d+)", line)
        if m:
            done_n, todo = int(m.group(1)), int(m.group(2))
            vitl = (0, done_n + todo)  # just started batch
            job["ok"] = done_n
            job["todo"] = todo
            break

    if compare:
        job["state"] = "done"
        job["phase"] = "compare"
        job["progress_pct"] = 100.0
        job["detail"] = "compare_f1.json present"
    elif "FileNotFoundError" in log and not alive and not vitl:
        job["state"] = "error"
        job["detail"] = "embed failed (FileNotFoundError on npz tmp)"
    elif alive:
        job["state"] = "running"
        if vitl:
            cur, total = vitl
            # lines like "vitl 20/391" mean batch progress; total embeds grow via checkpoint n=
            job["ok"] = cur
            job["todo"] = max(0, total - cur)
            job["progress_pct"] = round(100.0 * cur / total, 1) if total else None
            job["detail"] = f"pid={pid} vitl {cur}/{total}"
            # ETA from elapsed if present
            m = re.search(r"vitl\s+\d+/\d+\s+total=\d+\s+elapsed=([\d.]+)s", log)
            if m and cur > 0:
                rate = cur / float(m.group(1))
                job["eta"] = eta_from_rate(total - cur, rate)
        else:
            job["detail"] = f"pid={pid} embedding…"
    elif vitl:
        cur, total = vitl
        job["state"] = "stopped"
        job["ok"] = cur
        job["todo"] = max(0, total - cur)
        job["progress_pct"] = round(100.0 * cur / total, 1) if total else None
        job["detail"] = f"last vitl {cur}/{total}; pid dead"
    elif cache.is_file():
        job["state"] = "partial"
        job["detail"] = f"cache exists ({cache.name}); no live pid"
    else:
        job["state"] = "idle"
        job["detail"] = "no embed activity"

    # checkpoint n= from last line
    for line in reversed(log.splitlines()):
        m = re.search(r"checkpoint .+ n=(\d+)", line)
        if m:
            job["ok"] = int(m.group(1))
            break
    return job


def poll_overlap_guard() -> dict[str, Any]:
    path = DATA / "qa" / "rekognition_overlap_guard.json"
    g = read_json(path) or {}
    job: dict[str, Any] = {
        "id": "overlap_guard",
        "label": "Overlap guard",
        "state": g.get("status") or ("missing" if not g else "ok"),
        "phase": g.get("pause"),
        "ok": (g.get("skip") or {}).get("skip_labels"),
        "err": None,
        "todo": None,
        "progress_pct": None,
        "eta": None,
        "detail": g.get("strategy") or g.get("note"),
        "source": str(path),
        "last_remote_ts": g.get("updated_at"),
        "error": None,
        "raw": {
            "pause": g.get("pause"),
            "labels_alert": g.get("labels_alert"),
            "local_enrich_done": (g.get("local_enrich") or {}).get("done"),
        },
    }
    alert = g.get("labels_alert") or {}
    if alert.get("error"):
        job["err"] = alert.get("ok")
        job["detail"] = (job.get("detail") or "") + f" | ALERT: {alert.get('error')}"
        job["state"] = "alert"
    return job


def poll_ec2() -> list[dict[str, Any]]:
    instances: list[dict[str, Any]] = []
    for profile in ("sandbox", "default"):
        env = os.environ.copy()
        env["AWS_PROFILE"] = profile
        env["AWS_DEFAULT_REGION"] = REGION
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
            env.pop(k, None)
        try:
            p = subprocess.run(
                [
                    "aws",
                    "ec2",
                    "describe-instances",
                    "--filters",
                    "Name=tag:Name,Values=wflike-*",
                    "Name=instance-state-name,Values=pending,running,stopping,stopped",
                    "--query",
                    "Reservations[].Instances[].[InstanceId,State.Name,InstanceType,PublicIpAddress,Tags[?Key==`Name`]|[0].Value]",
                    "--output",
                    "json",
                ],
                capture_output=True,
                text=True,
                timeout=40,
                env=env,
            )
            if p.returncode != 0:
                instances.append(
                    {
                        "instance_id": None,
                        "name": f"_query_error_{profile}",
                        "state": "error",
                        "type": None,
                        "ip": None,
                        "profile": profile,
                        "error": (p.stderr or p.stdout or "").strip()[:200],
                    }
                )
                continue
            rows = json.loads(p.stdout or "[]")
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
            instances.append(
                {
                    "instance_id": None,
                    "name": f"_query_error_{profile}",
                    "state": "error",
                    "type": None,
                    "ip": None,
                    "profile": profile,
                    "error": str(e)[:200],
                }
            )
            continue
        for row in rows or []:
            if not row or not isinstance(row, list):
                continue
            iid, state, itype, ip, name = (list(row) + [None] * 5)[:5]
            instances.append(
                {
                    "instance_id": iid,
                    "name": name,
                    "state": state,
                    "type": itype,
                    "ip": ip if ip not in (None, "None") else None,
                    "profile": profile,
                }
            )
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for inst in instances:
        iid = inst.get("instance_id")
        if iid and iid in seen:
            continue
        if iid:
            seen.add(iid)
        uniq.append(inst)
    return uniq


def build_status() -> dict[str, Any]:
    jobs_list = [
        poll_community(),
        poll_owl(),
        poll_imdb_posters(),
        poll_imdb_features(),
        poll_rekognition_local(),
        poll_medium_compare(),
        poll_overlap_guard(),
    ]
    jobs = {j["id"]: j for j in jobs_list}
    ec2 = poll_ec2()
    running = sum(1 for j in jobs_list if j.get("state") == "running")
    done = sum(1 for j in jobs_list if j.get("state") == "done")
    alerts = sum(1 for j in jobs_list if j.get("state") in ("failed", "error", "alert"))
    return {
        "updated_at": utc_now(),
        "poll_interval_s": None,  # filled by main
        "summary": {
            "running": running,
            "done": done,
            "alerts": alerts,
            "ec2_running": sum(1 for i in ec2 if i.get("state") == "running"),
        },
        "jobs": jobs,
        "ec2": ec2,
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f"{path.stem}.{os.getpid()}.{time.time_ns()}.tmp"
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def events_tail(n: int = 40) -> str:
    text = read_text(EVENTS_PATH, max_bytes=80_000) or ""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def mirror_to_site(status: dict[str, Any]) -> None:
    """Copy status (+ events) next to the Pages HTML for LAN/file:// fallback."""
    try:
        SITE_MIRROR.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(SITE_MIRROR / "status.json", status)
        if EVENTS_PATH.is_file():
            shutil.copy2(EVENTS_PATH, SITE_MIRROR / "events.log")
    except OSError as e:
        print(f"[{utc_now()}] site mirror warn: {e}", file=sys.stderr, flush=True)


def s3_put(profile: str, local: Path, uri: str, content_type: str) -> tuple[bool, str]:
    if not local.is_file():
        return False, "missing local file"
    rc, out, err = run_aws(
        [
            "s3",
            "cp",
            str(local),
            uri,
            "--content-type",
            content_type,
            "--cache-control",
            "no-cache, max-age=30",
            "--quiet",
        ],
        profile,
        timeout=60,
    )
    if rc == 0:
        return True, uri
    return False, err or out or f"rc={rc}"


def sync_remote(*, skip_sync: bool) -> dict[str, Any]:
    """Upload status.json + events.log to private sandbox + public HTTPS bucket."""
    result: dict[str, Any] = {
        "ok": False,
        "public_url": PUBLIC_STATUS_URL,
        "targets": {},
        "skipped": skip_sync,
    }
    if skip_sync:
        return result

    targets = [
        ("sandbox", f"s3://{SANDBOX_BUCKET}/{DASH_PREFIX}/status.json", STATUS_PATH, "application/json"),
        ("sandbox", f"s3://{SANDBOX_BUCKET}/{DASH_PREFIX}/events.log", EVENTS_PATH, "text/plain; charset=utf-8"),
        ("default", f"s3://{PUBLIC_BUCKET}/{DASH_PREFIX}/status.json", STATUS_PATH, "application/json"),
        ("default", f"s3://{PUBLIC_BUCKET}/{DASH_PREFIX}/events.log", EVENTS_PATH, "text/plain; charset=utf-8"),
    ]
    ok_any = False
    for profile, uri, path, ctype in targets:
        if not path.is_file():
            result["targets"][uri] = {"ok": False, "error": "missing"}
            continue
        ok, info = s3_put(profile, path, uri, ctype)
        result["targets"][uri] = {"ok": ok, "info": info, "profile": profile}
        ok_any = ok_any or ok
    result["ok"] = ok_any
    return result


def write_status(status: dict[str, Any], prev: dict[str, Any] | None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(STATUS_PATH, status)
    append_event(prev, status)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true", help="Single poll then exit")
    ap.add_argument("--interval", type=int, default=45, help="Seconds between polls (default 45)")
    ap.add_argument("--no-sync", action="store_true", help="Skip S3 upload of status/events")
    ap.add_argument("--no-site-mirror", action="store_true", help="Skip copying into site/jobs-dashboard/")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)

    prev = read_json(STATUS_PATH)
    while True:
        t0 = time.time()
        try:
            status = build_status()
            status["poll_interval_s"] = args.interval
            status["poll_duration_s"] = round(time.time() - t0, 2)
            status["public_status_url"] = PUBLIC_STATUS_URL
            write_status(status, prev)
            status["events_tail"] = events_tail()
            _atomic_write_json(STATUS_PATH, status)

            remote = sync_remote(skip_sync=args.no_sync)
            status["remote_sync"] = {
                "ok": remote.get("ok"),
                "public_url": remote.get("public_url"),
                "skipped": remote.get("skipped"),
            }
            # Local-only meta after upload (S3 already has the job payload).
            _atomic_write_json(STATUS_PATH, status)

            if not args.no_site_mirror:
                mirror_to_site(status)

            prev = status
            sync_s = "skip" if args.no_sync else ("ok" if remote.get("ok") else "fail")
            print(
                f"[{status['updated_at']}] wrote {STATUS_PATH} "
                f"running={status['summary']['running']} "
                f"ec2={status['summary']['ec2_running']} "
                f"sync={sync_s} "
                f"({status['poll_duration_s']}s)",
                flush=True,
            )
            if not args.no_sync and not remote.get("ok"):
                fails = [
                    f"{u}: {(v or {}).get('info') or (v or {}).get('error')}"
                    for u, v in (remote.get("targets") or {}).items()
                    if not (v or {}).get("ok")
                ]
                if fails:
                    print(f"  sync errors: {'; '.join(fails[:4])}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[{utc_now()}] poller error: {e}", file=sys.stderr, flush=True)
            with EVENTS_PATH.open("a", encoding="utf-8") as f:
                f.write(f"[{utc_now()}] poller_error: {e}\n")
        if args.once:
            return 0
        time.sleep(max(15, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
