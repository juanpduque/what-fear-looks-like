#!/usr/bin/env python3
"""Segunda pasada sobre los mismatches de verify_celebrities_vs_cast.py usando
Claude (Bedrock) para juzgar plausibilidad, no solo comparar strings.

verify_celebrities_vs_cast.py encontro 16,567/20,181 "unmatched_celebs" — mezcla
de errores reales y obvios (Rekognition reconoce a alguien que murio antes de que
existiera la fotografia: Avogadro 1856, Tipu Sultan 1799) y casos ambiguos (actor
real del cast pero el nombre no calzo por formato). Un filtro de reglas no
distingue eso; Claude si, porque puede razonar sobre quien es la persona, cuando
vivio, y si es plausible que aparezca en un poster de esa pelicula/epoca.

Batchea varias peliculas por llamada (reduce costo/overhead), pide JSON.

  export AWS_PROFILE=sandbox
  python3 verify_celebrities_claude.py --workers 8 --batch-size 20
"""

from __future__ import annotations

import argparse
import csv
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
import pandas as pd
from botocore.config import Config

DATA = Path(__file__).parent / "data"
IN_CSV = DATA / "qa" / "celebrity_cast_verification.csv"
META_CSV = DATA / "posters.csv"
OUT = DATA / "qa" / "celebrity_cast_verification_claude.csv"
FIELDS = ["id", "title", "year", "name", "verdict", "reason"]
MODEL_ID = "us.amazon.nova-pro-v1:0"
REGION = "us-east-1"

_write_lock = threading.Lock()

PROMPT_HEADER = """Sos un verificador de datos para un ensayo sobre posters de cine de terror.
Un sistema de reconocimiento facial (AWS Rekognition RecognizeCelebrities) encontro
supuestas celebridades en cada poster que NO aparecen en el cast/crew real de TMDB
de esa pelicula. Tu trabajo es juzgar, para cada nombre, si es:

- "clearly_wrong": Rekognition claramente se equivoco. Ejemplos: la persona murio
  antes de que existiera la fotografia o antes del cine; es una figura historica,
  cientifico, politico, etc. sin relacion posible con cine de terror de esa epoca;
  el nombre no tiene sentido con el anio/genero de la pelicula.
- "plausible": es un actor/actriz o persona de la industria real que SI podria
  aparecer en ese poster (extra, doble, actor no acreditado, o el nombre no matcheo
  por formato/alias) aunque no este en la lista de cast que TMDB tiene registrada.
- "uncertain": no tenes suficiente info para decidir con confianza.

Peliculas a evaluar:
{items}

Respondes SOLO con JSON valido, sin texto adicional, con esta forma exacta:
{{"results": [{{"id": <id numero>, "name": "<nombre exacto>", "verdict": "clearly_wrong"|"plausible"|"uncertain", "reason": "<una frase corta>"}}, ...]}}
Incluir una entrada por cada nombre listado arriba (puede haber varios nombres por pelicula)."""


def load_targets(in_csv: Path, meta_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(in_csv)
    df["unmatched_celebs"] = df["unmatched_celebs"].apply(
        lambda s: json.loads(s) if isinstance(s, str) and s.strip() else []
    )
    df = df[df["unmatched_celebs"].apply(len) > 0]
    meta = pd.read_csv(meta_csv, usecols=["id", "title", "year"])
    df = df.merge(meta, on="id", how="left")
    return df[["id", "title", "year", "unmatched_celebs"]]


def load_done() -> set[tuple[int, str]]:
    if not OUT.exists():
        return set()
    d = pd.read_csv(OUT)
    return set(zip(d["id"].astype(int), d["name"].astype(str)))


def append_rows(rows: list[dict]) -> None:
    if not rows:
        return
    new_file = not OUT.exists()
    with _write_lock:
        with OUT.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new_file:
                w.writeheader()
            for r in rows:
                w.writerow(r)


def build_prompt(batch: list[dict]) -> str:
    lines = []
    for row in batch:
        title = row["title"] if pd.notna(row["title"]) else "?"
        year = int(row["year"]) if pd.notna(row["year"]) else "?"
        names = ", ".join(f'"{n}"' for n in row["unmatched_celebs"])
        lines.append(f'- id={row["id"]} "{title}" ({year}): {names}')
    return PROMPT_HEADER.format(items="\n".join(lines))


def call_claude(client, batch: list[dict]) -> list[dict]:
    prompt = build_prompt(batch)
    resp = client.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"temperature": 0, "maxTokens": 8000},
    )
    text = "".join(
        b.get("text", "")
        for b in resp.get("output", {}).get("message", {}).get("content", [])
        if "text" in b
    )
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    obj = json.loads(text)
    results = obj.get("results") or []
    id_to_meta = {int(r["id"]): (r["title"], r["year"]) for r in batch}
    out = []
    for r in results:
        pid = int(r.get("id", -1))
        title, year = id_to_meta.get(pid, ("", ""))
        out.append(
            {
                "id": pid,
                "title": title,
                "year": year,
                "name": r.get("name", ""),
                "verdict": r.get("verdict", ""),
                "reason": r.get("reason", ""),
            }
        )
    return out


def process_batch(client, batch: list[dict]) -> tuple[list[dict], str]:
    # Bedrock marketplace-subscription access has been intermittent on this sandbox
    # account (worked once, then AccessDeniedException on every model) — the error
    # text itself says "try again after 2 minutes", so retry with backoff instead
    # of giving up on the first failure.
    last_err = ""
    for attempt in range(6):
        try:
            return call_claude(client, batch), ""
        except Exception as e:
            last_err = str(e)
            if "AccessDeniedException" in last_err and "Marketplace" in last_err:
                time.sleep(min(20 * (attempt + 1), 120))
                continue
            return [], last_err
    return [], last_err


def main():
    global MODEL_ID, OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=20)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--region", default=REGION)
    ap.add_argument("--model-id", default=MODEL_ID)
    ap.add_argument(
        "--in-csv",
        default="",
        help="override celebrity_cast_verification.csv (e.g. celebrity_cast_verification_thriller.csv)",
    )
    ap.add_argument("--meta-csv", default="", help="override posters.csv (id,title,year source)")
    ap.add_argument("--out", default="", help="override output csv (keeps corpora separate)")
    args = ap.parse_args()

    MODEL_ID = args.model_id
    if args.out:
        OUT = Path(args.out)
    in_csv = Path(args.in_csv) if args.in_csv else IN_CSV
    meta_csv = Path(args.meta_csv) if args.meta_csv else META_CSV

    targets = load_targets(in_csv, meta_csv)
    done = load_done()
    # skip a movie only if ALL its unmatched names are already done
    rows = []
    for r in targets.itertuples():
        pending = [n for n in r.unmatched_celebs if (int(r.id), n) not in done]
        if pending:
            rows.append({"id": r.id, "title": r.title, "year": r.year, "unmatched_celebs": pending})
    if args.limit:
        rows = rows[: args.limit]
    print(f"peliculas con mismatches pendientes: {len(rows):,}", flush=True)

    batches = [rows[i : i + args.batch_size] for i in range(0, len(rows), args.batch_size)]
    print(f"batches={len(batches):,} batch_size={args.batch_size} model={MODEL_ID}", flush=True)

    session = boto3.Session(profile_name="sandbox")
    cfg = Config(retries={"max_attempts": 5, "mode": "adaptive"})
    client = session.client("bedrock-runtime", region_name=args.region, config=cfg)

    t0 = time.time()
    n_done = n_err = n_names = 0
    verdict_counts: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(process_batch, client, b): b for b in batches}
        for i, fut in enumerate(as_completed(futs), 1):
            results, err = fut.result()
            if err:
                n_err += 1
                if n_err <= 5:
                    print(f"  ERR: {err}", flush=True)
                # aviso temprano: si ya fallan >30% de los batches a esta altura,
                # es mas probable un problema sistemico (permisos, throttling) que
                # ruido normal — no tiene sentido dejar correr 800 batches mas para
                # enterarse recien al final
                if i >= 20 and n_err / i > 0.3:
                    print(
                        f"  ⚠ AVISO: {n_err}/{i} batches fallando ({100 * n_err / i:.0f}%) — "
                        f"revisar antes de dejar correr el resto",
                        flush=True,
                    )
                continue
            append_rows(results)
            n_done += 1
            n_names += len(results)
            for r in results:
                verdict_counts[r["verdict"]] = verdict_counts.get(r["verdict"], 0) + 1
            if i % 20 == 0:
                rate = n_names / max(time.time() - t0, 1e-9)
                vdist = " ".join(f"{k}={v}" for k, v in sorted(verdict_counts.items()))
                print(
                    f"  batches {i:,}/{len(batches):,} names={n_names:,} err={n_err} {rate:.1f} names/s | {vdist}",
                    flush=True,
                )

    vdist = " ".join(f"{k}={v}" for k, v in sorted(verdict_counts.items()))
    print(
        f"LISTO batches_ok={n_done:,} batches_err={n_err:,} names_written={n_names:,} | {vdist} -> {OUT}"
    )


if __name__ == "__main__":
    main()
