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

## AWS App Runner

App Runner is the right fit here: this app is a single small stateless
container with no other infrastructure to wire up, and App Runner gives
you a public HTTPS URL with essentially no setup — no VPC, load
balancer, or cluster to configure, and it scales to zero when idle. If
you outgrow that later (custom networking, sidecars, more control over
scaling), ECS Fargate is the natural next step, but it's real setup
overhead this project doesn't need yet.

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

`LINEAR_TEAM`, `SLACK_CHANNEL`, and `ARCADE_USER_ID` aren't secrets (they're
identifiers, not credentials) — those can be plain App Runner environment
variables.

### 3. Create the two IAM roles App Runner needs

App Runner uses **two separate roles**, not one:
- an **access role**, used by the App Runner build/deploy machinery to
  pull the image from your private ECR repo
- an **instance role**, used by the *running container itself* to reach
  other AWS services at runtime — required here because
  `RuntimeEnvironmentSecrets` reads `ARCADE_API_KEY` from Secrets Manager

```bash
# Access role: lets App Runner pull the image from ECR
aws iam create-role --role-name AppRunnerECRAccessRole \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"build.apprunner.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name AppRunnerECRAccessRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess

# Instance role: lets the running container read the secret at startup
aws iam create-role --role-name AppRunnerInstanceRole \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"tasks.apprunner.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam put-role-policy --role-name AppRunnerInstanceRole \
  --policy-name AppRunnerSecretsAccess \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"secretsmanager:GetSecretValue","Resource":"arn:aws:secretsmanager:<region>:<account-id>:secret:support-automation/arcade-api-key-XXXXXX"}]}'
```

Note the ARNs each prints (or fetch them with `aws iam get-role
--role-name <name> --query Role.Arn --output text`) — both are needed
below. The `Resource` in the instance role's policy must match the exact
secret ARN from step 2 (including its random suffix, e.g. `-XXXXXX`),
which `aws secretsmanager create-secret` printed when you ran it.

### 4. Create the App Runner service

Console: **App Runner → Create service → Container registry → Amazon
ECR**, pick the image just pushed, port `8000`. Under **Environment
variables**, add `LINEAR_TEAM`, `SLACK_CHANNEL`, `ARCADE_USER_ID` as
plain values; under **Environment secrets**, point `ARCADE_API_KEY` at
the Secrets Manager secret from step 2; under permissions, pick the two
roles from step 3.

Or via CLI:

```bash
aws apprunner create-service \
  --service-name support-automation \
  --source-configuration '{
    "ImageRepository": {
      "ImageIdentifier": "<account-id>.dkr.ecr.<your-region>.amazonaws.com/support-automation:latest",
      "ImageRepositoryType": "ECR",
      "ImageConfiguration": {
        "Port": "8000",
        "RuntimeEnvironmentVariables": {
          "LINEAR_TEAM": "<your Linear team key>",
          "SLACK_CHANNEL": "<your Slack channel>",
          "ARCADE_USER_ID": "<your identity, e.g. your email>"
        },
        "RuntimeEnvironmentSecrets": {
          "ARCADE_API_KEY": "arn:aws:secretsmanager:<region>:<account-id>:secret:support-automation/arcade-api-key-XXXXXX"
        }
      }
    },
    "AuthenticationConfiguration": {
      "AccessRoleArn": "arn:aws:iam::<account-id>:role/AppRunnerECRAccessRole"
    },
    "AutoDeploymentsEnabled": false
  }' \
  --instance-configuration '{
    "InstanceRoleArn": "arn:aws:iam::<account-id>:role/AppRunnerInstanceRole"
  }'
```

App Runner gives you back a public `*.awsapprunner.com` URL once the
service is running — that's the link to send out. Without `ARCADE_*`
configured at all, the portal still works fully; classification just
reports `create_linear_issue`/`notify_support_channel` as `skipped`
rather than raising (and if the key turns out to be wrong once you do
set it, those actions report `failed` with the real error, not a 500 —
the classify endpoint itself can't be taken down by a bad Arcade key).

### Updating after a code change

```bash
docker build -t support-automation .
docker tag support-automation:latest <account-id>.dkr.ecr.<your-region>.amazonaws.com/support-automation:latest
docker push <account-id>.dkr.ecr.<your-region>.amazonaws.com/support-automation:latest
aws apprunner start-deployment --service-arn <the service's ARN>
```

(Or set `AutoDeploymentsEnabled: true` above to redeploy automatically on
every image push, at the cost of no manual gate before a new image goes
live publicly.)
