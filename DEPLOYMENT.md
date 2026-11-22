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

Enter individual Atlassian and model credentials only in the session sidebar.
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