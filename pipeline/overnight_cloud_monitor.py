#!/usr/bin/env python3
"""Overnight AWS/job monitor for What Fear Looks Like.

Polls public dashboard; when AWS creds appear, also hits EC2/S3/Custom Labels.
Appends to pipeline/data/qa/cloud_overnight_status.md
Writes compare_f1 when Custom Labels training completes.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PIPELINE = Path(__file__).resolve().parent
REPO = PIPELINE.parent
STATUS_MD = PIPELINE / "data" / "qa" / "cloud_overnight_status.md"
COMPARE_DIR = PIPELINE / "data" / "qa" / "medium_custom_labels"
PUBLIC_STATUS = (
    "https://amaleli-website.s3.amazonaws.com/wflike-jobs-dashboard/status.json"
)
REGION = "us-east-1"
BUCKET = "sagemaker-studio-a5572760"
OWL_BUCKET = "aof-owlv2-102516364259"
CL_PROJECT = "wflike-medium-clf"
CL_VERSION = "v202608040132"
LOGREG_F1 = 0.5135
INTERVAL_S = int(os.environ.get("OVERNIGHT_INTERVAL_S", "1800"))  # 30 min
MAX_HOURS = float(os.environ.get("OVERNIGHT_MAX_HOURS", "6"))


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_public() -> dict | None:
    try:
        with urllib.request.urlopen(PUBLIC_STATUS, timeout=45) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"_error": str(e)}


def aws_env() -> dict:
    env = os.environ.copy()
    env["AWS_DEFAULT_REGION"] = REGION
    for k in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        env.pop(k, None)
    return env


def has_aws_creds() -> bool:
    if os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"):
        return True
    if (Path.home() / ".aws" / "credentials").is_file():
        return True
    return False


def aws_json(args: list[str], timeout: int = 60) -> tuple[int, object, str]:
    cmd = ["aws", *args, "--region", REGION, "--output", "json"]
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=aws_env()
        )
        out = p.stdout.strip()
        data = json.loads(out) if out else None
        return p.returncode, data, (p.stderr or "").strip()
    except FileNotFoundError:
        return 127, None, "aws cli not found"
    except subprocess.TimeoutExpired:
        return 124, None, "timeout"
    except json.JSONDecodeError as e:
        return 2, None, f"json error: {e}"


def s3_cp_text(uri: str) -> tuple[bool, str]:
    cmd = ["aws", "s3", "cp", uri, "-", "--region", REGION]
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, env=aws_env()
        )
        if p.returncode != 0:
            return False, (p.stderr or p.stdout or "s3 error").strip()
        return True, p.stdout
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def poll_custom_labels() -> dict:
    """DescribeProjectVersions for medium CLF; write compare_f1 on TRAINING_COMPLETED."""
    out: dict = {
        "project": CL_PROJECT,
        "version": CL_VERSION,
        "status": "unknown",
        "f1": None,
        "compare_written": False,
        "error": None,
    }
    code, data, err = aws_json(
        [
            "rekognition",
            "describe-project-versions",
            "--project-arn",
            # resolve via describe-projects if needed
            f"arn:aws:rekognition:{REGION}:{os.environ.get('AWS_ACCOUNT_ID', '567596065542')}:project/{CL_PROJECT}/version/{CL_VERSION}/1",
        ]
    )
    # Prefer list via project name
    code2, projects, err2 = aws_json(["rekognition", "describe-projects"])
    project_arn = None
    if code2 == 0 and isinstance(projects, dict):
        for p in projects.get("ProjectDescriptions") or []:
            if p.get("ProjectArn", "").endswith(f"/{CL_PROJECT}") or CL_PROJECT in p.get(
                "ProjectArn", ""
            ):
                project_arn = p["ProjectArn"]
                break
    if not project_arn:
        # try describe-project-versions with ProjectName filter via list
        code3, vers, err3 = aws_json(
            [
                "rekognition",
                "describe-project-versions",
                "--project-arn",
                f"arn:aws:rekognition:{REGION}:567596065542:project/{CL_PROJECT}/1",
            ]
        )
        if code3 != 0:
            out["error"] = err or err2 or err3
            out["status"] = "api_error"
            return out
        data = vers
    else:
        code, data, err = aws_json(
            [
                "rekognition",
                "describe-project-versions",
                "--project-arn",
                project_arn,
            ]
        )
        if code != 0:
            out["error"] = err
            out["status"] = "api_error"
            return out

    versions = (data or {}).get("ProjectVersionDescriptions") or []
    match = None
    for v in versions:
        arn = v.get("ProjectVersionArn", "")
        if CL_VERSION in arn or v.get("VersionName") == CL_VERSION:
            match = v
            break
    if not match and versions:
        # pick newest training
        match = versions[0]
    if not match:
        out["status"] = "not_found"
        out["error"] = "no project versions"
        return out

    status = match.get("Status") or "unknown"
    out["status"] = status
    out["raw_status_message"] = match.get("StatusMessage")
    eval_result = match.get("EvaluationResult") or {}
    f1 = eval_result.get("F1Score")
    out["f1"] = f1
    out["arn"] = match.get("ProjectVersionArn")

    if status == "TRAINING_COMPLETED" and f1 is not None:
        COMPARE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": utc_now(),
            "project": CL_PROJECT,
            "version": CL_VERSION,
            "project_version_arn": match.get("ProjectVersionArn"),
            "status": status,
            "custom_labels_f1": float(f1),
            "logreg_f1_baseline": LOGREG_F1,
            "delta_f1": float(f1) - LOGREG_F1,
            "wins_vs_logreg": float(f1) > LOGREG_F1,
            "evaluation": eval_result,
            "status_message": match.get("StatusMessage"),
        }
        path = COMPARE_DIR / "compare_f1.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        summary = COMPARE_DIR / "compare_f1.md"
        summary.write_text(
            f"# Medium Custom Labels vs LogReg\n\n"
            f"- Custom Labels F1: **{float(f1):.4f}**\n"
            f"- LogReg baseline: **{LOGREG_F1:.4f}**\n"
            f"- Delta: **{float(f1) - LOGREG_F1:+.4f}**\n"
            f"- Winner: **{'Custom Labels' if float(f1) > LOGREG_F1 else 'LogReg'}**\n"
            f"- Version: `{CL_VERSION}` · status `{status}` · {utc_now()}\n",
            encoding="utf-8",
        )
        out["compare_written"] = True
    elif status in ("TRAINING_FAILED", "FAILED"):
        out["error"] = match.get("StatusMessage") or "training failed"
    return out


def poll_aws_live() -> dict:
    result: dict = {"creds": True}
    code, ident, err = aws_json(["sts", "get-caller-identity"])
    if code != 0:
        result["sts_error"] = err
        result["creds"] = False
        return result
    result["identity"] = ident
    acct = (ident or {}).get("Account")
    if acct:
        os.environ["AWS_ACCOUNT_ID"] = acct

    code, ec2, err = aws_json(
        [
            "ec2",
            "describe-instances",
            "--filters",
            "Name=tag:Name,Values=wflike-*",
            "Name=instance-state-name,Values=pending,running,stopping,stopped",
            "--query",
            "Reservations[].Instances[].[InstanceId,State.Name,InstanceType,PublicIpAddress,Tags[?Key==`Name`]|[0].Value]",
        ]
    )
    result["ec2"] = ec2 if code == 0 else err

    ok, text = s3_cp_text(f"s3://{BUCKET}/wflike-community-72k/results/PROGRESS.json")
    result["community_progress"] = json.loads(text) if ok and text.strip().startswith("{") else text[:500]
    ok2, text2 = s3_cp_text(f"s3://{OWL_BUCKET}/wflike-owlv2-backfill/results/PROGRESS")
    result["owl_progress"] = text2.strip()[:500] if ok2 else text2[:300]
    # flags
    for flag in ("DONE", "FAIL", "PAUSE_LABELS"):
        okf, _ = s3_cp_text(f"s3://{BUCKET}/wflike-community-72k/results/{flag}")
        result[f"community_{flag}"] = okf

    result["custom_labels"] = poll_custom_labels()
    return result


def fmt_job_row(j: dict) -> str:
    return (
        f"| {j.get('label') or j.get('id')} | {j.get('state')} | "
        f"{j.get('progress_pct')}% {j.get('phase') or ''} | "
        f"{(j.get('detail') or '')[:120]} |"
    )


def append_tick(public: dict | None, aws: dict | None) -> None:
    lines: list[str] = []
    lines.append(f"\n---\n\n## {utc_now()} — tick\n")
    if aws and aws.get("creds"):
        lines.append("### AWS: OK\n")
        ident = aws.get("identity") or {}
        lines.append(f"- Account: `{ident.get('Account')}` Arn: `{ident.get('Arn')}`\n")
        lines.append(f"- EC2: `{json.dumps(aws.get('ec2'), ensure_ascii=False)[:800]}`\n")
        lines.append(f"- Community PROGRESS: `{json.dumps(aws.get('community_progress'), ensure_ascii=False)[:400]}`\n")
        lines.append(
            f"- Community flags DONE={aws.get('community_DONE')} FAIL={aws.get('community_FAIL')} "
            f"PAUSE_LABELS={aws.get('community_PAUSE_LABELS')}\n"
        )
        lines.append(f"- OWL PROGRESS: `{aws.get('owl_progress')}`\n")
        cl = aws.get("custom_labels") or {}
        lines.append(
            f"- Custom Labels: status=`{cl.get('status')}` f1=`{cl.get('f1')}` "
            f"compare_written=`{cl.get('compare_written')}` err=`{cl.get('error')}`\n"
        )
    else:
        lines.append("### AWS: **sin credenciales** (solo dashboard público)\n")
        if aws and aws.get("sts_error"):
            lines.append(f"- sts error: `{aws.get('sts_error')}`\n")

    if not public:
        lines.append("### Dashboard público: vacío\n")
    elif public.get("_error"):
        lines.append(f"### Dashboard público error: `{public['_error']}`\n")
    else:
        lines.append(f"### Dashboard público (updated `{public.get('updated_at')}`)\n")
        lines.append(f"- summary: `{public.get('summary')}`\n")
        lines.append("| Job | Status | Progress | Detail |\n|---|---|---|---|\n")
        for j in (public.get("jobs") or {}).values():
            lines.append(fmt_job_row(j) + "\n")
        lines.append(f"- ec2: `{json.dumps(public.get('ec2'), ensure_ascii=False)}`\n")

        jobs = public.get("jobs") or {}
        owl = jobs.get("owlv2_backfill") or {}
        last = owl.get("last_remote_ts")
        lines.append(
            f"\n**OWL check:** creature={owl.get('creature')} weapon={owl.get('weapon')} "
            f"last_ts={last} state={owl.get('state')} — leave running unless instance dead.\n"
        )
        comm = jobs.get("community_72k") or {}
        lines.append(
            f"**Community:** state={comm.get('state')} phase={comm.get('phase')} "
            f"(no relaunch; DONE expected).\n"
        )
        lines.append(
            "**Local pending:** SigLIP embeds + dashboard 127.0.0.1:8765 mueren si Mac duerme.\n"
        )

    STATUS_MD.parent.mkdir(parents=True, exist_ok=True)
    with STATUS_MD.open("a", encoding="utf-8") as f:
        f.write("".join(lines))
    print(f"[{utc_now()}] appended tick → {STATUS_MD}", flush=True)


def one_tick() -> dict:
    public = fetch_public()
    aws = None
    if has_aws_creds():
        aws = poll_aws_live()
    else:
        # still try sts in case ambient creds appear
        code, _, err = aws_json(["sts", "get-caller-identity"])
        if code == 0:
            aws = poll_aws_live()
        else:
            aws = {"creds": False, "sts_error": err or "NoCredentials"}
    append_tick(public, aws)
    return {"public": public, "aws": aws}


def main() -> int:
    once = "--once" in sys.argv
    deadline = time.time() + MAX_HOURS * 3600
    n = 0
    while True:
        n += 1
        print(f"[{utc_now()}] overnight tick #{n}", flush=True)
        try:
            one_tick()
        except Exception as e:  # noqa: BLE001
            with STATUS_MD.open("a", encoding="utf-8") as f:
                f.write(f"\n---\n\n## {utc_now()} — ERROR tick\n\n`{e}`\n")
            print(f"tick error: {e}", flush=True)
        if once:
            return 0
        if time.time() >= deadline:
            with STATUS_MD.open("a", encoding="utf-8") as f:
                f.write(
                    f"\n---\n\n## {utc_now()} — fin de ventana overnight ({MAX_HOURS}h)\n\n"
                    "Loop detenido. Revisar tabla Job|Status|Progress|Next al final del PR.\n"
                )
            return 0
        # 20–40 min jitter around INTERVAL_S
        sleep_s = INTERVAL_S + (n % 3) * 300  # 30 / 35 / 40 min
        print(f"[{utc_now()}] sleeping {sleep_s}s", flush=True)
        time.sleep(sleep_s)


if __name__ == "__main__":
    raise SystemExit(main())
