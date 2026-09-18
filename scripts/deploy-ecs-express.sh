#!/usr/bin/env bash
# Builds, pushes, and deploys the web portal to AWS via Amazon ECS
# Express Mode. See ../DEPLOY.md for the manual step-by-step version this
# script automates -- read that first if anything here needs explaining.
#
# Idempotent for ECR/IAM/Secrets Manager (safe to re-run). The final
# `create-express-gateway-service` call is NOT idempotent -- if the
# service already exists, re-running this script will fail there with a
# clear error telling you to use `aws ecs update-express-gateway-service`
# instead (see DEPLOY.md's "Updating after a code change" section).
#
# Required environment variables (set before running, never hardcoded
# here): LINEAR_TEAM, SLACK_CHANNEL, ARCADE_USER_ID, ARCADE_API_KEY.
# ARCADE_API_KEY is only ever passed to `aws secretsmanager`, never
# echoed or logged by this script.

set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-support-automation}"
ECR_REPO="${ECR_REPO:-support-automation}"
SECRET_NAME="${SECRET_NAME:-support-automation/arcade-api-key}"
REGION="${AWS_REGION:-$(aws configure get region)}"
CONTAINER_PORT="${CONTAINER_PORT:-8000}"

for var in LINEAR_TEAM SLACK_CHANNEL ARCADE_USER_ID ARCADE_API_KEY; do
  if [ -z "${!var:-}" ]; then
    echo "error: \$$var is not set. Export it before running this script." >&2
    exit 1
  fi
done

if [ -z "$REGION" ]; then
  echo "error: no AWS region set. Export AWS_REGION or run 'aws configure'." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}"

echo "== Account: $ACCOUNT_ID  Region: $REGION =="

echo "== 1. ECR repository =="
aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$REGION" > /dev/null 2>&1 \
  || aws ecr create-repository --repository-name "$ECR_REPO" --region "$REGION" > /dev/null
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

echo "== 2. Build and push image =="
docker build -t "$ECR_REPO" "$REPO_ROOT"
docker tag "$ECR_REPO:latest" "$ECR_URI:latest"
docker push "$ECR_URI:latest"

echo "== 3. Secrets Manager: $SECRET_NAME =="
SECRET_ARN="$(aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region "$REGION" \
  --query ARN --output text 2>/dev/null || true)"
if [ -z "$SECRET_ARN" ]; then
  SECRET_ARN="$(aws secretsmanager create-secret --name "$SECRET_NAME" \
    --secret-string "$ARCADE_API_KEY" --region "$REGION" --query ARN --output text)"
else
  aws secretsmanager put-secret-value --secret-id "$SECRET_NAME" \
    --secret-string "$ARCADE_API_KEY" --region "$REGION" > /dev/null
fi
echo "secret ARN: $SECRET_ARN"

echo "== 4. IAM roles =="
aws iam get-role --role-name ecsTaskExecutionRole > /dev/null 2>&1 || \
  aws iam create-role --role-name ecsTaskExecutionRole \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}' > /dev/null

aws iam get-role --role-name ecsInfrastructureRoleForExpressServices > /dev/null 2>&1 || \
  aws iam create-role --role-name ecsInfrastructureRoleForExpressServices \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Sid":"AllowAccessInfrastructureForECSExpressServices","Effect":"Allow","Principal":{"Service":"ecs.amazonaws.com"},"Action":"sts:AssumeRole"}]}' > /dev/null

aws iam attach-role-policy --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
aws iam attach-role-policy --role-name ecsInfrastructureRoleForExpressServices \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices

aws iam put-role-policy --role-name ecsTaskExecutionRole \
  --policy-name SupportAutomationSecretsAccess \
  --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"secretsmanager:GetSecretValue\",\"Resource\":\"$SECRET_ARN\"}]}"

EXECUTION_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/ecsTaskExecutionRole"
INFRA_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/ecsInfrastructureRoleForExpressServices"

echo "waiting for IAM role propagation..."
sleep 15

echo "== 5. Create the Express Mode service =="
PRIMARY_CONTAINER=$(cat <<JSON
{
  "image": "$ECR_URI:latest",
  "containerPort": $CONTAINER_PORT,
  "environment": [
    {"name": "LINEAR_TEAM", "value": "$LINEAR_TEAM"},
    {"name": "SLACK_CHANNEL", "value": "$SLACK_CHANNEL"},
    {"name": "ARCADE_USER_ID", "value": "$ARCADE_USER_ID"}
  ],
  "secrets": [
    {"name": "ARCADE_API_KEY", "valueFrom": "$SECRET_ARN"}
  ]
}
JSON
)

aws ecs create-express-gateway-service \
  --service-name "$SERVICE_NAME" \
  --execution-role-arn "$EXECUTION_ROLE_ARN" \
  --infrastructure-role-arn "$INFRA_ROLE_ARN" \
  --primary-container "$PRIMARY_CONTAINER" \
  --health-check-path "/" \
  --region "$REGION" \
  --monitor-resources
