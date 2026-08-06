#!/usr/bin/env python3
"""Pilot: Vertex AI Gemini vision OCR on ocr_pilot_v2 sample.

Uses ADC (gcloud application-default credentials) against Vertex generateContent.
Writes per-id txt under gemini-flash/ and a sidecar CSV, then merge-upserts into
results.csv by (model, id) so concurrent Bedrock runs are not clobbered on our
side. Skips ids already present with status=ok (in results or sidecar).

  python3 pilot_ocr_gemini.py
  python3 pilot_ocr_gemini.py --models gemini-flash --limit 5
  python3 pilot_ocr_gemini.py --no-skip-done

Requires: gcloud ADC + Vertex AI API on project playground-ia-502703.
"""
from __future__ import annotations

import argparse
import base64
import csv
import os
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"


def title_overlap_score(ocr_text: str, title: str) -> float:
    """Normalized token overlap (inlined to avoid numpy import side-effects)."""

    def toks(s: str) -> set[str]:
        return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(t) > 1}

    tt = toks(title)
    if not tt:
        return 0.0
    ot = toks(ocr_text)
    return round(len(tt & ot) / len(tt), 4)
POSTERS = DATA / "posters"
POSTERS_CSV = DATA / "posters.csv"
DEFAULT_OUT_DIR = DATA / "qa" / "ocr_pilot_v2"
OUT_DIR = DEFAULT_OUT_DIR
RESULTS_CSV = OUT_DIR / "results.csv"
SAMPLE_IDS = OUT_DIR / "sample_ids.txt"
SIDECAR_CSV = OUT_DIR / "gemini_flash_sidecar.csv"

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

DEFAULT_PROJECT = "playground-ia-502703"
DEFAULT_LOCATION = "us-central1"
OCR_PROMPT = (
    "Extract ALL visible text from this movie poster. "
    "Return plain text only, no commentary."
)
MAX_RETRIES = 8
BASE_BACKOFF_S = 2.0

MODEL_CATALOG: dict[str, str] = {
    "gemini-flash": "gemini-2.5-flash",
}


def configure_out_dir(path: str | Path) -> None:
    global OUT_DIR, RESULTS_CSV, SAMPLE_IDS, SIDECAR_CSV
    OUT_DIR = Path(path)
    RESULTS_CSV = OUT_DIR / "results.csv"
    SAMPLE_IDS = OUT_DIR / "sample_ids.txt"
    SIDECAR_CSV = OUT_DIR / "gemini_flash_sidecar.csv"


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


def write_csv_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RESULT_FIELDS, extrasaction="ignore")
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
    """Write txt + sidecar always; merge into shared results.csv best-effort."""
    write_model_txt(row)
    side = upsert_rows(read_csv_rows(SIDECAR_CSV), row)
    write_csv_rows(SIDECAR_CSV, side)
    try:
        merged = upsert_rows(read_csv_rows(RESULTS_CSV), row)
        write_csv_rows(RESULTS_CSV, merged)
    except OSError as e:
        print(f"  warn: results.csv merge failed (sidecar kept): {e}", flush=True)


def final_merge_sidecar() -> int:
    """Re-merge all sidecar rows into results.csv (recover from Bedrock clobber)."""
    side = read_csv_rows(SIDECAR_CSV)
    if not side:
        return 0
    merged = read_csv_rows(RESULTS_CSV)
    for row in side:
        merged = upsert_rows(merged, row)
    write_csv_rows(RESULTS_CSV, merged)
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
    if suf == ".gif":
        return "image/gif"
    return "image/jpeg"


def _access_token() -> str:
    try:
        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        req = google.auth.transport.requests.Request()
        creds.refresh(req)
        if creds.token:
            return creds.token
    except Exception as e:
        print(f"  google.auth unavailable: {e}", flush=True)

    tok = subprocess.check_output(
        ["gcloud", "auth", "application-default", "print-access-token"],
        text=True,
        stderr=subprocess.PIPE,
    ).strip()
    if not tok:
        raise RuntimeError("empty ADC token")
    return tok


def _is_throttle(status_code: int, body: str) -> bool:
    if status_code in (429, 503, 504):
        return True
    msg = (body or "").lower()
    return any(
        k in msg
        for k in (
            "resource exhausted",
            "rate limit",
            "too many requests",
            "quota exceeded",
            "unavailable",
            "deadline exceeded",
        )
    )


def _extract_text(resp: dict) -> str:
    parts: list[str] = []
    for cand in resp.get("candidates") or []:
        content = cand.get("content") or {}
        for part in content.get("parts") or []:
            if isinstance(part, dict) and "text" in part:
                parts.append(part.get("text") or "")
    return "\n".join(parts).strip()


def gemini_ocr(
    session,
    *,
    token: str,
    project: str,
    location: str,
    model_id: str,
    path: Path,
) -> tuple[str, str]:
    """Return (text, possibly_refreshed_token)."""
    import requests

    data = path.read_bytes()
    if not data:
        raise ValueError(f"empty image: {path}")
    if len(data) > 18_000_000:
        raise ValueError(f"image too large: {len(data)}")

    url = (
        f"https://{location}-aiplatform.googleapis.com/v1/"
        f"projects/{project}/locations/{location}/publishers/google/"
        f"models/{model_id}:generateContent"
    )
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": OCR_PROMPT},
                    {
                        "inlineData": {
                            "mimeType": _mime_for(path),
                            "data": base64.b64encode(data).decode(),
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 2048,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": project,
    }

    last_err: Exception | None = None
    current_token = token
    for attempt in range(MAX_RETRIES):
        try:
            headers["Authorization"] = f"Bearer {current_token}"
            r = session.post(url, headers=headers, json=body, timeout=120)
            if r.status_code == 401 and attempt + 1 < MAX_RETRIES:
                current_token = _access_token()
                print(
                    f"    401 → refreshed ADC token "
                    f"(attempt {attempt + 1}/{MAX_RETRIES})",
                    flush=True,
                )
                continue
            if _is_throttle(r.status_code, r.text) and attempt + 1 < MAX_RETRIES:
                sleep_s = BASE_BACKOFF_S * (2**attempt)
                print(
                    f"    throttle/backoff {sleep_s:.1f}s "
                    f"(attempt {attempt + 1}/{MAX_RETRIES}): "
                    f"HTTP {r.status_code}",
                    flush=True,
                )
                time.sleep(sleep_s)
                continue
            if not r.ok:
                raise RuntimeError(f"Vertex HTTP {r.status_code}: {r.text[:400]}")
            resp = r.json()
            if "error" in resp:
                err = resp["error"]
                msg = err if isinstance(err, str) else err.get("message", str(err))
                raise RuntimeError(msg)
            return _extract_text(resp), current_token
        except requests.RequestException as e:
            last_err = e
            if attempt + 1 < MAX_RETRIES:
                sleep_s = BASE_BACKOFF_S * (2**attempt)
                print(
                    f"    network/backoff {sleep_s:.1f}s "
                    f"(attempt {attempt + 1}/{MAX_RETRIES}): {e}",
                    flush=True,
                )
                time.sleep(sleep_s)
                continue
            raise
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            if attempt + 1 < MAX_RETRIES and any(
                k in msg for k in ("resource exhausted", "rate limit", "unavailable")
            ):
                sleep_s = BASE_BACKOFF_S * (2**attempt)
                print(
                    f"    throttle/backoff {sleep_s:.1f}s "
                    f"(attempt {attempt + 1}/{MAX_RETRIES}): {e}",
                    flush=True,
                )
                time.sleep(sleep_s)
                continue
            raise
    assert last_err is not None
    raise last_err


def seed_sidecar_from_txt(model_name: str, sample: list[dict]) -> int:
    """Rebuild sidecar/results rows for ids that only have .txt (e.g. after clobber)."""
    model_dir = OUT_DIR / model_name
    if not model_dir.is_dir():
        return 0
    by_id = {int(r["id"]): r for r in sample}
    side_ids = {
        int(r["id"])
        for r in read_csv_rows(SIDECAR_CSV)
        if r.get("model") == model_name and str(r.get("status") or "") == "ok"
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
    # Also treat existing txt as done if sidecar/results were clobbered
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
    model_id: str,
    model_name: str,
    skip_done: bool,
    project: str,
    location: str,
    session,
    token: str,
) -> None:
    print(
        f"\n=== model={model_name} vertex={model_id} "
        f"project={project} location={location} n={len(sample)} ===",
        flush=True,
    )

    seeded = seed_sidecar_from_txt(model_name, sample)
    if seeded:
        print(f"  seeded {seeded} rows from existing .txt into sidecar", flush=True)

    done_ok = done_ok_ids(model_name) if skip_done else set()
    if done_ok:
        print(f"  skip {len(done_ok)} already-ok ids", flush=True)

    n_todo = sum(1 for r in sample if int(r["id"]) not in done_ok)
    if n_todo == 0:
        print(f"  nothing to do for {model_name}", flush=True)
        return

    done_n = 0
    current_token = token
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
        try:
            if not img.exists():
                raise FileNotFoundError(f"missing {img}")
            text, current_token = gemini_ocr(
                session,
                token=current_token,
                project=project,
                location=location,
                model_id=model_id,
                path=img,
            )
        except Exception as e:
            status = f"error: {e}"[:500]
            print(f"  [{done_n}/{n_todo}] id={pid} FAIL {status}", flush=True)
            traceback.print_exc()
        lat = time.perf_counter() - t0
        row = make_row(pid, title, year, model_name, text, lat, status)
        persist_row(row)
        print(
            f"  [{done_n}/{n_todo}] id={pid} status={status[:40]} "
            f"chars={row['chars']} overlap={row['title_overlap_score']} "
            f"{row['latency_s']}s",
            flush=True,
        )


def parse_models(raw: str) -> list[tuple[str, str]]:
    tags = [t.strip() for t in raw.split(",") if t.strip()]
    if not tags:
        raise SystemExit("no models specified")
    out: list[tuple[str, str]] = []
    for tag in tags:
        if tag not in MODEL_CATALOG:
            known = ", ".join(sorted(MODEL_CATALOG))
            raise SystemExit(f"unknown model tag {tag!r}; known: {known}")
        out.append((tag, MODEL_CATALOG[tag]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--models",
        default="gemini-flash",
        help="comma-separated tags: " + ",".join(sorted(MODEL_CATALOG)),
    )
    ap.add_argument(
        "--ids-file",
        default="",
        help="sample id list (default: <out-dir>/sample_ids.txt)",
    )
    ap.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help="output dir (default: data/qa/ocr_pilot_v2)",
    )
    ap.add_argument(
        "--project",
        default=os.environ.get("GCP_PROJECT", DEFAULT_PROJECT),
        help="GCP project for Vertex",
    )
    ap.add_argument(
        "--location",
        default=os.environ.get("GCP_LOCATION", DEFAULT_LOCATION),
        help="Vertex location (default: us-central1)",
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
    ids_path = Path(args.ids_file) if args.ids_file else (OUT_DIR / "sample_ids.txt")
    if not ids_path.exists():
        raise SystemExit(f"missing ids file: {ids_path}")

    models = parse_models(args.models)
    sample = load_sample(ids_path)
    if args.limit and args.limit > 0:
        sample = sample[: args.limit]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"sample n={len(sample)} from {ids_path}", flush=True)
    print(f"models: {[t for t, _ in models]}", flush=True)
    print(f"project={args.project} location={args.location}", flush=True)

    try:
        import requests
    except ImportError as e:
        raise SystemExit(f"requests required: {e}") from e

    try:
        token = _access_token()
    except Exception as e:
        raise SystemExit(f"ADC token failed: {e}") from e

    session = requests.Session()
    for tag, mid in models:
        run_model(
            sample,
            model_id=mid,
            model_name=tag,
            skip_done=not args.no_skip_done,
            project=args.project,
            location=args.location,
            session=session,
            token=token,
        )

    n_side = final_merge_sidecar()
    print(f"final sidecar merge → {n_side} gemini rows into {RESULTS_CSV}", flush=True)

    rows = read_csv_rows(RESULTS_CSV)
    for tag, _ in models:
        n = sum(1 for r in rows if r.get("model") == tag)
        n_ok = sum(
            1
            for r in rows
            if r.get("model") == tag and str(r.get("status") or "") == "ok"
        )
        print(f"  {tag}: {n_ok}/{n} ok", flush=True)
    print(f"\nLISTO → {RESULTS_CSV} ({len(rows)} rows)", flush=True)
    print(f"sidecar → {SIDECAR_CSV}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
