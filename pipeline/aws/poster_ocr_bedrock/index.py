import base64
import json

import boto3

RUNTIME = boto3.client("bedrock-runtime")
S3 = boto3.client("s3")
DEFAULT_MODEL = "us.amazon.nova-2-lite-v1:0"

OCR_PROMPT = (
    "Extract ALL visible text from this movie poster. "
    "Return plain text only, no commentary."
)

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


def _load_image(event: dict) -> tuple[bytes, str]:
    if event.get("image_b64"):
        raw = base64.b64decode(event["image_b64"])
        fmt = event.get("image_format") or "jpeg"
        return raw, fmt

    bucket = event.get("s3_bucket")
    key = event.get("s3_key")
    if bucket and key:
        obj = S3.get_object(Bucket=bucket, Key=key)
        raw = obj["Body"].read()
        fmt = event.get("image_format")
        if not fmt:
            kl = key.lower()
            if kl.endswith(".png"):
                fmt = "png"
            elif kl.endswith(".webp"):
                fmt = "webp"
            elif kl.endswith(".gif"):
                fmt = "gif"
            else:
                fmt = "jpeg"
        return raw, fmt

    raise ValueError("image_b64 or s3_bucket+s3_key required")


def handler(event, context):
    if isinstance(event, str):
        event = json.loads(event)
    model_id = event.get("model_id") or DEFAULT_MODEL
    mode = (event.get("mode") or "ocr").lower()
    max_tokens = int(event.get("max_tokens") or 2048)

    try:
        raw, fmt = _load_image(event)
    except Exception as e:
        return {"statusCode": 400, "error": str(e)}

    if mode == "enrich":
        prompt = event.get("prompt") or ENRICH_PROMPT
    else:
        prompt = event.get("prompt") or OCR_PROMPT

    resp = RUNTIME.converse(
        modelId=model_id,
        messages=[
            {
                "role": "user",
                "content": [
                    {"image": {"format": fmt, "source": {"bytes": raw}}},
                    {"text": prompt},
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
        "mode": mode,
        "text": text,
        "usage": resp.get("usage") or {},
    }
