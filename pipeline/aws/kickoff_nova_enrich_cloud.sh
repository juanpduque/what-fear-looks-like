#!/usr/bin/env bash
# Kick off cloud orchestrator (self-chains). Optional: fan-out async batches.
#   bash pipeline/aws/kickoff_nova_enrich_cloud.sh
#   bash pipeline/aws/kickoff_nova_enrich_cloud.sh --fanout
#   bash pipeline/aws/kickoff_nova_enrich_cloud.sh --smoke
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-sandbox}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-west-2}"
export AWS_EC2_METADATA_DISABLED=true

BUCKET="${NOVA_ENRICH_S3_BUCKET:-sagemaker-studio-a5572760}"
PREFIX="${NOVA_ENRICH_S3_PREFIX:-wflike-nova-enrich/cloud}"
MODE="${1:-}"

invoke_lambda() {
  local fn="$1" payload_file="$2" out_file="$3" inv_type="${4:-RequestResponse}"
  aws lambda invoke \
    --function-name "$fn" \
    --invocation-type "$inv_type" \
    --payload "fileb://${payload_file}" \
    "$out_file" >/dev/null
}

if [[ "$MODE" == "--smoke" ]]; then
  echo "=== smoke: 3 ids sync ==="
  aws s3 cp "s3://${BUCKET}/${PREFIX}/todo_ids.json" /tmp/nova_todo_ids.json --only-show-errors
  python3 - <<'PY'
import json
todo = json.load(open("/tmp/nova_todo_ids.json"))[:3]
payload = {"ids": [int(x) for x in todo], "no_chain": True}
open("/tmp/nova_orch_smoke_payload.json", "w").write(json.dumps(payload))
print("ids", todo)
PY
  invoke_lambda nova-enrich-orchestrator /tmp/nova_orch_smoke_payload.json /tmp/nova_orch_smoke.json RequestResponse
  cat /tmp/nova_orch_smoke.json
  echo
  exit 0
fi

if [[ "$MODE" == "--fanout" ]]; then
  echo "=== fan-out async batches ==="
  python3 - <<PY
import json, subprocess
bucket = "${BUCKET}"
prefix = "${PREFIX}"
subprocess.check_call(
    ["aws", "s3", "cp", f"s3://{bucket}/{prefix}/todo_ids.json", "/tmp/nova_todo_ids.json"]
)
todo = json.load(open("/tmp/nova_todo_ids.json"))
batch = 10
n = 0
for i in range(0, len(todo), batch):
    chunk = todo[i : i + batch]
    payload = {"ids": chunk, "no_chain": True, "cursor": i}
    pf = f"/tmp/nova_fanout_{n}.json"
    open(pf, "w").write(json.dumps(payload))
    subprocess.check_call(
        [
            "aws", "lambda", "invoke",
            "--function-name", "nova-enrich-orchestrator",
            "--invocation-type", "Event",
            "--payload", f"fileb://{pf}",
            "/tmp/nova_orch_fanout_out.json",
        ],
        stdout=subprocess.DEVNULL,
    )
    n += 1
    if n % 50 == 0:
        print(f"  queued {n} batches ({min(i+batch,len(todo))}/{len(todo)})", flush=True)
print(f"fanout done batches={n} ids={len(todo)}")
PY
  exit 0
fi

echo "=== kickoff self-chain from cursor=0 ==="
printf '%s' '{"cursor":0,"chain":true}' > /tmp/nova_orch_kickoff_payload.json
invoke_lambda nova-enrich-orchestrator /tmp/nova_orch_kickoff_payload.json /tmp/nova_orch_kickoff.json Event
echo "queued Event invoke"
cat /tmp/nova_orch_kickoff.json 2>/dev/null || true
echo
echo "progress: s3://${BUCKET}/${PREFIX}/progress_cloud.json"
