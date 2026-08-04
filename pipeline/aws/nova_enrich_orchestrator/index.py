"""Cloud Nova enrich orchestrator: batch from S3, write rows/json, self-chain."""
from __future__ import annotations

import csv
import io
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
from botocore.config import Config

S3 = boto3.client("s3")
LAMBDA = boto3.client(
    "lambda",
    config=Config(read_timeout=90, connect_timeout=10, retries={"max_attempts": 3}),
)

BUCKET = os.environ.get("NOVA_ENRICH_BUCKET", "")
PREFIX = os.environ.get("NOVA_ENRICH_PREFIX", "wflike-nova-enrich/cloud")
ENRICH_FN = os.environ.get("NOVA_ENRICH_FN", "poster-ocr-bedrock")
ORCH_FN = os.environ.get("NOVA_ORCH_FN", "nova-enrich-orchestrator")
MODEL_ID = os.environ.get("NOVA_MODEL_ID", "us.amazon.nova-2-lite-v1:0")
BATCH_SIZE = int(os.environ.get("NOVA_BATCH_SIZE", "10"))
WORKERS = int(os.environ.get("NOVA_WORKERS", "3"))
MIN_INTERVAL = float(os.environ.get("NOVA_MIN_INTERVAL", "0.55"))

CSV_FIELDS = [
    "id",
    "title",
    "year",
    "status",
    "latency_s",
    "title_text",
    "credits_text",
    "other_text",
    "languages",
    "mood",
    "fear_labels",
    "weapon",
    "monster",
    "person",
    "animal",
    "blood_gore",
    "violence",
    "sexual_content",
    "sensitive",
    "moderation_notes",
    "description",
    "model_id",
    "input_tokens",
    "output_tokens",
    "error",
]


def _key(*parts: str) -> str:
    return "/".join(p.strip("/") for p in (PREFIX, *parts) if p)


def s3_get_json(key: str, default=None):
    try:
        raw = S3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
        return json.loads(raw)
    except S3.exceptions.NoSuchKey:
        return default
    except Exception as e:
        if "NoSuchKey" in type(e).__name__ or "404" in str(e) or "Not Found" in str(e):
            return default
        raise


def s3_put_json(key: str, obj) -> None:
    S3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(obj, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )


def s3_exists(key: str) -> bool:
    try:
        S3.head_object(Bucket=BUCKET, Key=key)
        return True
    except Exception:
        return False


def strip_json(text: str) -> dict:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, flags=re.S)
        if not m:
            raise
        blob = m.group(0)
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            blob2 = re.sub(r",\s*([}\]])", r"\1", blob)
            return json.loads(blob2)


def _join_list(val) -> str:
    if val is None:
        return ""
    if isinstance(val, list):
        return "|".join(str(x).strip() for x in val if str(x).strip())
    return str(val).strip()


def _fear_labels(val) -> str:
    if not val:
        return ""
    if isinstance(val, str):
        return val
    parts = []
    for item in val:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            conf = item.get("conf", item.get("confidence", ""))
            try:
                conf_s = f"{float(conf):.2f}"
            except (TypeError, ValueError):
                conf_s = str(conf)
            if name:
                parts.append(f"{name}:{conf_s}")
        else:
            parts.append(str(item))
    return "|".join(parts)


def _score(val, default=0.0) -> float:
    try:
        x = float(val)
    except (TypeError, ValueError):
        return default
    return round(max(0.0, min(1.0, x)), 4)


def empty_row(pid, title, year, status, latency, err="") -> dict:
    return {
        "id": pid,
        "title": title,
        "year": year,
        "status": status,
        "latency_s": round(latency, 3),
        "title_text": "",
        "credits_text": "",
        "other_text": "",
        "languages": "",
        "mood": "",
        "fear_labels": "",
        "weapon": 0.0,
        "monster": 0.0,
        "person": 0.0,
        "animal": 0.0,
        "blood_gore": 0.0,
        "violence": 0.0,
        "sexual_content": 0.0,
        "sensitive": "",
        "moderation_notes": "",
        "description": "",
        "model_id": MODEL_ID,
        "input_tokens": "",
        "output_tokens": "",
        "error": (err or "")[:500],
    }


def parse_enrich(pid, title, year, payload, latency) -> tuple[dict, dict]:
    data = strip_json(payload.get("text") or "")
    usage = payload.get("usage") or {}
    row = empty_row(pid, title, year, "ok", latency)
    row.update(
        {
            "title_text": str(data.get("title_text") or "").replace("\n", " ").strip(),
            "credits_text": str(data.get("credits_text") or "").replace("\n", "\\n").strip(),
            "other_text": str(data.get("other_text") or "").replace("\n", "\\n").strip(),
            "languages": _join_list(data.get("languages")),
            "mood": _join_list(data.get("mood")),
            "fear_labels": _fear_labels(data.get("fear_labels")),
            "weapon": _score(data.get("weapon")),
            "monster": _score(data.get("monster")),
            "person": _score(data.get("person")),
            "animal": _score(data.get("animal")),
            "blood_gore": _score(data.get("blood_gore")),
            "violence": _score(data.get("violence")),
            "sexual_content": _score(data.get("sexual_content")),
            "sensitive": _join_list(data.get("sensitive")),
            "moderation_notes": str(data.get("moderation_notes") or "").replace("\n", " ").strip(),
            "description": str(data.get("description") or "").replace("\n", " ").strip(),
            "model_id": payload.get("model_id") or MODEL_ID,
            "input_tokens": usage.get("inputTokens", ""),
            "output_tokens": usage.get("outputTokens", ""),
        }
    )
    return row, data


def write_row(row: dict, data: dict | None = None) -> None:
    pid = int(row["id"])
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore")
    w.writeheader()
    w.writerow(row)
    S3.put_object(
        Bucket=BUCKET,
        Key=_key("rows", f"{pid}.csv"),
        Body=buf.getvalue().encode("utf-8"),
        ContentType="text/csv",
    )
    if data is not None and row.get("status") == "ok":
        s3_put_json(_key("json", f"{pid}.json"), data)


def invoke_enrich(pid: int) -> dict:
    poster_key = _key("posters", f"{pid}.jpg")
    payload = {
        "mode": "enrich",
        "model_id": MODEL_ID,
        "s3_bucket": BUCKET,
        "s3_key": poster_key,
        "image_format": "jpeg",
        "max_tokens": 700,
    }
    resp = LAMBDA.invoke(
        FunctionName=ENRICH_FN,
        Payload=json.dumps(payload).encode("utf-8"),
    )
    body = json.loads(resp["Payload"].read())
    if resp.get("FunctionError"):
        raise RuntimeError(
            f"lambda error: {body.get('errorType')}: {body.get('errorMessage')}"
        )
    if not isinstance(body, dict) or body.get("statusCode") != 200:
        raise RuntimeError(f"bad lambda response: {body!r}"[:500])
    return body


def process_one(meta: dict) -> dict:
    pid = int(meta["id"])
    title = meta.get("title") or ""
    year = meta.get("year") or ""
    t0 = time.perf_counter()
    # skip if already done in cloud
    if s3_exists(_key("json", f"{pid}.json")):
        return {"id": pid, "status": "skip", "latency_s": 0.0}
    try:
        body = invoke_enrich(pid)
        lat = time.perf_counter() - t0
        row, data = parse_enrich(pid, title, year, body, lat)
        write_row(row, data)
        return {"id": pid, "status": "ok", "latency_s": lat, "description": row.get("description", "")[:80]}
    except Exception as e:
        lat = time.perf_counter() - t0
        err = f"{type(e).__name__}: {e}"
        row = empty_row(pid, title, year, f"error: {err}"[:80], lat, err)
        write_row(row, None)
        return {"id": pid, "status": "error", "latency_s": lat, "error": err[:200]}


def load_meta_map() -> dict[int, dict]:
    key = _key("posters_meta.json")
    data = s3_get_json(key, default={})
    if isinstance(data, dict) and "by_id" in data:
        return {int(k): v for k, v in data["by_id"].items()}
    if isinstance(data, list):
        return {int(x["id"]): x for x in data}
    return {int(k): v for k, v in (data or {}).items()}


def chain_next(next_cursor: int, todo_len: int) -> bool:
    if next_cursor >= todo_len:
        return False
    payload = {"cursor": next_cursor, "chain": True}
    try:
        LAMBDA.invoke(
            FunctionName=ORCH_FN,
            InvocationType="Event",
            Payload=json.dumps(payload).encode("utf-8"),
        )
        return True
    except Exception as e:
        print(f"self-invoke failed: {e}")
        return False


def handler(event, context):
    global BUCKET
    if isinstance(event, str):
        event = json.loads(event)
    event = event or {}
    if event.get("bucket"):
        BUCKET = event["bucket"]
    if not BUCKET:
        return {"statusCode": 500, "error": "NOVA_ENRICH_BUCKET not set"}

    todo = s3_get_json(_key("todo_ids.json"), default=[]) or []
    todo_len = len(todo)

    if event.get("ids"):
        items = []
        meta_map = load_meta_map()
        for i in event["ids"]:
            pid = int(i)
            m = meta_map.get(pid) or {"id": pid, "title": "", "year": ""}
            items.append({"id": pid, "title": m.get("title", ""), "year": m.get("year", "")})
        next_cursor = int(event.get("cursor") or 0)
    else:
        cursor = int(event.get("cursor") or 0)
        items = []
        meta_map = load_meta_map()
        i = cursor
        while i < todo_len and len(items) < BATCH_SIZE:
            pid = int(todo[i])
            i += 1
            if s3_exists(_key("json", f"{pid}.json")):
                continue
            m = meta_map.get(pid) or {"id": pid, "title": "", "year": ""}
            items.append({"id": pid, "title": m.get("title", ""), "year": m.get("year", "")})
        next_cursor = i

    results = []
    if items:
        # mild pacing: process with small thread pool
        with ThreadPoolExecutor(max_workers=max(1, WORKERS)) as ex:
            futs = {ex.submit(process_one, it): it for it in items}
            for fut in as_completed(futs):
                results.append(fut.result())
                time.sleep(MIN_INTERVAL / max(1, WORKERS))

    ok_n = sum(1 for r in results if r.get("status") == "ok")
    err_n = sum(1 for r in results if r.get("status") == "error")
    skip_n = sum(1 for r in results if r.get("status") == "skip")

    progress = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "cursor": next_cursor,
        "todo_len": todo_len,
        "batch_ok": ok_n,
        "batch_err": err_n,
        "batch_skip": skip_n,
        "batch_ids": [r.get("id") for r in results],
        "sample": results[:3],
    }
    s3_put_json(_key("progress_cloud.json"), progress)

    chained = False
    if not event.get("no_chain") and next_cursor < todo_len:
        chained = chain_next(next_cursor, todo_len)

    return {
        "statusCode": 200,
        "cursor": next_cursor,
        "todo_len": todo_len,
        "ok": ok_n,
        "err": err_n,
        "skip": skip_n,
        "chained": chained,
        "done": next_cursor >= todo_len,
    }
