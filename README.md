# SAP Code Generator

External Jira Cloud / Confluence requirements refinement and SAP ABAP
Cloud code generation, with separate requirement and code conversations.

## Run locally

Use Python 3.13+ in a virtual environment:

```sh
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) for `uvx`.
The app launches `mcp-atlassian==0.24.6` in a temporary directory; the first
local request downloads connector dependencies. The Docker image instead
installs a dedicated connector environment at build time.

## Requirements workflow

For a shared link with no visitor API credentials, enable server-managed shared
mode as described in [DEPLOYMENT.md](DEPLOYMENT.md#shared-link-without-visitor-api-credentials).
The owner configures the model once; credential fields and publishing are hidden.
Jira/Confluence reads require exact owner-configured allowlists. Personal mode
below remains the default.

1. Enter your individual model API key and model/deployment name in the
   sidebar. Anthropic, OpenAI, Azure OpenAI and Google Gemini are supported. Azure also needs
   its resource endpoint; API version is `2024-10-21`. Web subscriptions do
   not guarantee API access or quota. The test button consumes API quota and may be billable.
   For Google, select **Google Gemini**, enter a key from
   [Google AI Studio](https://aistudio.google.com/api-keys), and a text model
   such as `gemini-3.5-flash-lite`. Requests use Google's fixed OpenAI-compatible
   endpoint through the existing OpenAI SDK; no additional dependency is needed.
   Check [current pricing](https://aistudio.google.com/docs/pricing) and your
   project's model access and quotas. Free-tier content may be used to improve
   Google's products; submit only synthetic/demo data under those terms.
2. In **Requirements**, choose Jira/wiki or paste a raw requirement. Jira/wiki
   needs site URLs, account emails and ordinary Atlassian Cloud API tokens
   supported by site-based authentication. Use a Confluence base URL ending
   in `/wiki`, a ticket such as `KAN-4`, and optionally a published page URL
   or numeric ID. Linked design pages are followed when no page is specified.
3. **Fetch & summarize** produces a sectioned specification. Review as BSA /
   Product Manager, QA or Developer, and refine it in the requirement chat.
   The role focus, requirements persona, code-generation persona and section
   template are exact snapshots from `sap-ai-codegen-platform-personal`.
   Separate external-cloud policies constrain those prompts to this app's
   actual capabilities; the reference repository is not a runtime dependency.
4. Edit the complete specification directly, or import a UTF-8 `.md`/`.txt`
   specification up to 100 KB. Explicitly approve and **Finalize requirement**.
   Generation uses the actual finalized editor text, not the original ticket.
   Manual edits, refinement, imports, source/account changes and approval
   withdrawal invalidate previously approved code and saved-file links.
5. Optionally publish the finalized spec as a Jira comment, replace a Jira
   description, create a Confluence page or update one. Enter a separate
   destination and explicitly authorize the write. Updating replaces content;
   changing document/target resets confirmation. Generation never has write
   tools. Verify the destination before retrying a timed-out publication.
6. In **Code generation**, generate, review and revise complete code files
   using its independent conversation. Download a ZIP and the finalized spec.

Pasted/imported specifications need only model settings; publishing still
requires configured Atlassian credentials with destination write permissions.
No local filesystem/repository picker or Git/SAP deployment control is exposed.

## Connections and data

In personal mode, credentials are masked and held only in the server's Streamlit session, not
written to `.env` or configuration files. Clearing connection settings removes
credentials, context and saved-file links, not files already on disk. Each
browser session has a separate random artifact directory. Model requests
contain requirements and conversation text, not the connection settings.
Use only public/synthetic material authorized for your selected provider.

Shared mode reads owner-managed credentials from server environment variables,
not visitor widgets. Conversations and artifacts remain separate per browser
session. All visitors consume the owner's model quota; an instance-wide hourly
limit defaults to 30 attempts. This does not replace authentication or durable
abuse controls. No shared history or credential browser is exposed.

The app does not connect to SAP and requires no SAP endpoint or access token.
Download generated files and import them into your SAP system manually.
No ABAP source grounding, syntax check, ATC, activation, execution or deployment
is performed; verify those separately in Eclipse ADT after import.
Classic RFC/ALV and unreleased-table assumptions are excluded from generation.

Outputs are versioned under `generated/<session-id>/<ticket-or-session>/` by
default, or under `ARTIFACT_DIR`. Sessions and local container files are not
durable; download your work. Legacy SAP connection, abapGit export and local
credential-setup utilities have been removed. No `.env` file is required.

## Docker and Google Cloud

See [DEPLOYMENT.md](DEPLOYMENT.md) for non-root Docker packaging, private
Cloud Run commands, authenticated external access and WebSocket/session
limitations. Authentication, quotas, durable per-user storage and retention
are required before a production multi-user launch.

## Tests

```sh
python3 -m unittest test_demo_backend -v
```

Tests mock external providers and MCP calls. Passing tests does not establish
live credential access or generated SAP object activation.

## Repository contents

- `app.py`: Streamlit requirements, approval, code generation and downloads.
- `demo_backend.py`: session-scoped Atlassian MCP and model API calls.
- `prompts.py`: requirements and code-generation prompts.
- `test_demo_backend.py`: mocked backend and Streamlit workflow regressions.
- `Dockerfile`, `.dockerignore`, `.gcloudignore`, `DEPLOYMENT.md`: deployment packaging.

Private connection files, generated downloads, logs and local dependencies are
ignored by Git. Before publishing, review `git status --short` and the staged
diff for secrets. Ignore rules do not remove secrets from existing Git history;
rotate any previously committed credentials and address that history separately.
