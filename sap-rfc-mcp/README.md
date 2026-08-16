# SAP RFC MCP Server (vendored starter)

A minimal MCP server exposing read-only SAP RFC tools (`sap_system_info`,
`read_table`), built on PyRFC and the SAP NW RFC SDK. `setup.py` (in the
project root) walks you through configuring and registering this — the
one thing it *can't* automate is below.

## Prerequisite that can't be automated

PyRFC requires SAP's NW RFC SDK, which is behind an SAP support portal
login and can't be scripted:

1. Download NWRFC SDK 7.50 (matching your CPU architecture) from SAP.
2. Extract it somewhere, e.g. `/usr/local/sap/nwrfcsdk`.
3. Have that extraction path ready — `setup.py` will ask for it and
   write it into `.env` as `SAPNWRFC_HOME`/`DYLD_LIBRARY_PATH` (or
   `LD_LIBRARY_PATH` on Linux).
4. A native Python 3.x matching your CPU architecture, and a PyRFC wheel
   matching your Python version (the PyPI package is yanked — get it
   from the PyRFC GitHub releases page).

Run `python3 test_connection.py` (after `setup.py` writes `.env`) to
confirm connectivity before relying on the MCP server itself — it uses
the same connection logic.

## What's included

- `sap_system_info` — confirms connectivity, returns system ID/host/DB
- `read_table` — read-only wrapper around `RFC_READ_TABLE`, with an
  allowlist filter on table/field names (no WHERE-clause filtering,
  capped at 500 rows — see `abap-accelerator` for richer object access)

## What's NOT included (by design)

No write/BAPI tools (creating sales orders, postings, etc.) are wired
in. Adding those means deciding who can trigger them from a chat
interface and reviewing exactly what your SAP user is authorized to
do — don't add them without thinking through that first.

## Security notes

- Credentials live only in `.env` (gitignored), never in source code.
- Table/field names from tool calls are validated against an
  allowlist before being sent to SAP, since `RFC_READ_TABLE` builds a
  query string from them.
- Errors returned to the model are generic; avoid changing this to
  surface raw exception text, since it can include hostnames or
  other internal details.
