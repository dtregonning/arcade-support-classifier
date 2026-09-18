# Deploying the web portal

This covers the web portal only (`support_automation.webapp.app`) — a
stateless FastAPI app with no database. The MCP server is a separate
concern, deployed to Arcade Cloud via `arcade deploy` (see README's
Arcade section); it doesn't need any of this.

## Image

```bash
docker build -t support-automation .
docker run --rm -p 8000:8000 support-automation
```

Then open http://127.0.0.1:8000 — same portal, same `/api/samples` and
`/api/tickets/classify` endpoints as running it locally with `uv run
support-portal`. The image never bakes in `.env` or any secret (`.env`
is excluded via `.dockerignore`); all `ARCADE_*` configuration comes from
environment variables at run time, same as any other 12-factor app.

## AWS (Amazon ECS Express Mode)

**Fast path:** `scripts/deploy-ecs-express.sh` runs every step below —
ECR repo, image build/push, the secret, both IAM roles, and the service
itself. It's idempotent except for the final service creation (safe to
re-run up to that point; re-running after the service already exists
will tell you to use `update-express-gateway-service` instead, per
"Updating after a code change" below). Set four environment variables
first, then run it:

```bash
export LINEAR_TEAM=<your Linear team key>
export SLACK_CHANNEL=<your Slack channel>
export ARCADE_USER_ID=<your identity, e.g. your email>
export ARCADE_API_KEY=<your Arcade API key>
./scripts/deploy-ecs-express.sh
```

The manual steps below are what it's actually doing — read them if the
script fails partway through and you need to pick up from a specific
step, or if you want to understand what each piece is for before running
it.

**Not AWS App Runner** — App Runner stopped accepting new customers as
of April 30, 2026 (existing services keep running, but you can't create
new ones). AWS's own replacement recommendation for "single container,
give me a public HTTPS URL, no manual VPC/ALB/cluster setup" is **Amazon
ECS Express Mode**, which is what this section uses. If you outgrow it
later (custom networking, sidecars, finer control), plain ECS Fargate
with a hand-built task definition is the next step — Express Mode
services are regular ECS resources under the hood, fully visible and
editable in the console/API, so nothing here is a dead end.

### 1. Push the image to ECR

```bash
aws ecr create-repository --repository-name support-automation
aws ecr get-login-password --region <your-region> | \
  docker login --username AWS --password-stdin <account-id>.dkr.ecr.<your-region>.amazonaws.com

docker build -t support-automation .
docker tag support-automation:latest \
  <account-id>.dkr.ecr.<your-region>.amazonaws.com/support-automation:latest
docker push <account-id>.dkr.ecr.<your-region>.amazonaws.com/support-automation:latest
```

### 2. Store the Arcade key as a secret, not a plain env var

```bash
aws secretsmanager create-secret \
  --name support-automation/arcade-api-key \
  --secret-string "<your ARCADE_API_KEY>"
```

Note the full ARN it prints (it ends in a random suffix, e.g.
`-XXXXXX`) — you need the exact ARN again below. `LINEAR_TEAM`,
`SLACK_CHANNEL`, and `ARCADE_USER_ID` aren't secrets (they're
identifiers, not credentials) — those go in as plain environment
variables.

### 3. Create the two IAM roles Express Mode needs

```bash
aws iam create-role --role-name ecsTaskExecutionRole \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam create-role --role-name ecsInfrastructureRoleForExpressServices \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Sid":"AllowAccessInfrastructureForECSExpressServices","Effect":"Allow","Principal":{"Service":"ecs.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

aws iam attach-role-policy --role-name ecsTaskExecutionRole \
    --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
aws iam attach-role-policy --role-name ecsInfrastructureRoleForExpressServices \
    --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices
```

The **execution role** (not a separate instance role — Express Mode
works differently from App Runner here) is what resolves secrets at
container startup, so it also needs read access to the specific secret
from step 2:

```bash
aws iam put-role-policy --role-name ecsTaskExecutionRole \
  --policy-name SupportAutomationSecretsAccess \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"secretsmanager:GetSecretValue","Resource":"arn:aws:secretsmanager:<region>:<account-id>:secret:support-automation/arcade-api-key-XXXXXX"}]}'
```

IAM roles are eventually consistent — if the next step fails with an
assume-role error, wait ~30-60s and retry.

### 4. Create the Express Mode service

```bash
aws ecs create-express-gateway-service \
    --service-name support-automation \
    --execution-role-arn arn:aws:iam::<account-id>:role/ecsTaskExecutionRole \
    --infrastructure-role-arn arn:aws:iam::<account-id>:role/ecsInfrastructureRoleForExpressServices \
    --primary-container '{
      "image": "<account-id>.dkr.ecr.<your-region>.amazonaws.com/support-automation:latest",
      "containerPort": 8000,
      "environment": [
        {"name": "LINEAR_TEAM", "value": "<your Linear team key>"},
        {"name": "SLACK_CHANNEL", "value": "<your Slack channel>"},
        {"name": "ARCADE_USER_ID", "value": "<your identity, e.g. your email>"}
      ],
      "secrets": [
        {"name": "ARCADE_API_KEY", "valueFrom": "arn:aws:secretsmanager:<region>:<account-id>:secret:support-automation/arcade-api-key-XXXXXX"}
      ]
    }' \
    --health-check-path "/" \
    --region <your-region> \
    --monitor-resources
```

`--monitor-resources` streams status until the service goes `ACTIVE` and
prints the final details, including the public URL, which looks like:

```
https://<service-name>.ecs.<region>.on.aws/
```

That's the link to send out. Without `ARCADE_*` configured at all, the
portal still works fully; classification just reports
`create_linear_issue`/`notify_support_channel` as `skipped` rather than
raising (and if the key turns out to be wrong once you do set it, those
actions report `failed` with the real error, not a 500 — the classify
endpoint itself can't be taken down by a bad Arcade key).

### Checking status or re-fetching the URL later

```bash
aws ecs describe-express-gateway-service --service-arn <arn from step 4's output> --region <your-region>
aws ecs monitor-express-gateway-service --service-arn <arn from step 4's output> --region <your-region>
```

### Updating after a code change

```bash
docker build -t support-automation .
docker tag support-automation:latest <account-id>.dkr.ecr.<your-region>.amazonaws.com/support-automation:latest
docker push <account-id>.dkr.ecr.<your-region>.amazonaws.com/support-automation:latest

aws ecs update-express-gateway-service \
  --service-arn <arn from step 4's output> \
  --primary-container '{"image": "<account-id>.dkr.ecr.<your-region>.amazonaws.com/support-automation:latest"}' \
  --region <your-region> \
  --monitor-resources
```
