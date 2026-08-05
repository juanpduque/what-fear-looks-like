#!/usr/bin/env python3
"""Full-corpus Nova 2 Lite poster enrich via sandbox Lambda bridge.

One Bedrock call per poster returns structured JSON:
  title/credits/languages, fear labels + mood, moderation signals,
  short search description.

  export AWS_PROFILE=sandbox
  python3 nova_poster_enrich.py --limit 20 --workers 8
  python3 nova_poster_enrich.py --workers 24            # full corpus, resume

Outputs:
  data/qa/nova_enrich/nova_enrich.csv
  data/qa/nova_enrich/json/{id}.json
  data/qa/nova_enrich/nova_enrich.log
"""
from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import re
import signal
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
import pandas as pd
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from PIL import Image

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"
POSTERS_CSV = DATA / "posters.csv"
OUT_DIR = DATA / "qa" / "nova_enrich"
OUT_CSV = OUT_DIR / "nova_enrich.csv"
OUT_JSON = OUT_DIR / "json"
LOG_PATH = OUT_DIR / "nova_enrich.log"

DEFAULT_LAMBDA = "poster-ocr-bedrock"
DEFAULT_REGION = "us-west-2"
DEFAULT_MODEL = "us.amazon.nova-2-lite-v1:0"

ENRICH_PROMPT = """You analyze a movie poster image. Return ONLY valid JSON (no markdown) with this schema:
{
  "title_text": "main title as printed on the poster (empty if none)",
  "credits_text": "tagline, cast, director, studio, billing block text (empty if none)",
  "languages": ["en"],
  "other_text": "any other visible text not in title/credits",
  "mood": ["up to 5 short mood/atmosphere tags, e.g. dread, camp, gothic, erotic, surreal"],
  "fear_labels": [{"name":"label","conf":0.0}],
  "weapon": 0.0,
  "monster": 0.0,
  "person": 0.0,
  "animal": 0.0,
  "blood_gore": 0.0,
  "violence": 0.0,
  "sexual_content": 0.0,
  "sensitive": ["optional tags: violence, gore, nudity, sexual, occult, self-harm, none"],
  "moderation_notes": "one short sentence on sensitive content, or empty",
  "description": "1-2 sentence neutral visual description for search/embeddings"
}

Rules:
- fear_labels: up to 12 visual concepts useful for horror analysis (weapon, knife, gun, monster, creature, ghost, skull, blood, fire, water, silhouette, face, crowd, house, forest, vehicle, text-heavy, etc.). conf in 0..1.
- weapon/monster/person/animal/blood_gore/violence/sexual_content: likelihood 0..1 from the poster artwork.
- languages: ISO-like codes inferred from visible text (en, es, ja, ...). Use [] if no text.
- Keep description factual and concise (<= 45 words). No spoilers beyond what the poster shows.
"""

MAX_SIDE = 1280
JPEG_QUALITY = 85
MAX_BYTES = 4_500_000

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

_print_lock = threading.Lock()
_write_lock = threading.Lock()
_rate_lock = threading.Lock()
_next_slot = 0.0


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    with _print_lock:
        print(line, flush=True)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def acquire_rate_slot(min_interval_s: float) -> None:
    """Global spacing between Bedrock invokes to avoid throttle storms."""
    global _next_slot
    with _rate_lock:
        now = time.monotonic()
        slot = max(now, _next_slot)
        _next_slot = slot + min_interval_s
        wait = slot - now
    if wait > 0:
        time.sleep(wait)


def _is_jpeg_bytes(raw: bytes) -> bool:
    return len(raw) >= 3 and raw[0:3] == b"\xff\xd8\xff"


def resize_jpeg(path: Path) -> tuple[bytes, str]:
    """Always re-encode to a clean baseline JPEG for Bedrock.

    Many corpus files are named .jpg but are WebP/PNG; some real JPEGs are also
    rejected by Converse (odd MIME sniff). Never send raw disk bytes.
    """
    im = Image.open(path)
    im = im.convert("RGB")
    w, h = im.size
    scale = min(1.0, MAX_SIDE / float(max(w, h)))
    if scale < 1.0:
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    q = JPEG_QUALITY
    im.save(buf, format="JPEG", quality=q, optimize=True)
    data = buf.getvalue()
    while len(data) > MAX_BYTES and q > 40:
        q -= 10
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=q, optimize=True)
        data = buf.getvalue()
    if len(data) > MAX_BYTES:
        raise ValueError(f"image still >{MAX_BYTES} after compress ({len(data)})")
    if not _is_jpeg_bytes(data):
        raise ValueError("re-encode did not produce JPEG bytes")
    return data, "jpeg"


def _repair_json_blob(blob: str) -> str:
    """Best-effort fixes for common Nova Lite JSON breakage."""
    s = blob.strip()
    # trailing commas before } or ]
    s = re.sub(r",\s*([}\]])", r"\1", s)
    # invalid \u escapes (not followed by 4 hex digits)
    s = re.sub(r"\\u(?![0-9a-fA-F]{4})", r"\\\\u", s)
    # raw control chars outside of escapes (often from truncated unicode)
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", s)
    # if truncated mid-string / mid-object: close open quotes and braces/brackets
    if s.count('"') % 2 == 1:
        s += '"'
    # drop a dangling backslash at end
    if s.endswith("\\"):
        s = s[:-1] + " "
    opens = s.count("{") - s.count("}")
    open_br = s.count("[") - s.count("]")
    # if we closed a string but left a dangling comma, remove it
    s = re.sub(r",\s*$", "", s)
    if open_br > 0:
        s += "]" * open_br
    if opens > 0:
        s += "}" * opens
    s = re.sub(r",\s*([}\]])", r"\1", s)
    return s


def _extract_partial_json(text: str) -> dict:
    """Pull scalar/array fields with regex when json.loads still fails."""
    out: dict = {}
    for key in (
        "title_text",
        "credits_text",
        "other_text",
        "moderation_notes",
        "description",
    ):
        m = re.search(
            rf'"{key}"\s*:\s*"((?:\\.|[^"\\])*)"',
            text,
            flags=re.S,
        )
        if m:
            try:
                out[key] = json.loads(f'"{m.group(1)}"')
            except Exception:
                out[key] = m.group(1)
    for key in (
        "weapon",
        "monster",
        "person",
        "animal",
        "blood_gore",
        "violence",
        "sexual_content",
    ):
        m = re.search(rf'"{key}"\s*:\s*(-?\d+(?:\.\d+)?)', text)
        if m:
            out[key] = float(m.group(1))
    for key in ("languages", "mood", "sensitive"):
        m = re.search(rf'"{key}"\s*:\s*(\[[^\]]*\])', text, flags=re.S)
        if m:
            try:
                out[key] = json.loads(_repair_json_blob(m.group(1)))
            except Exception:
                pass
    # fear_labels as raw string if array present
    m = re.search(r'"fear_labels"\s*:\s*(\[.*?\])\s*[,}]', text, flags=re.S)
    if m:
        try:
            out["fear_labels"] = json.loads(_repair_json_blob(m.group(1)))
        except Exception:
            pass
    if not out:
        raise json.JSONDecodeError("no partial fields", text or "", 0)
    return out


def strip_json(text: str) -> dict:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    candidates = [t]
    m = re.search(r"\{.*\}", t, flags=re.S)
    if m:
        candidates.append(m.group(0))
    # also try from first { to end (truncated)
    i = t.find("{")
    if i >= 0:
        candidates.append(t[i:])

    last_err: Exception | None = None
    seen: set[str] = set()
    for cand in candidates:
        for blob in (cand, _repair_json_blob(cand)):
            if blob in seen:
                continue
            seen.add(blob)
            try:
                data = json.loads(blob)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError as e:
                last_err = e
                continue
    # last resort: partial field scrape
    try:
        return _extract_partial_json(t)
    except Exception:
        if last_err:
            raise last_err
        raise json.JSONDecodeError("unable to parse enrich JSON", t or "", 0)


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


def empty_row(pid: int, title: str, year, status: str, latency: float, err: str = "") -> dict:
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
        "model_id": DEFAULT_MODEL,
        "input_tokens": "",
        "output_tokens": "",
        "error": err[:500],
    }


def parse_enrich(pid: int, title: str, year, payload: dict, latency: float) -> dict:
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
            "model_id": payload.get("model_id") or DEFAULT_MODEL,
            "input_tokens": usage.get("inputTokens", ""),
            "output_tokens": usage.get("outputTokens", ""),
        }
    )
    return row, data


def load_done(path: Path) -> set[int]:
    done: set[int] = set()
    if not path.exists():
        return done
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if str(r.get("status") or "") != "ok":
                continue
            try:
                done.add(int(r["id"]))
            except (TypeError, ValueError):
                pass
    return done


def ensure_csv_header(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()


def append_rows(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with _write_lock:
        ensure_csv_header(path)
        with path.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
            for r in rows:
                w.writerow(r)
            f.flush()
            try:
                import os

                os.fsync(f.fileno())
            except OSError:
                pass


def write_progress(*, ok: int, err: int, completed: int, n_todo: int, done_prior: int) -> None:
    payload = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ok_run": ok,
        "err_run": err,
        "completed_run": completed,
        "n_todo": n_todo,
        "done_prior": done_prior,
        "ok_total_est": done_prior + ok,
        "csv": str(OUT_CSV),
        "json_dir": str(OUT_JSON),
    }
    with _write_lock:
        (OUT_DIR / "progress.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )


def _is_throttle(exc: Exception) -> bool:
    msg = str(exc)
    return "ThrottlingException" in msg or "TooManyRequests" in msg or "Rate exceeded" in msg


def invoke_one(client, lambda_name: str, model_id: str, img_bytes: bytes, fmt: str) -> dict:
    payload = {
        "mode": "enrich",
        "model_id": model_id,
        "image_b64": base64.b64encode(img_bytes).decode("ascii"),
        "image_format": fmt,
        "max_tokens": 700,
    }
    resp = client.invoke(
        FunctionName=lambda_name,
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


def invoke_bedrock_direct(
    client, model_id: str, img_bytes: bytes, fmt: str, *, max_tokens: int = 700
) -> dict:
    """Call Bedrock Converse directly (no Lambda bridge)."""
    resp = client.converse(
        modelId=model_id,
        messages=[
            {
                "role": "user",
                "content": [
                    {"image": {"format": fmt, "source": {"bytes": img_bytes}}},
                    {"text": ENRICH_PROMPT},
                ],
            }
        ],
        inferenceConfig={"temperature": 0, "maxTokens": max_tokens},
    )
    text = "".join(
        b.get("text", "")
        for b in resp.get("output", {}).get("message", {}).get("content", [])
        if "text" in b
    )
    return {
        "statusCode": 200,
        "model_id": model_id,
        "mode": "enrich",
        "text": text,
        "usage": resp.get("usage") or {},
    }


def _is_json_parse_error(exc: Exception) -> bool:
    if isinstance(exc, json.JSONDecodeError):
        return True
    name = type(exc).__name__
    msg = str(exc)
    return name == "JSONDecodeError" or "JSONDecodeError" in msg


def process_one(
    client,
    *,
    lambda_name: str,
    model_id: str,
    pid: int,
    title: str,
    year,
    min_interval_s: float = 0.4,
    max_retries: int = 6,
    direct: bool = False,
) -> dict:
    t0 = time.perf_counter()
    img = POSTERS / f"{pid}.jpg"
    if not img.exists():
        alt = POSTERS / f"{pid}.png"
        img = alt if alt.exists() else img
    try:
        if not img.exists():
            raise FileNotFoundError(f"missing poster {pid}")
        raw, fmt = resize_jpeg(img)
        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                acquire_rate_slot(min_interval_s)
                # bump tokens on JSON retries (truncation is a common cause)
                max_tokens = 700 if attempt == 0 else 1200
                if direct:
                    body = invoke_bedrock_direct(
                        client, model_id, raw, fmt, max_tokens=max_tokens
                    )
                else:
                    body = invoke_one(client, lambda_name, model_id, raw, fmt)
                lat = time.perf_counter() - t0
                row, data = parse_enrich(pid, title, year, body, lat)
                OUT_JSON.mkdir(parents=True, exist_ok=True)
                (OUT_JSON / f"{pid}.json").write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                return row
            except Exception as e:
                last_err = e
                retryable = _is_throttle(e) or _is_json_parse_error(e)
                if attempt + 1 < max_retries and retryable:
                    time.sleep(min(20.0, 1.25 * (2**attempt)))
                    continue
                raise
        assert last_err is not None
        raise last_err
    except Exception as e:
        lat = time.perf_counter() - t0
        err = f"{type(e).__name__}: {e}"
        return empty_row(pid, title, year, f"error: {err}"[:80], lat, err)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", default="", help="comma-separated ids subset")
    ap.add_argument(
        "--ids-file",
        default="",
        help="JSON list of ids, or newline/CSV text file (covers ids missing from posters.csv)",
    )
    ap.add_argument(
        "--meta-json",
        default="",
        help="optional posters_meta.json with by_id for title/year when not in posters.csv",
    )
    ap.add_argument("--lambda-name", default=DEFAULT_LAMBDA)
    ap.add_argument("--region", default=DEFAULT_REGION)
    ap.add_argument("--model-id", default=DEFAULT_MODEL)
    ap.add_argument(
        "--save-every",
        type=int,
        default=1,
        help="flush OK rows to local CSV every N results (default 1)",
    )
    ap.add_argument(
        "--flush-seconds",
        type=float,
        default=30.0,
        help="also flush pending OK rows at least every N seconds",
    )
    ap.add_argument(
        "--min-interval",
        type=float,
        default=0.45,
        help="min seconds between Bedrock invokes (global)",
    )
    ap.add_argument("--no-skip-done", action="store_true")
    ap.add_argument(
        "--direct",
        action="store_true",
        help="call Bedrock Converse directly (no Lambda bridge)",
    )
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.mkdir(parents=True, exist_ok=True)
    ensure_csv_header(OUT_CSV)

    posters = pd.read_csv(POSTERS_CSV, usecols=["id", "title", "year"])
    posters["id"] = posters["id"].astype(int)
    by_csv = {
        int(r.id): (str(r.title or ""), r.year)
        for r in posters.itertuples(index=False)
    }

    meta_by: dict[str, dict] = {}
    if args.meta_json:
        meta_path = Path(args.meta_json)
        if meta_path.exists():
            raw_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta_by = raw_meta.get("by_id") or raw_meta

    want: set[int] | None = None
    if args.ids_file:
        raw = Path(args.ids_file).read_text(encoding="utf-8").strip()
        if raw.startswith("["):
            want = {int(x) for x in json.loads(raw)}
        else:
            want = {
                int(x)
                for x in re.split(r"[\s,]+", raw)
                if x.strip() and re.fullmatch(r"-?\d+", x.strip())
            }
    elif args.ids:
        want = {int(x) for x in args.ids.split(",") if x.strip()}

    if want is not None:
        rows = []
        for pid in sorted(want):
            if pid in by_csv:
                title, year = by_csv[pid]
            else:
                m = meta_by.get(str(pid)) or meta_by.get(pid) or {}
                title = str(m.get("title") or "")
                year = m.get("year") or ""
            rows.append({"id": pid, "title": title, "year": year})
        posters = pd.DataFrame(rows)
    posters = posters.sort_values("id").reset_index(drop=True)

    done = set() if args.no_skip_done else load_done(OUT_CSV)
    todo = posters[~posters["id"].isin(done)].copy()
    if args.limit and args.limit > 0:
        todo = todo.head(args.limit).copy()

    mode = "direct" if args.direct else f"lambda:{args.lambda_name}"
    log(
        f"start n_todo={len(todo)} done={len(done)} workers={args.workers} "
        f"min_interval={args.min_interval}s save_every={args.save_every} "
        f"flush_seconds={args.flush_seconds} model={args.model_id} "
        f"mode={mode} region={args.region} out={OUT_CSV}"
    )
    if todo.empty:
        log("nothing to do")
        return 0

    cfg = Config(
        read_timeout=130,
        connect_timeout=30,
        retries={"max_attempts": 3, "mode": "adaptive"},
        max_pool_connections=max(args.workers + 4, 20),
    )
    if args.direct:
        client = boto3.client("bedrock-runtime", region_name=args.region, config=cfg)
    else:
        client = boto3.client("lambda", region_name=args.region, config=cfg)

    ok = err = 0
    t_run = time.perf_counter()
    n_todo = len(todo)
    chunk_size = max(args.workers * 20, 100)
    completed = 0
    stop = {"flag": False}
    pending_box: dict[str, list[dict]] = {"rows": []}
    last_flush = time.monotonic()

    def flush_pending() -> int:
        rows = pending_box["rows"]
        ok_rows = [r for r in rows if str(r.get("status")) == "ok"]
        pending_box["rows"] = [r for r in rows if str(r.get("status")) != "ok"]
        if ok_rows:
            append_rows(OUT_CSV, ok_rows)
            write_progress(
                ok=ok,
                err=err,
                completed=completed,
                n_todo=n_todo,
                done_prior=len(done),
            )
            log(f"checkpoint flushed ok_batch={len(ok_rows)} ok_run={ok} → {OUT_CSV.name}")
        return len(ok_rows)

    def on_signal(signum, _frame) -> None:
        stop["flag"] = True
        log(f"signal {signum} received — flushing local checkpoint")
        flush_pending()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    rows_iter = list(todo.itertuples(index=False))
    for chunk_start in range(0, len(rows_iter), chunk_size):
        if stop["flag"]:
            break
        chunk = rows_iter[chunk_start : chunk_start + chunk_size]
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {
                ex.submit(
                    process_one,
                    client,
                    lambda_name=args.lambda_name,
                    model_id=args.model_id,
                    pid=int(r.id),
                    title=str(r.title),
                    year=r.year,
                    min_interval_s=args.min_interval,
                    direct=args.direct,
                ): int(r.id)
                for r in chunk
            }
            for fut in as_completed(futs):
                if stop["flag"]:
                    break
                pid = futs[fut]
                completed += 1
                try:
                    row = fut.result()
                except Exception as e:
                    row = empty_row(pid, "", "", f"error: {e}"[:80], 0.0, str(e))
                pending_box["rows"].append(row)
                if str(row.get("status")) == "ok":
                    ok += 1
                else:
                    err += 1
                    with _write_lock:
                        err_path = OUT_DIR / "nova_enrich_errors.csv"
                        write_header = (
                            not err_path.exists() or err_path.stat().st_size == 0
                        )
                        with err_path.open("a", newline="", encoding="utf-8") as f:
                            w = csv.DictWriter(
                                f, fieldnames=CSV_FIELDS, extrasaction="ignore"
                            )
                            if write_header:
                                w.writeheader()
                            w.writerow(row)
                            f.flush()

                n_pending_ok = sum(
                    1 for r in pending_box["rows"] if str(r.get("status")) == "ok"
                )
                now = time.monotonic()
                if n_pending_ok >= args.save_every or (now - last_flush) >= args.flush_seconds:
                    flush_pending()
                    last_flush = now

                if (
                    completed % 10 == 0
                    or completed == n_todo
                    or str(row.get("status")) != "ok"
                ):
                    elapsed = time.perf_counter() - t_run
                    rate = ok / elapsed if elapsed > 0 else 0
                    eta = (n_todo - completed) / rate if rate > 0 else 0
                    log(
                        f"[{completed}/{n_todo}] id={pid} status={row.get('status')} "
                        f"ok={ok} err={err} rate={rate:.2f}/s eta={eta/3600:.2f}h "
                        f"desc={(row.get('description') or '')[:60]!r}"
                    )
        flush_pending()
        last_flush = time.monotonic()

    flush_pending()
    elapsed = time.perf_counter() - t_run
    write_progress(
        ok=ok, err=err, completed=completed, n_todo=n_todo, done_prior=len(done)
    )
    log(f"LISTO ok={ok} err={err} elapsed={elapsed/60:.1f}m → {OUT_CSV}")
    return 0 if err == 0 or ok > 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("interrupted")
        sys.exit(130)
