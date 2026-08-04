#!/usr/bin/env bash
# Deploy poster-ocr-bedrock (S3-aware) + nova-enrich-orchestrator.
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-sandbox}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-west-2}"
export AWS_EC2_METADATA_DISABLED=true
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy || true

BUCKET="${NOVA_ENRICH_S3_BUCKET:-strands-travelagents3sessionsbucket-sn8rc9ezuma6}"
PREFIX="${NOVA_ENRICH_S3_PREFIX:-wflike-nova-enrich/cloud}"
ROLE_ARN="${NOVA_LAMBDA_ROLE_ARN:-}"
PIPE="$(cd "$(dirname "$0")/.." && pwd)"
AWS_DIR="$PIPE/aws"

if [[ -z "$ROLE_ARN" ]]; then
  ROLE_ARN="$(aws lambda get-function-configuration \
    --function-name poster-ocr-bedrock \
    --query Role --output text 2>/dev/null || true)"
fi
if [[ -z "$ROLE_ARN" || "$ROLE_ARN" == "None" ]]; then
  ROLE_ARN="$(aws iam list-roles --query 'Roles[?contains(RoleName, `TravelAgentExecutionRole`)].Arn | [0]' --output text)"
fi
echo "role=$ROLE_ARN bucket=$BUCKET prefix=$PREFIX"

deploy_zip() {
  local name="$1" src_dir="$2" handler="$3" timeout="$4" memory="$5"
  local zip="/tmp/${name}.zip"
  (cd "$src_dir" && zip -q -r "$zip" index.py)
  if aws lambda get-function --function-name "$name" >/dev/null 2>&1; then
    echo "updating $name"
    aws lambda update-function-code --function-name "$name" --zip-file "fileb://$zip" >/dev/null
    aws lambda wait function-updated-v2 --function-name "$name" 2>/dev/null || sleep 3
    aws lambda update-function-configuration \
      --function-name "$name" \
      --timeout "$timeout" \
      --memory-size "$memory" \
      --handler "$handler" \
      >/dev/null || true
  else
    echo "creating $name"
    aws lambda create-function \
      --function-name "$name" \
      --runtime python3.12 \
      --role "$ROLE_ARN" \
      --handler "$handler" \
      --timeout "$timeout" \
      --memory-size "$memory" \
      --zip-file "fileb://$zip" \
      --description "WFL Nova enrich cloud" \
      >/dev/null
  fi
  aws lambda wait function-active-v2 --function-name "$name" 2>/dev/null || sleep 2
}

deploy_zip poster-ocr-bedrock "$AWS_DIR/poster_ocr_bedrock" index.handler 60 512
deploy_zip nova-enrich-orchestrator "$AWS_DIR/nova_enrich_orchestrator" index.handler 300 1024

echo "--- env orchestrator ---"
aws lambda update-function-configuration \
  --function-name nova-enrich-orchestrator \
  --timeout 300 \
  --memory-size 1024 \
  --environment "Variables={
    NOVA_ENRICH_BUCKET=${BUCKET},
    NOVA_ENRICH_PREFIX=${PREFIX},
    NOVA_ENRICH_FN=poster-ocr-bedrock,
    NOVA_ORCH_FN=nova-enrich-orchestrator,
    NOVA_MODEL_ID=us.amazon.nova-2-lite-v1:0,
    NOVA_BATCH_SIZE=10,
    NOVA_WORKERS=3,
    NOVA_MIN_INTERVAL=0.55
  }" >/dev/null
aws lambda wait function-updated-v2 --function-name nova-enrich-orchestrator 2>/dev/null || sleep 3

# Allow TravelAgent role to invoke enrich + self (resource policy)
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
for stmt in enrich-invoke self-invoke; do
  aws lambda remove-permission --function-name nova-enrich-orchestrator --statement-id "$stmt" 2>/dev/null || true
done
aws lambda add-permission \
  --function-name nova-enrich-orchestrator \
  --statement-id self-invoke \
  --action lambda:InvokeFunction \
  --principal "$ROLE_ARN" \
  >/dev/null || true

aws lambda remove-permission --function-name poster-ocr-bedrock --statement-id orch-invoke 2>/dev/null || true
aws lambda add-permission \
  --function-name poster-ocr-bedrock \
  --statement-id orch-invoke \
  --action lambda:InvokeFunction \
  --principal "$ROLE_ARN" \
  >/dev/null || true

echo "=== deploy OK ==="
aws lambda get-function-configuration --function-name poster-ocr-bedrock \
  --query '[FunctionName,LastUpdateStatus,Timeout]' --output text
aws lambda get-function-configuration --function-name nova-enrich-orchestrator \
  --query '[FunctionName,LastUpdateStatus,Timeout,Environment.Variables]' --output json
