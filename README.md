# SAP Code Generator — Claude Code version

No API key needed. Uses your Claude Pro/Max/Team/Enterprise subscription
via Claude Code, and drives Jira, Confluence, and SAP (both table reads and
ABAP source/object access) through MCP connectors.

Two ways to use this:
- **`app.py`** — a browser UI (recommended if you don't want a terminal)
- **`/gen-sap-code` slash command** — for the terminal, if you ever want it

## One-time setup

1. **Prerequisites**: Python **3.10+** (required by Streamlit/the MCP SDK —
   check with `python3 --version`), plus `git` and `gh` (GitHub CLI,
   authenticated — `gh auth status`). Install Claude Code if you haven't
   already.

2. **Clone this repo**, then run the interactive setup:
   ```bash
   git clone <this-repo-url>
   cd sap-code-gen
   python3 setup.py
   ```
   This walks you through everything below and wires it up automatically:
   - Your Claude Code OAuth token
   - Jira/Confluence (registers `mcp-atlassian`)
   - The vendored SAP RFC MCP server (`sap-rfc-mcp/`) for table reads
   - One or more SAP systems for ABAP source/object access (clones and
     configures [abap-accelerator](https://github.com/aws-solutions-library-samples/guidance-for-deploying-sap-abap-accelerator-for-amazon-q-developer))
   - Your abapGit target repo (creates a private GitHub repo via `gh`, or
     points at an existing one)
   - Personalizes `CLAUDE.md` with your custom ABAP object naming prefix

   It's safe to re-run — each section can be skipped if already configured,
   and you can re-run it later just to add another SAP system.

   **One thing `setup.py` can't automate**: PyRFC needs SAP's NW RFC SDK,
   which is behind an SAP support portal login. See
   `sap-rfc-mcp/README.md` for that one manual step — do it before running
   `setup.py`'s SAP RFC section, or come back and re-run that section after.

3. Install the UI's dependencies:
   ```bash
   pip install -r requirements.txt --break-system-packages
   ```

4. Open a **new terminal** (so your OAuth token loads from your shell
   profile), then confirm everything registered correctly:
   ```bash
   claude mcp list
   ```

## Using the UI

From inside the project folder:
```bash
streamlit run app.py
```

This opens a browser tab. The sidebar shows environment status (token set?
which SAP systems are running?) with **Start/Stop/Restart** controls for
each configured SAP system — nothing auto-starts, so start what you need.

From there:
1. Enter a Jira ticket key (and optionally a Confluence page) and click
   **Generate code** — or skip this and just ask about the requirement in
   the chat first if you're not ready to generate yet.
2. Claude fetches the ticket, pulls in any linked/specified wiki doc,
   classifies it as ABAP or Fiori/UI5, and generates the code.
3. Test it. Type feedback in the chat box (a test failure, a pattern to
   use instead, anything wrong) and press enter. Claude revises the same
   code — full conversation history is preserved via the session, so
   it's editing what it actually wrote, not starting over.
4. Repeat step 3 as many times as you like.
5. Click **New ticket / reset session** in the sidebar to start on a
   different ticket.

Every round's files are saved under `generated/<ticket-key>/`, named
`v1_...`, `v2_...`, etc. — nothing gets overwritten, so you can always go
back to an earlier version. An expander under the chat shows exactly
which files were saved each round.

## Pushing generated code to abapGit

Once you're happy with a round, click **📤 Push to abapGit repo** (next to
"Files saved this round"). This converts the latest generated files into
the format abapGit expects (`<name>.prog.abap`/`.xml` for reports,
`<name>.clas.abap`/`.xml` for classes, `<name>.tabl.xml`/`.struc.xml` for
tables/structures — see `CLAUDE.md` for the plain-text format Claude uses
to describe a dictionary object) and pushes them to whatever local path
you configured as `ABAPGIT_REPO_DIR` during setup. Object types beyond
these aren't auto-converted — the button's output will list anything
skipped so you can handle it manually.

**Dictionary object (table/structure) conversion is best-effort**,
especially for fields using an inline built-in type (`CHAR20`, `DEC15.2`,
etc.) rather than referencing an existing data element — do a trial
pull + activate in SAP before trusting this for a real deliverable.

From there, use **zabapgit** in your SAP system to pull from that repo
into a package. Two things worth checking on the SAP side before your
first pull:
- Your SAP system needs outbound network access to `github.com`.
- If the repo is private, the SAP HTTP connection zabapgit uses needs a
  GitHub personal access token (not your GitHub password) configured for
  authentication.

Pushing is deliberately **not** available by just asking Claude in chat —
only the button (or running `export_to_abapgit.py --push` yourself) does
it. Claude can still check what's already there read-only, e.g. "what's
in the abapGit repo?"

## Using the terminal version instead

If you'd rather type in a terminal on a given day, the same project still
works there — just run `claude` from inside the folder and either type
`/gen-sap-code ACIS-1234` or describe the ticket in plain language.

## Adding another SAP system later

Re-run `python3 setup.py` — it'll skip sections already configured and
let you add another entry to the "ABAP Accelerator" section. Each system
gets its own instance folder, port, and MCP server registration
(`abap-accelerator-<key>`), and shows up as its own card in the sidebar.

## Notes

- Because this runs through your subscription, keep it to your own
  individual use (per Anthropic's usage policy) — this isn't a setup for
  routing other people's requests through your seat.
- `ALLOWED_TOOLS` in `app.py` is deliberately scoped to just the tools this
  workflow needs, built from `.env`/`sap_systems.json` rather than
  hardcoded names. Headless runs can't show interactive permission
  prompts, so this list is what keeps a run from silently trying — and
  failing — to use something broader. Widen it only if you add tools
  this workflow genuinely needs.
- `.env` and `sap_systems.json` are gitignored (they're generated by
  `setup.py` and contain machine-specific paths/credentials) — the
  `.example` counterparts are what's actually committed.
- If you ever want this to also work without any interactive Claude Code
  session (e.g. triggered from a script or CI, or centrally hosted for a
  team), that's a different setup using the Claude Agent SDK with an API
  key — a separate effort from this local, per-person setup.
