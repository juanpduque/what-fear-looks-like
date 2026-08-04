#!/usr/bin/env python3
"""Overnight monitor: S3 + EC2 + Rekognition Custom Labels → append status.md.

Usage:
  python3 pipeline/aws/overnight_monitor_tick.py          # one tick
  python3 pipeline/aws/overnight_monitor_tick.py --loop   # every 25-35 min
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATUS = ROOT / "pipeline" / "data" / "qa" / "cloud_overnight_status.md"
COMPARE_DIR = ROOT / "pipeline" / "data" / "qa" / "medium_custom_labels"
COMPARE_JSON = COMPARE_DIR / "compare_f1.json"
BUCKET = "sagemaker-studio-a5572760"
REGION = os.environ["AWS_DEFAULT_REGION"]
OWL_INSTANCE = "i-0b9777ca835a6d5ab"
COMMUNITY_INSTANCE = "i-0c9df56ab11bf8b4b"
CL_PROJECT = (
    f"arn:aws:rekognition:{REGION}:567596065542:project/"
    "wflike-medium-clf/1785807168455"
)
LOGREG_F1 = 0.5135
OWL_TARGET = 19263


def redact(s: str | None) -> str:
    if not s:
        return ""
    return s.replace(REGION, "<region>")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(cmd: list[str], timeout: int = 120) -> tuple[int, str, str]:
    p = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False
    )
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def aws_json(args: list[str]):
    rc, out, err = run(["aws", *args, "--region", REGION, "--output", "json"])
    if rc != 0:
        return None, err or out
    try:
        return json.loads(out) if out else None, None
    except json.JSONDecodeError:
        return None, out


def s3_text(key: str) -> str | None:
    rc, out, err = run(
        ["aws", "s3", "cp", f"s3://{BUCKET}/{key}", "-", "--region", REGION]
    )
    if rc != 0:
        return None
    return out


def s3_exists(key: str) -> bool:
    rc, out, _err = run(
        ["aws", "s3", "ls", f"s3://{BUCKET}/{key}", "--region", REGION]
    )
    return rc == 0 and bool(out.strip())


def parse_owl_progress(text: str | None) -> dict:
    out = {
        "creature": None,
        "weapon": None,
        "ts": None,
        "device": None,
        "raw": text,
    }
    if not text:
        return out
    for line in text.splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if k == "creature_delta":
            out["creature"] = int(v)
        elif k == "weapon":
            out["weapon"] = int(v)
        elif k == "ts":
            out["ts"] = v
        elif k == "device":
            out["device"] = v
    return out


def ec2_state(iid: str) -> dict:
    data, err = aws_json(
        [
            "ec2",
            "describe-instances",
            "--instance-ids",
            iid,
            "--query",
            "Reservations[0].Instances[0].{Id:InstanceId,State:State.Name,Type:InstanceType,Name:Tags[?Key==`Name`]|[0].Value}",
        ]
    )
    if err or not data:
        return {"Id": iid, "State": "unknown", "error": err}
    return data


def custom_labels() -> dict:
    data, err = aws_json(
        [
            "rekognition",
            "describe-project-versions",
            "--project-arn",
            CL_PROJECT,
        ]
    )
    if err or not data:
        return {"error": err}
    versions = data.get("ProjectVersionDescriptions") or []
    if not versions:
        return {"error": "no versions"}
    # prefer v202608040132
    chosen = None
    for v in versions:
        arn = v.get("ProjectVersionArn") or ""
        if "v202608040132" in arn:
            chosen = v
            break
    if chosen is None:
        chosen = versions[0]
    eval_res = chosen.get("EvaluationResult") or {}
    f1 = None
    if isinstance(eval_res, dict):
        f1 = eval_res.get("F1Score")
        # sometimes nested
        summary = eval_res.get("Summary") or {}
        if f1 is None and isinstance(summary, dict):
            f1 = summary.get("F1Score")
    return {
        "arn": chosen.get("ProjectVersionArn"),
        "status": chosen.get("Status"),
        "message": chosen.get("StatusMessage"),
        "created": str(chosen.get("CreationTimestamp")),
        "billable_s": chosen.get("BillableTrainingTimeInSeconds"),
        "f1": f1,
        "evaluation": eval_res,
        "testing": chosen.get("TestingDataResult"),
    }


def maybe_write_compare(cl: dict) -> str | None:
    if cl.get("status") != "TRAINING_COMPLETED":
        return None
    if COMPARE_JSON.exists():
        return "compare_f1.json already present"
    COMPARE_DIR.mkdir(parents=True, exist_ok=True)
    cl_f1 = cl.get("f1")
    payload = {
        "written_at": utc_now(),
        "project": "wflike-medium-clf",
        "version": "v202608040132",
        "project_version_arn": redact(cl.get("arn")),
        "status": cl.get("status"),
        "custom_labels_f1": cl_f1,
        "logreg_f1": LOGREG_F1,
        "delta_f1": (None if cl_f1 is None else round(float(cl_f1) - LOGREG_F1, 6)),
        "beats_logreg": (
            None if cl_f1 is None else bool(float(cl_f1) > LOGREG_F1)
        ),
        "evaluation_result": cl.get("evaluation"),
        "billable_training_seconds": cl.get("billable_s"),
        "notes": (
            "LogReg baseline F1 fixed at 0.5135 per overnight brief "
            "(local_baseline/metrics.json macro_f1_test was 0.4852)."
        ),
    }
    COMPARE_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return f"wrote {COMPARE_JSON.relative_to(ROOT)}"



def git_checkpoint(msg: str) -> None:
    """Stage status/compare artifacts and push (best-effort)."""
    files = [
        "pipeline/data/qa/cloud_overnight_status.md",
        "pipeline/data/qa/medium_custom_labels/compare_f1.json",
        "pipeline/aws/overnight_monitor_tick.py",
    ]
    # scrub region literal before commit
    needle = REGION
    for rel in files:
        path = ROOT / rel
        if not path.exists():
            continue
        txt = path.read_text(encoding="utf-8")
        if needle and needle in txt:
            path.write_text(txt.replace(needle, "<region>"), encoding="utf-8")
    run(["git", "add", *files])
    rc, staged, _ = run(["git", "diff", "--cached", "--name-only"])
    if not staged.strip():
        print("git: nothing to commit", flush=True)
        return
    rc, out, err = run(["git", "commit", "-m", msg])
    print("git commit:", out or err, flush=True)
    if rc != 0:
        return
    # refresh GH HTTPS credentials (tokens expire mid-overnight)
    run(["gh", "auth", "setup-git"], timeout=60)
    rc, out, err = run(
        ["git", "push", "-u", "origin", "HEAD"], timeout=180
    )
    if rc != 0:
        run(["gh", "auth", "setup-git"], timeout=60)
        rc, out, err = run(
            ["git", "push", "-u", "origin", "HEAD"], timeout=180
        )
    print("git push:", out or err, "rc=", rc, flush=True)


def tick() -> str:
    now = utc_now()
    sts, sts_err = aws_json(["sts", "get-caller-identity"])
    aws_ok = sts is not None
    owl_raw = s3_text("wflike-owlv2-backfill/results/PROGRESS")
    owl = parse_owl_progress(owl_raw)
    community_prog = s3_text("wflike-community-72k/results/PROGRESS.json")
    community_done = s3_exists("wflike-community-72k/results/DONE")
    if not community_done and community_prog:
        try:
            community_done = json.loads(community_prog).get("status") == "done"
        except json.JSONDecodeError:
            pass
    owl_ec2 = ec2_state(OWL_INSTANCE)
    comm_ec2 = ec2_state(COMMUNITY_INSTANCE)
    cl = custom_labels()
    compare_note = maybe_write_compare(cl) if aws_ok else None

    creature = owl.get("creature")
    pct = (
        round(100.0 * creature / OWL_TARGET, 1)
        if isinstance(creature, int)
        else None
    )
    remain_h = None
    if isinstance(creature, int) and creature < OWL_TARGET:
        remain_h = round((OWL_TARGET - creature) * 3.0 / 3600, 1)

    # stale detection: if PROGRESS ts older than 12 min while EC2 running
    stale = False
    if owl.get("ts") and owl_ec2.get("State") == "running":
        try:
            ts = datetime.strptime(owl["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
            stale = age_min > 12
        except ValueError:
            pass

    lines = [
        f"\n---\n\n## {now} — tick\n",
        f"### AWS: **{'OK' if aws_ok else 'FAIL'}**"
        + (f" (`{redact(sts.get('Arn'))}`)" if sts else f" ({sts_err})"),
        "",
        "| Job | Status | Progress | Detail |",
        "|---|---|---|---|",
        (
            f"| Community 72k | "
            f"{'DONE' if community_done else 'UNKNOWN'} | "
            f"{'100%' if community_done else '?'} | "
            f"EC2={comm_ec2.get('State')} · "
            f"`{(community_prog or '')[:120].replace(chr(10), ' ')}`"
            f" |"
        ),
        (
            f"| OWL CPU backfill | "
            f"{'STALE?' if stale else ('RUNNING' if owl_ec2.get('State')=='running' else owl_ec2.get('State'))} | "
            f"{creature}/{OWL_TARGET} ({pct}%) device={owl.get('device')} | "
            f"ts={owl.get('ts')} · EC2 `{OWL_INSTANCE}` {owl_ec2.get('State')} "
            f"{owl_ec2.get('Type')} · ETA~{remain_h}h · "
            f"{'⚠️ progress stale >12min' if stale else 'sano'} |"
        ),
        (
            f"| Custom Labels v202608040132 | "
            f"{cl.get('status') or cl.get('error')} | "
            f"F1={cl.get('f1')} | "
            f"{(cl.get('message') or '')[:120]} · "
            f"{compare_note or 'await COMPLETED'} |"
        ),
        "",
    ]
    if compare_note and "wrote" in compare_note:
        lines.append(f"**Acción:** {compare_note}\n")
    if stale:
        lines.append(
            "**Acción OWL:** progress stale con EC2 running — "
            "revisar consola; no relaunch GPU; resume CPU desde deltas S3 si muerto.\n"
        )
    if (
        community_done
        and comm_ec2.get("State") == "running"
    ):
        lines.append(
            "**Acción Community:** DONE pero EC2 aún running — "
            "candidato a terminate (idle billing).\n"
        )

    block = "\n".join(lines) + "\n"
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    with STATUS.open("a", encoding="utf-8") as f:
        f.write(block)
    print(block)
    return block


def main():
    loop = "--loop" in sys.argv
    if not loop:
        tick()
        return
    # several hours: ~8h / ~30min ≈ 16 ticks
    max_ticks = 20
    for i in range(max_ticks):
        print(f"=== loop tick {i+1}/{max_ticks} ===", flush=True)
        try:
            tick()
            git_checkpoint(f"chore(qa): overnight status tick {utc_now()}")
        except Exception as e:
            msg = f"\n---\n\n## {utc_now()} — tick ERROR\n\n`{e}`\n"
            with STATUS.open("a", encoding="utf-8") as f:
                f.write(msg)
            print(msg, flush=True)
        if i + 1 >= max_ticks:
            break
        sleep_s = random.randint(20 * 60, 40 * 60)
        print(f"sleep {sleep_s}s…", flush=True)
        time.sleep(sleep_s)


if __name__ == "__main__":
    main()
