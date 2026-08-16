# SAP Code Generator — Project Context

This project turns a Jira ticket into generated SAP code (ABAP or Fiori/UI5),
grounded in a linked Confluence design doc where one exists, and refined
through conversation until you're satisfied with the result.

This file is read automatically by Claude Code at the start of every
session in this folder — you don't need to repeat this context each time.

If any of the tools below aren't registered yet, run `python3 setup.py`
from the project root first — it configures and registers everything.

## Available tools

This project expects the following MCP connectors to be configured in
Claude Code (`claude mcp list` to check; `python3 setup.py` sets these up):

- **Jira** — for fetching ticket details, comments, linked issues
- **Wiki / Confluence** — for fetching linked design docs. Note: if the
  native `confluence_search`/`confluence_get_page` MCP tools error against
  your Confluence instance, that's a known class of bug on some
  Server/Data Center instances, not necessarily a config issue on this
  end. Use these workaround scripts instead, which hit the REST endpoints
  directly (both scoped into `ALLOWED_TOOLS`):
  - `python3 confluence_search.py "<query>"` — to find a page
  - `python3 confluence_get_page.py <page-id-or-url>` — to fetch one
- **SAP tools** (`sap-cap`, `sap-fiori`, `sap-ui5`) — for live grounding:
  UI5 API references, CAP model definitions, Fiori guidelines, etc. Use
  these tools whenever generating Fiori/UI5/CAP code — don't rely on
  memorized API signatures when a live lookup is available.
- **sap-rfc** (vendored in `sap-rfc-mcp/`) — raw table reads via
  `read_table` (RFC_READ_TABLE; no WHERE-clause filtering, capped at
  500 rows). Use for actual data, not source code.
- **abap-accelerator-\<system\>** (one per system defined in
  `sap_systems.json`, e.g. `abap-accelerator-dev`) — the real way to
  read/search existing ABAP objects: `aws_abap_cb_get_source`,
  `aws_abap_cb_search_object`, `aws_abap_cb_get_objects`,
  `aws_abap_cb_get_transport_requests`, `aws_abap_cb_get_migration_analysis`,
  `aws_abap_cb_check_syntax`, `aws_abap_cb_run_atc_check`. Backed by the
  ADT REST API. Each is a standalone server started/stopped manually from
  the Streamlit sidebar — if a call fails, check whether the relevant
  system is running there before assuming it's a code/config problem. Ask
  which system is relevant if it's not obvious from the ticket.
  Deliberately scoped to read-only tools in `ALLOWED_TOOLS` — these
  servers also have `create_object`/`update_source`/`activate_object`,
  but those are NOT enabled here; don't suggest using them. When a ticket
  requires modifying an existing program, read it via
  `aws_abap_cb_get_source`, then present the changed code back as usual
  rather than writing it back to SAP directly.
- **abapGit repo** (path from `ABAPGIT_REPO_DIR` in `.env`) — where
  generated code lands for pulling into SAP via zabapgit. Check its state
  with `python3 check_abapgit_repo.py [log|status|files|show <path>]`
  (read-only — no GitHub login needed for this). Pushing is intentionally
  NOT available from chat — it only happens via the sidebar's
  **📤 Push to abapGit repo** button (or `export_to_abapgit.py --push`
  run manually), so don't attempt to push even if asked; point to the
  button instead.

## Workflow (used by /gen-sap-code, or just describe a ticket directly)

1. Fetch the Jira ticket (key, summary, description, comments, labels,
   component, any linked issues).
2. If the ticket description, comments, or linked issues reference a
   Confluence/wiki page, fetch that page's content too (use
   `confluence_get_page.py`, not the native tool — see Available tools
   above). If a design doc is expected but not directly linked, search
   for it with `confluence_search.py` before giving up.
3. Classify the ticket as ABAP work, Fiori/UI5 work, or both, based on
   component/labels/description. State the classification explicitly
   before generating code.
4. Generate code following the conventions below. For Fiori/UI5/CAP work,
   consult the relevant SAP MCP tool (`sap-ui5:get_guidelines`,
   `sap-ui5:get_api_reference`, `sap-cap:search_docs`, `sap-fiori:search_docs`)
   rather than guessing at API details.
5. Present the code, a one-paragraph summary of what it does, and any
   assumptions or open questions.
6. Wait for feedback. If a test failure is reported, a different pattern
   is requested, or something is flagged as wrong, revise the SAME code —
   don't restart from the ticket. Keep changes scoped to what was flagged;
   leave everything else as-is. Always show the full corrected file(s)
   again (not a diff), so each round is a complete, runnable snapshot.
7. Repeat step 6 as many times as needed.

## ABAP conventions

- Custom object naming prefix: `ZKRANJAN_*` (set by `setup.py` —
  if you still see the literal placeholder here, run `python3 setup.py`)
- Use `CL_SALV_TABLE` for ALV list output unless the ticket specifies
  otherwise (e.g. `CL_GUI_ALV_GRID` for editable grids)
- Assume BRIM / SD / FI-CA table context where relevant — e.g. `DFKKOP`,
  `DFKKINVDOC_H/I`, `VBAK`, `VCNUM` — when the ticket references billing,
  invoicing, orders, or partner data
- Clean-code practices: meaningful names, no unnecessary `SELECT *`,
  proper exception handling
- Header comment block on generated reports/classes: ticket key, short
  description, author placeholder

## Dictionary objects (tables, structures)

If a ticket requires a new Z-table or structure, it isn't real ABAP source
— represent it as plain text in this exact format so it converts cleanly
into abapGit's XML format:

```
* ZKRANJAN_XXX.tabl
TABLE: ZKRANJAN_XXX
DESCRIPTION: <short description>
DELIVERY_CLASS: A
FIELDS:
  MANDT | KEY | MANDT
  SKU_ID | KEY | CHAR20 | SKU identifier
  STATUS | | CHAR1 | Processing status
```

(`.struc` instead of `.tabl`, and `STRUCTURE:` instead of `TABLE:` for a
plain structure — omit `DELIVERY_CLASS` there, and keys don't apply.)

Each field line is `NAME | KEY(optional, tables only) | TYPE | description`.
For `TYPE`, **strongly prefer referencing an existing SAP data element**
(e.g. `MANDT`, or one already used by a table this ticket touches) over an
inline built-in type (`CHAR20`, `NUMC10`, `DEC15.2`, `INT4`, `DATS`, `TIMS`,
`STRING`) — referencing a real data element is far more reliable since SAP
derives the technical attributes automatically on activation, whereas
inline types are a best-effort conversion. If you don't know a suitable
existing data element, say so as an open question rather than inventing one.

## Fiori / UI5 conventions

- Standard SAPUI5 MVC structure (Component.js, manifest.json, views,
  controllers)
- Default to JavaScript unless the ticket specifies TypeScript
- Prefer Fiori Elements / annotation-driven approach for standard
  list-report or object-page patterns; freestyle UI5 only when the
  ticket calls for custom interactions
- Header comment: ticket key, short description, author placeholder

## Output structure

Always structure generated-code responses as:

```
## Ticket Summary
<one paragraph>

## Classification
<ABAP / FIORI / BOTH>

## Code
<one fenced code block per file>

## Notes
<assumptions, open questions>
```

**The filename must be the literal first line inside each fenced code
block** — not a comment above/outside the fence, and not buried after
other header lines. The app parses this to name saved files, so getting
it wrong (or omitting it) means the file gets a generic fallback name
that later tooling (e.g. the abapGit export) won't recognize. Example:

```abap
* Z_EXAMPLE_REPORT.abap
*&---------------------------------------------------------------------*
*& Report Z_EXAMPLE_REPORT
*& ...
*&---------------------------------------------------------------------*
REPORT z_example_report.
...
```

Save generated files under `./generated/<ticket-key>/` — create the
directory if it doesn't exist. Use `v1`, `v2`, etc. as a suffix on
filenames for each revision round so earlier versions aren't overwritten.
