#!/usr/bin/env bash
# Trigger an in-place deploy on the EC2 box via SSM Run Command.
# Usage (local or CI):
#   AWS_REGION=ap-south-1 EC2_INSTANCE_ID=i-... bash backend/deploy/ssm-deploy.sh
set -euo pipefail

REGION="${AWS_REGION:-ap-south-1}"
INSTANCE_ID="${EC2_INSTANCE_ID:?EC2_INSTANCE_ID is required}"
REPO_DIR="${EC2_REPO_DIR:-/home/ubuntu/Resume_generator}"
BRANCH="${DEPLOY_BRANCH:-main}"
PARAM_NAME="${RESUME_ENV_SSM_PARAM:-/resume-generator/prod/env}"

echo "==> SSM deploy to ${INSTANCE_ID} (${REGION}) branch=${BRANCH}"

COMMAND_ID="$(aws ssm send-command \
  --region "$REGION" \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --comment "resume-api deploy ${BRANCH}" \
  --timeout-seconds 600 \
  --parameters "commands=[
\"set -euo pipefail\",
\"export AWS_REGION=${REGION}\",
\"export RESUME_ENV_SSM_PARAM=${PARAM_NAME}\",
\"cd ${REPO_DIR}\",
\"git fetch origin\",
\"git checkout ${BRANCH}\",
\"git pull --ff-only origin ${BRANCH}\",
\"bash backend/deploy/ensure-env-from-ssm.sh\",
\"bash backend/deploy/update-ec2.sh\"
]" \
  --query 'Command.CommandId' \
  --output text)"

echo "==> CommandId: ${COMMAND_ID}"
echo "==> Waiting for success..."

aws ssm wait command-executed \
  --region "$REGION" \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" || true

STATUS="$(aws ssm get-command-invocation \
  --region "$REGION" \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --query 'Status' \
  --output text)"

echo "==> Status: ${STATUS}"
aws ssm get-command-invocation \
  --region "$REGION" \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --query '{Status:Status,Stdout:StandardOutputContent,Stderr:StandardErrorContent}' \
  --output json

if [[ "$STATUS" != "Success" ]]; then
  echo "Deploy failed" >&2
  exit 1
fi
