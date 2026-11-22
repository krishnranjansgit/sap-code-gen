# Docker and Google Cloud Run

This is an external demonstration workflow, not a production multi-user platform.
The image runs as a non-root user and contains only the Streamlit runtime,
prompt snapshots and dependencies. It does not copy local credentials, SAP
system configurations, repositories, generated history or legacy connectors.
The pinned Atlassian MCP connector is installed at build time in its own
environment, so requests do not download packages. No API keys belong in the image.

## Local container

Start Docker Desktop, then run:

```sh
docker build -t sap-code-gen:demo .
docker run --rm -p 8503:8080 --name sap-code-gen-demo sap-code-gen:demo
```

Open <http://localhost:8503>. A health endpoint is available at
`/_stcore/health`. `PORT` defaults to 8080; `ARTIFACT_DIR` defaults to
`/tmp/sap-artifacts`. Optional mounted storage must be writable by UID 10001.
The app namespaces output by a random per-session workspace identifier.
Do not mount local credentials or legacy SAP configuration into the container.

## Cloud Run

Use a dedicated Google Cloud project with billing enabled. Authenticate with
`gcloud auth login`, then replace the example values below. These commands
create billable resources and are for the deployment operator to run.

```sh
export PROJECT_ID="your-project-id"
export REGION="us-central1"
gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com
gcloud artifacts repositories create sap-demo --repository-format=docker --location="$REGION"
gcloud builds submit --tag "$REGION-docker.pkg.dev/$PROJECT_ID/sap-demo/codegen:v1" .
gcloud run deploy sap-code-gen \
  --image "$REGION-docker.pkg.dev/$PROJECT_ID/sap-demo/codegen:v1" \
  --region "$REGION" --port 8080 \
  --memory 2Gi --cpu 1 --concurrency 4 \
  --timeout 3600 --min-instances 1 --max-instances 1 \
  --session-affinity --no-allow-unauthenticated \
  --set-env-vars ARTIFACT_DIR=/tmp/sap-artifacts
```

The deployed service is IAM-private. Grant only trusted demo operators
`roles/run.invoker`. A regular browser cannot send a Cloud Run identity token
by itself; for operator testing use `gcloud run services proxy sap-code-gen
--region="$REGION" --port=8080`, then open <http://localhost:8080>.
For external browser access, configure authenticated IAP behind an HTTPS load
balancer with WebSocket support and restrict Cloud Run ingress to that load
balancer. Do not make the raw service unauthenticated as an authentication
workaround. Use a dedicated runtime service account without unnecessary GCP
permissions, HTTPS, access auditing and token/data retention policies.

Streamlit uses long-lived WebSockets. Cloud Run's timeout can disconnect a
session after one hour; session affinity is best-effort, not durability. A
single warm instance reduces but does not eliminate session loss and incurs
idle cost. Refreshing/reconnecting, instance replacement or deployment can
lose credentials, requirement approval and conversations. Download finalized
specifications and code before leaving. Reimported specs require fresh approval.
Local container files are ephemeral and consume instance memory; reset clears
links but does not delete existing files. Limit demo duration/output volume,
and replace the instance periodically. Durable storage with retention, real
user identity/authorization, per-user quotas and audit records are prerequisites
for production rollout. There is no cross-session history browser or server
filesystem selector in the UI.

## Data and Verification

In personal mode, enter individual Atlassian and model credentials only in the session sidebar.
Requirements and conversation text are transmitted to the selected LLM provider.
Only approved public/synthetic data should be used. Generation MCP tools are
read-only; an explicit publish action launches one write tool for one chosen
destination. Description/page updates replace existing content. Review the
destination and permissions before confirming; inspect it before retrying any
timed-out write to avoid duplicates or unintended overwrites.

There is no SAP/BTP connection or deployment logic in the app. Download generated
files and import them manually into your SAP system. Generated objects have not
been syntax-checked, activated, run or deployed by this application. Perform
those checks separately in Eclipse ADT against your ABAP Cloud tenant.

Run `python3 -m unittest test_demo_backend -v` before packaging. These tests mock
providers and Atlassian APIs; they do not prove live credentials or cloud access.

## Shared link without visitor API credentials

Enable shared mode with `SAP_CODEGEN_SHARED_MODE=true` in the server environment.
Visitors do not enter API credentials or choose the model. Settings are read on
the server, never placed in widgets or loaded from the legacy `.env`. Personal
mode remains the default when the flag is absent. Do not bake secrets into the
image or commit them. Use a dedicated demo account, not your everyday account.

Required server variables:

| Variable | Purpose |
| --- | --- |
| `SAP_CODEGEN_LLM_PROVIDER` | `Google Gemini`, `OpenAI`, `Anthropic`, or `Azure OpenAI` |
| `SAP_CODEGEN_LLM_MODEL` | Your available model or deployment name |
| `SAP_CODEGEN_LLM_API_KEY` | Model API key, injected from Secret Manager |
| `SAP_CODEGEN_LLM_ENDPOINT` | Azure resource endpoint, only for Azure |
| `SAP_CODEGEN_REQUESTS_PER_HOUR` | Model attempts per instance, default 30, range 1-1000 |

Pasted/imported requirements need only the model connection. For Jira/Confluence,
also set `SAP_CODEGEN_JIRA_URL`, `SAP_CODEGEN_JIRA_EMAIL`,
`SAP_CODEGEN_JIRA_API_TOKEN`, `SAP_CODEGEN_CONFLUENCE_URL`,
`SAP_CODEGEN_CONFLUENCE_EMAIL`, and `SAP_CODEGEN_CONFLUENCE_API_TOKEN`.
Inject both API tokens from Secret Manager. Use read-only, least-privilege
Atlassian credentials on a site containing approved public/synthetic data only.
Set `SAP_CODEGEN_ALLOWED_TICKETS` to comma-separated exact keys such as
`KAN-4,KAN-5`, and `SAP_CODEGEN_ALLOWED_PAGES` to comma-separated numeric
Confluence IDs such as `425985,425986`. Empty lists deny all reads of that
resource. Unapproved linked pages are not fetched. Approved ticket content,
including its comments and link metadata, is visible to visitors. Publishing
is disabled in both the UI and backend in shared mode.

Create the model secret through Google Cloud Secret Manager's console. Grant
the dedicated runtime service account `roles/secretmanager.secretAccessor`
on that secret only. After deploying the image with these changes, an operator
can configure an existing Cloud Run service without putting the key in commands:

```sh
gcloud run services update sap-code-gen --region="$REGION" \
  --update-env-vars='SAP_CODEGEN_SHARED_MODE=true,SAP_CODEGEN_LLM_PROVIDER=Google Gemini,SAP_CODEGEN_LLM_MODEL=gemini-3.5-flash-lite,SAP_CODEGEN_REQUESTS_PER_HOUR=30' \
  --update-secrets=SAP_CODEGEN_LLM_API_KEY=sap-codegen-llm-key:1
```

Use the authenticated external browser access described above for trusted users;
they may sign in for access but need no Atlassian or model API credentials.
For an intentionally anonymous, public/synthetic-only demonstration, the
operator may explicitly grant public invocation instead:

```sh
gcloud run services add-iam-policy-binding sap-code-gen --region="$REGION" \
  --member=allUsers --role=roles/run.invoker
gcloud run services describe sap-code-gen --region="$REGION" --format='value(status.url)'
```

The resulting HTTPS URL is the shareable link; localhost is not shareable.
Anyone with public access can consume your quota and see approved source data.
The hourly model limiter is shared across sessions in one process, counts
failed API attempts, and resets on process restart; it is not a durable billing
or abuse-control boundary. Keep `--max-instances 1`, apply provider-enforced
quotas and billing alerts, and use authenticated access plus durable rate
limiting for production. Retrieval is not rate-limited by the model limiter.
Organization policy may prohibit anonymous invocation. Cloud deployment and
live secret injection have not been validated by the mocked tests.