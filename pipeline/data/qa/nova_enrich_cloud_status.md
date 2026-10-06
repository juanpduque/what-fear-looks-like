# Nova enrich cloud status

**When (UTC):** 2026-08-04T15:28:58Z  
**Result:** STOPPED — AWS STS gate failed

## STS

```text
aws sts get-caller-identity
→ An error occurred (InvalidClientTokenId) when calling the GetCallerIdentity operation: The security token included in the request is invalid.
```

| Field | Value |
|--------|--------|
| Account | _(unavailable)_ |
| Arn / UserId | _(unavailable)_ |
| Creds injected | yes (`AWS_ACCESS_KEY_ID` ASIA…, session token present) |
| Region env | `AWS_DEFAULT_REGION` set (us-east-*) |

## Pipeline (not run)

Per gate: only proceed after STS OK. Skipped:

1. Latest main + Nova AWS scripts — N/A (already on `main` with scripts; no further sync)
2. `stage_nova_enrich_posters.sh` — not run → **n_todo** unknown
3. `deploy_nova_enrich_cloud.sh` / `kickoff_nova_enrich_cloud.sh` — not run → **kickoff** not OK
4. OWL — not touched

## Stop reason

**InvalidClientTokenId** — security token in the request is invalid. User reported secrets updated again; injected cloud-agent AWS credentials still rejected by STS. Re-inject valid keys/session and retry.
