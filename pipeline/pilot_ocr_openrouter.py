#!/usr/bin/env python3
"""Pilot: OpenRouter free VLMs on hard12 OCR sample.

Default models:
  gemma     → google/gemma-4-26b-a4b-it:free
  omni      → nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free
  gemma31   → google/gemma-4-31b-it          (pago; :free si --prefer-free)
  gemini25  → google/gemini-2.5-flash
  qwen3vl32 → qwen/qwen3-vl-32b-instruct

Reads OPENROUTER_API_KEY from the environment, or from pipeline/.env.local
(never logs the key). OpenAI-compatible client → https://openrouter.ai/api/v1

  # hard12 with Gemma only (default)
  python3 pilot_ocr_openrouter.py

  # batch techo
  python3 pilot_ocr_openrouter.py --models gemini25,qwen3vl32,gemma31

  # smoke
  python3 pilot_ocr_openrouter.py --limit 1 --models gemini25

Outputs:
  data/qa/ocr_hard12_openrouter/{model}/{id}.txt
  data/qa/ocr_hard12_openrouter/results.csv
  data/qa/ocr_hard12_openrouter/openrouter_sidecar.csv
  data/qa/ocr_hard12_openrouter/openrouter_usage.csv
"""
from __future__ import annotations

import argparse
import base64
import csv
import os
import re
import sys
import time
import traceback
from pathlib import Path

from ocr_metrics import title_overlap_score

PIPE = Path(__file__).resolve().parent
DATA = PIPE / "data"
POSTERS_CSV = DATA / "posters.csv"
ENV_LOCAL = PIPE / ".env.local"

DEFAULT_IDS = DATA / "qa" / "ocr_qwen_hard" / "sample_ids.txt"
DEFAULT_OUT_DIR = DATA / "qa" / "ocr_hard12_openrouter"
DEFAULT_POSTERS_CANDIDATES = (
    DATA / "qa" / "_ocr_hard12_new_stage" / "posters",
    DATA / "qa" / "_ocr_qwen_hard_stage" / "posters",
    DATA / "posters",
)

OUT_DIR = DEFAULT_OUT_DIR
RESULTS_CSV = OUT_DIR / "results.csv"
SAMPLE_IDS = OUT_DIR / "sample_ids.txt"
SIDECAR_CSV = OUT_DIR / "openrouter_sidecar.csv"
USAGE_CSV = OUT_DIR / "openrouter_usage.csv"
POSTERS = DEFAULT_POSTERS_CANDIDATES[0]

RESULT_FIELDS = [
    "id",
    "title",
    "year",
    "model",
    "text",
    "chars",
    "title_overlap_score",
    "latency_s",
    "status",
]
USAGE_FIELDS = [
    "id",
    "model",
    "api_model",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "latency_s",
    "status",
]

OCR_PROMPT = (
    "Extract ALL visible text from this movie poster. "
    "Return plain text only, no commentary."
)
MAX_RETRIES = 8
BASE_BACKOFF_S = 3.0
OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# short key → (api model id, results.csv tag)
MODEL_CATALOG = {
    "gemma": (
        "google/gemma-4-26b-a4b-it:free",
        "gemma4-26b-free-hard",
    ),
    "omni": (
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "nemotron-omni-free-hard",
    ),
    "gemma31": (
        "google/gemma-4-31b-it",
        "gemma4-31b",
    ),
    "gemma31free": (
        "google/gemma-4-31b-it:free",
        "gemma4-31b-free",
    ),
    "gemini25": (
        "google/gemini-2.5-flash",
        "gemini-2.5-flash-or-hard",
    ),
    "qwen3vl32": (
        "qwen/qwen3-vl-32b-instruct",
        "qwen3-vl-32b-hard",
    ),
}
DEFAULT_MODELS = "gemma"


def configure_out_dir(path: str | Path) -> None:
    global OUT_DIR, RESULTS_CSV, SAMPLE_IDS, SIDECAR_CSV, USAGE_CSV
    OUT_DIR = Path(path)
    RESULTS_CSV = OUT_DIR / "results.csv"
    SAMPLE_IDS = OUT_DIR / "sample_ids.txt"
    SIDECAR_CSV = OUT_DIR / "openrouter_sidecar.csv"
    USAGE_CSV = OUT_DIR / "openrouter_usage.csv"


def configure_posters_dir(path: str | Path) -> None:
    global POSTERS
    POSTERS = Path(path)


def resolve_posters_dir(explicit: str) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.is_dir():
            raise SystemExit(f"posters dir missing: {p}")
        return p
    for cand in DEFAULT_POSTERS_CANDIDATES:
        if cand.is_dir() and any(cand.glob("*.jpg")):
            return cand
    raise SystemExit(
        "no posters dir found; pass --posters-dir "
        f"(tried {[str(c) for c in DEFAULT_POSTERS_CANDIDATES]})"
    )


def load_openrouter_key() -> str:
    env = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if env:
        return env
    if ENV_LOCAL.is_file():
        for line in ENV_LOCAL.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(
                r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line
            )
            if not m:
                continue
            k, v = m.group(1), m.group(2).strip().strip('"').strip("'")
            if k == "OPENROUTER_API_KEY" and len(v) > 20:
                return v
    raise SystemExit(
        "OPENROUTER_API_KEY not set (env or pipeline/.env.local)"
    )


def _redact(msg: str, key: str = "") -> str:
    s = str(msg or "")
    s = re.sub(r"sk-or-v1-[A-Za-z0-9_-]{10,}", "sk-or-[REDACTED]", s)
    s = re.sub(r"sk-[A-Za-z0-9_-]{10,}", "sk-[REDACTED]", s)
    if key and key in s:
        s = s.replace(key, "sk-or-[REDACTED]")
    return s


def load_sample(ids_file: Path) -> list[dict]:
    posters_by_id: dict[int, dict] = {}
    with POSTERS_CSV.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (TypeError, ValueError, KeyError):
                continue
            posters_by_id[pid] = {
                "id": pid,
                "title": r.get("title") or "",
                "year": r.get("year") or "",
            }
    raw = ids_file.read_text(encoding="utf-8")
    ids = [int(x) for x in re.split(r"[\s,]+", raw.strip()) if x.strip()]
    out: list[dict] = []
    for pid in ids:
        if pid in posters_by_id:
            out.append(dict(posters_by_id[pid]))
        else:
            out.append({"id": pid, "title": "", "year": ""})
    return out


def read_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def write_csv_rows(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def upsert_rows(existing: list[dict], row: dict) -> list[dict]:
    model = str(row["model"])
    pid = str(row["id"])
    out: list[dict] = []
    replaced = False
    for r in existing:
        if str(r.get("model") or "") == model and str(r.get("id") or "") == pid:
            out.append(row)
            replaced = True
        else:
            out.append(r)
    if not replaced:
        out.append(row)
    return out


def write_model_txt(row: dict) -> None:
    if row.get("status") != "ok" or not row.get("text"):
        return
    model_dir = OUT_DIR / str(row["model"])
    model_dir.mkdir(parents=True, exist_ok=True)
    raw = str(row["text"]).replace("\\n", "\n")
    (model_dir / f"{row['id']}.txt").write_text(raw, encoding="utf-8")


def persist_row(row: dict) -> None:
    write_model_txt(row)
    side = upsert_rows(read_csv_rows(SIDECAR_CSV), row)
    write_csv_rows(SIDECAR_CSV, side, RESULT_FIELDS)
    try:
        merged = upsert_rows(read_csv_rows(RESULTS_CSV), row)
        write_csv_rows(RESULTS_CSV, merged, RESULT_FIELDS)
    except OSError as e:
        print(f"  warn: results.csv merge failed (sidecar kept): {e}", flush=True)


def persist_usage(row: dict) -> None:
    usage = upsert_rows(read_csv_rows(USAGE_CSV), row)
    write_csv_rows(USAGE_CSV, usage, USAGE_FIELDS)


def final_merge_sidecar() -> int:
    side = read_csv_rows(SIDECAR_CSV)
    if not side:
        return 0
    merged = read_csv_rows(RESULTS_CSV)
    for row in side:
        merged = upsert_rows(merged, row)
    write_csv_rows(RESULTS_CSV, merged, RESULT_FIELDS)
    return len(side)


def csv_text(text: str) -> str:
    return (text or "").replace("\n", "\\n")


def make_row(
    pid: int,
    title: str,
    year,
    model: str,
    text: str,
    latency_s: float,
    status: str,
) -> dict:
    ok = status == "ok"
    score = title_overlap_score(text, title) if ok else 0.0
    return {
        "id": pid,
        "title": title,
        "year": year,
        "model": model,
        "text": csv_text(text) if ok else "",
        "chars": len(text) if ok else 0,
        "title_overlap_score": score,
        "latency_s": round(latency_s, 3),
        "status": status,
    }


def _mime_for(path: Path) -> str:
    suf = path.suffix.lower()
    if suf in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suf == ".png":
        return "image/png"
    if suf == ".webp":
        return "image/webp"
    return "image/jpeg"


def _is_throttle(err: Exception) -> bool:
    msg = _redact(str(err)).lower()
    status = getattr(err, "status_code", None) or getattr(err, "http_status", None)
    if status in (429, 500, 502, 503, 504):
        return True
    # OpenAI SDK wraps HTTPError
    body = ""
    try:
        resp = getattr(err, "response", None)
        if resp is not None:
            status = getattr(resp, "status_code", status)
            body = str(getattr(resp, "text", "") or "")[:500].lower()
    except Exception:
        pass
    if status in (429, 500, 502, 503, 504):
        return True
    blob = f"{msg} {body}"
    return any(
        k in blob
        for k in (
            "rate limit",
            "rate-limited",
            "too many requests",
            "429",
            "timeout",
            "overloaded",
            "temporarily",
            "retry shortly",
        )
    )


def _extract_text(choice) -> str:
    if choice is None:
        return ""
    msg = getattr(choice, "message", None)
    if msg is None and isinstance(choice, dict):
        msg = choice.get("message")
    if msg is None:
        return ""
    content = getattr(msg, "content", None)
    if content is None and isinstance(msg, dict):
        content = msg.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            else:
                t = getattr(block, "text", None)
                if t:
                    parts.append(str(t))
        return "\n".join(p for p in parts if p).strip()
    return (str(content) if content is not None else "").strip()


def openrouter_ocr(client, path: Path, api_model: str, api_key: str) -> tuple[str, dict]:
    data = path.read_bytes()
    if not data:
        raise ValueError(f"empty image: {path}")
    if len(data) > 20_000_000:
        raise ValueError(f"image too large: {len(data)}")

    b64 = base64.b64encode(data).decode("ascii")
    mime = _mime_for(path)
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.chat.completions.create(
                model=api_model,
                temperature=0,
                max_tokens=2048,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": OCR_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime};base64,{b64}",
                                },
                            },
                        ],
                    }
                ],
            )
            choice = (resp.choices or [None])[0]
            text = _extract_text(choice)
            usage = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
            if getattr(resp, "usage", None) is not None:
                usage["prompt_tokens"] = int(resp.usage.prompt_tokens or 0)
                usage["completion_tokens"] = int(resp.usage.completion_tokens or 0)
                usage["total_tokens"] = int(
                    resp.usage.total_tokens
                    or (usage["prompt_tokens"] + usage["completion_tokens"])
                )
            # Free pool sometimes returns 200 with empty content — retry
            if not text:
                raise RuntimeError("empty model content (retryable)")
            return text, usage
        except Exception as e:
            last_err = e
            retryable = _is_throttle(e) or "empty model content" in str(e).lower()
            if attempt + 1 < MAX_RETRIES and retryable:
                sleep_s = BASE_BACKOFF_S * (2**attempt)
                print(
                    f"    throttle/backoff {sleep_s:.1f}s "
                    f"(attempt {attempt + 1}/{MAX_RETRIES}): {_redact(e, api_key)}",
                    flush=True,
                )
                time.sleep(sleep_s)
                continue
            raise RuntimeError(_redact(e, api_key)) from None
    assert last_err is not None
    raise RuntimeError(_redact(last_err, api_key)) from None


def seed_sidecar_from_txt(model_name: str, sample: list[dict]) -> int:
    model_dir = OUT_DIR / model_name
    if not model_dir.is_dir():
        return 0
    by_id = {int(r["id"]): r for r in sample}
    side_ids = {
        int(r["id"])
        for r in read_csv_rows(SIDECAR_CSV)
        if r.get("model") == model_name
        and str(r.get("status") or "") == "ok"
        and str(r.get("id") or "").isdigit()
    }
    n = 0
    for p in sorted(model_dir.glob("*.txt")):
        try:
            pid = int(p.stem)
        except ValueError:
            continue
        if pid in side_ids:
            continue
        meta = by_id.get(pid) or {"id": pid, "title": "", "year": ""}
        text = p.read_text(encoding="utf-8")
        row = make_row(
            pid,
            str(meta.get("title") or ""),
            meta.get("year", ""),
            model_name,
            text,
            0.0,
            "ok",
        )
        persist_row(row)
        n += 1
    return n


def done_ok_ids(model_name: str) -> set[int]:
    done: set[int] = set()
    for path in (RESULTS_CSV, SIDECAR_CSV):
        for r in read_csv_rows(path):
            if r.get("model") != model_name:
                continue
            if str(r.get("status") or "") != "ok":
                continue
            try:
                done.add(int(r["id"]))
            except (TypeError, ValueError):
                pass
    model_dir = OUT_DIR / model_name
    if model_dir.is_dir():
        for p in model_dir.glob("*.txt"):
            try:
                done.add(int(p.stem))
            except ValueError:
                pass
    return done


def run_model(
    sample: list[dict],
    *,
    model_key: str,
    api_model: str,
    result_tag: str,
    skip_done: bool,
    client,
    api_key: str,
) -> dict:
    print(
        f"\n=== key={model_key} result={result_tag} api={api_model} "
        f"n={len(sample)} posters={POSTERS} ===",
        flush=True,
    )

    seeded = seed_sidecar_from_txt(result_tag, sample)
    if seeded:
        print(f"  seeded {seeded} rows from existing .txt into sidecar", flush=True)

    done_ok = done_ok_ids(result_tag) if skip_done else set()
    if done_ok:
        print(f"  skip {len(done_ok)} already-ok ids", flush=True)

    n_todo = sum(1 for r in sample if int(r["id"]) not in done_ok)
    totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "n_ok": 0,
        "n_err": 0,
    }
    if n_todo == 0:
        print(f"  nothing to do for {result_tag}", flush=True)
        return totals

    done_n = 0
    for r in sample:
        pid = int(r["id"])
        title = str(r.get("title") or "")
        year = r.get("year", "")
        if skip_done and pid in done_ok:
            continue
        done_n += 1
        img = POSTERS / f"{pid}.jpg"
        if not img.exists():
            alt = POSTERS / f"{pid}.png"
            img = alt if alt.exists() else img
        t0 = time.perf_counter()
        status = "ok"
        text = ""
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        try:
            if not img.exists():
                raise FileNotFoundError(f"missing {img}")
            text, usage = openrouter_ocr(client, img, api_model, api_key)
        except Exception as e:
            status = f"error: {_redact(e, api_key)}"[:500]
            print(f"  [{done_n}/{n_todo}] id={pid} FAIL {status}", flush=True)
            traceback.print_exc()
            totals["n_err"] += 1
        lat = time.perf_counter() - t0
        row = make_row(pid, title, year, result_tag, text, lat, status)
        persist_row(row)
        persist_usage(
            {
                "id": pid,
                "model": result_tag,
                "api_model": api_model,
                "prompt_tokens": usage["prompt_tokens"],
                "completion_tokens": usage["completion_tokens"],
                "total_tokens": usage["total_tokens"],
                "latency_s": round(lat, 3),
                "status": status if status == "ok" else status[:80],
            }
        )
        if status == "ok":
            totals["n_ok"] += 1
            totals["prompt_tokens"] += usage["prompt_tokens"]
            totals["completion_tokens"] += usage["completion_tokens"]
            totals["total_tokens"] += usage["total_tokens"]
        print(
            f"  [{done_n}/{n_todo}] id={pid} status={status[:40]} "
            f"chars={row['chars']} overlap={row['title_overlap_score']} "
            f"{row['latency_s']}s tok={usage['total_tokens']}",
            flush=True,
        )
        # gentle pacing for shared free pool
        time.sleep(1.0)
    return totals


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--ids-file",
        default=str(DEFAULT_IDS),
        help=f"sample ids (default: {DEFAULT_IDS})",
    )
    ap.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help=f"output dir (default: {DEFAULT_OUT_DIR})",
    )
    ap.add_argument(
        "--posters-dir",
        default="",
        help="posters dir (default: hard12_new stage → qwen_hard stage → data/posters)",
    )
    ap.add_argument(
        "--models",
        default=DEFAULT_MODELS,
        help="comma-separated keys: gemma,omni,gemma31,gemma31free,gemini25,qwen3vl32",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="optional cap on sample size (0 = all)",
    )
    ap.add_argument(
        "--no-skip-done",
        action="store_true",
        help="re-run even if status=ok already present for this model",
    )
    args = ap.parse_args()

    configure_out_dir(args.out_dir)
    configure_posters_dir(resolve_posters_dir(args.posters_dir))

    keys = [k.strip().lower() for k in args.models.split(",") if k.strip()]
    unknown = [k for k in keys if k not in MODEL_CATALOG]
    if unknown:
        raise SystemExit(
            f"unknown models {unknown}; choose from {list(MODEL_CATALOG)}"
        )
    if not keys:
        raise SystemExit("empty --models")

    ids_path = Path(args.ids_file)
    if not ids_path.exists():
        raise SystemExit(f"missing ids file: {ids_path}")

    api_key = load_openrouter_key()
    sample = load_sample(ids_path)
    if args.limit and args.limit > 0:
        sample = sample[: args.limit]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLE_IDS.write_text(
        "\n".join(str(int(r["id"])) for r in sample) + "\n", encoding="utf-8"
    )

    print(f"sample n={len(sample)} from {ids_path}", flush=True)
    print(f"posters_dir={POSTERS}", flush=True)
    print(f"out_dir={OUT_DIR}", flush=True)
    print(f"models={keys}", flush=True)
    print("OPENROUTER_API_KEY=set (value not logged)", flush=True)

    try:
        from openai import OpenAI
    except ImportError as e:
        raise SystemExit(f"openai package required: {e}") from e

    client = OpenAI(
        api_key=api_key,
        base_url=OPENROUTER_BASE,
        default_headers={
            "HTTP-Referer": "https://github.com/juanpduque/what-fear-looks-like",
            "X-Title": "what-fear-looks-like-ocr-hard12",
        },
    )

    for key in keys:
        api_model, result_tag = MODEL_CATALOG[key]
        totals = run_model(
            sample,
            model_key=key,
            api_model=api_model,
            result_tag=result_tag,
            skip_done=not args.no_skip_done,
            client=client,
            api_key=api_key,
        )
        print(
            f"  {result_tag}: this_run ok={totals['n_ok']} err={totals['n_err']} "
            f"tok={totals['total_tokens']}",
            flush=True,
        )

    n_side = final_merge_sidecar()
    print(f"final sidecar merge → {n_side} rows into {RESULTS_CSV}", flush=True)

    rows = read_csv_rows(RESULTS_CSV)
    for key in keys:
        _, tag = MODEL_CATALOG[key]
        n = sum(1 for r in rows if r.get("model") == tag)
        n_ok = sum(
            1
            for r in rows
            if r.get("model") == tag and str(r.get("status") or "") == "ok"
        )
        vals: list[float] = []
        for r in rows:
            if r.get("model") != tag or str(r.get("status") or "") != "ok":
                continue
            try:
                vals.append(float(r["title_overlap_score"]))
            except (TypeError, ValueError):
                pass
        mean_ov = round(sum(vals) / len(vals), 4) if vals else float("nan")
        print(f"  {tag}: {n_ok}/{n} ok mean_overlap={mean_ov}", flush=True)

    print(f"\nLISTO → {RESULTS_CSV} ({len(rows)} rows)", flush=True)
    print(f"sidecar → {SIDECAR_CSV}", flush=True)
    print(f"usage → {USAGE_CSV}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
