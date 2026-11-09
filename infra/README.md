# Deployment

The public demo runs in two places:
- **Vercel** hosts the web app.
- **AWS ECS Fargate** hosts the agent API, behind an HTTPS load balancer on `api.<your-domain>`.

The demo has its own Supabase project, so visitors never touch the development data.

```
browser ──> Vercel (Next.js, password gate) ──HTTPS + X-Agent-Secret──> ALB ──> Fargate task (agent API + MCP server)
                                                                                     ├─> Claude, Voyage
                                                                                     └─> Supabase (demo project)
```

The Terraform is split by cost:

| Stack | What | Cost | Lifetime |
|---|---|---|---|
| [`base/`](base/) | ECR repository, the API's keys (one Secrets Manager secret), the GitHub OIDC deploy role | about $0.40/month | stays up |
| [`app/`](app/) | VPC (public subnets, no NAT gateway), ALB, ACM certificate, Route 53 record, ECS cluster and service | about $35/month while up | `apply` for a demo, `destroy` afterwards |

Most of the app cost is the load balancer and its public IPs. The task itself is 0.25 vCPU and 0.5 GB. Claude spend comes on top, capped at `DAILY_SPEND_CAP_USD` ($5/day by default).

App Runner was the first choice, but it stopped accepting new customers on 30 April 2026. It also ends every request, streams included, at 120 seconds.

## Needs

- Terraform 1.10 or later
- The AWS CLI, signed in to the account (`aws configure` or SSO)
- A Route 53 public hosted zone for your domain in that account
- A second Supabase project for the demo, in us-east-1 (the same region as the AWS stacks). In its SQL Editor, run every file in `supabase/migrations/` and then `supabase/seed.sql`, in the order the main README lists.
- The knowledge base ingested into it: run `python -m ingestion.ingest` with the demo project's `SUPABASE_URL` and key set in your shell.

## First time

```bash
# 1. The long-lived part. If the account already has GitHub's OIDC provider, add -var create_github_oidc_provider=false.
cd infra/base
terraform init && terraform apply

# 2. Put the keys in the secret. Use the demo Supabase project's URL and service-role key, and a new long
#    random AGENT_API_SECRET; Vercel gets the same one. Edit api-secret.json, run this, then delete the file.
cat > api-secret.json <<'EOF'
{"ANTHROPIC_API_KEY": "...", "VOYAGE_API_KEY": "...", "SUPABASE_URL": "https://<demo-ref>.supabase.co",
 "SUPABASE_SERVICE_ROLE_KEY": "...", "AGENT_API_SECRET": "..."}
EOF
aws secretsmanager put-secret-value --secret-id support-agent/api --secret-string file://api-secret.json
rm api-secret.json
```

3. In GitHub, go to **Settings → Secrets and variables → Actions**:
   - Under **Variables**, add `AWS_DEPLOY_ROLE_ARN` (the `github_deploy_role_arn` output) and `AWS_REGION` (`us-east-1`).
   - Under **Secrets**, add `DEMO_SUPABASE_URL` and `DEMO_SUPABASE_SERVICE_ROLE_KEY`, for the nightly reset.
4. Push the first image: **Actions → Deploy API → Run workflow**. With `infra/app` not up yet, it only pushes the image.

## Bring the demo up

```bash
cd infra/app
cp terraform.tfvars.example terraform.tfvars   # once: set domain_name
terraform init
terraform apply                                 # about 5 minutes, mostly the certificate check and the first task
curl https://api.<your-domain>/health           # {"status":"ok"}
```

In Vercel, import the repository with **Root Directory** `web` and set these environment variables (once; they survive the AWS side going up and down):
- `AGENT_API_URL`: the `api_url` output
- `AGENT_API_SECRET`: the value in the AWS secret
- `DEMO_PASSWORD`: the password you'll give people

While the app stack is up, every push to `main` that changes the API redeploys it, through `.github/workflows/deploy.yml`.

## Take it down

```bash
cd infra/app && terraform destroy
```

The image, the keys and the deploy role stay in `base`. Vercel keeps serving the web app; until the next `apply`, it shows that it can't reach the agent API.

## Operating it

- **Logs:** `aws logs tail /ecs/support-agent-api --follow`
- **Spend:** the `daily_spend` table in the demo Supabase project shows today's Claude spend. Once it reaches the cap, new messages are refused until 00:00 UTC.
- **Nightly reset:** `.github/workflows/reset-demo.yml` runs `reset_demo_data()` on the demo project at 04:00 UTC. You can also run it by hand from the Actions tab.
- **Run one task only.** Conversation locks, rate limits and resume scheduling live in the process's memory. That's why `desired_count` is limited to 0 or 1, and a deploy stops the old task before starting the new one, which means about a minute and a half of downtime per deploy.
- **State:** each stack's Terraform state is a local file in its folder (git-ignored). Keep it, or `destroy` won't know what to remove. For a team you'd move it to an S3 backend.
