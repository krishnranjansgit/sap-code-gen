"""
Minimal MCP server exposing a few read-oriented SAP RFC tools to
Claude Desktop via PyRFC.

Setup:
    pip install mcp pyrfc python-dotenv

Run manually (for testing):
    python3 sap_mcp_server.py

Then point claude_desktop_config.json at this file (see README.md).

Security notes:
    - Credentials come only from environment variables (.env), never
      from tool arguments or hardcoded values.
    - Table/field names passed in by the model are validated against
      allowlists of characters before being sent to SAP, since
      RFC_READ_TABLE builds a query from them.
    - This starter only exposes READ operations. Adding write/BAPI
      tools (e.g. creating sales orders) needs extra authorization
      checks -- don't wire those in without deciding who is allowed
      to trigger them and reviewing your SAP user's authorizations.
"""

import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

mcp = FastMCP("sap-rfc")

# Allowlist: table/field names are alphanumeric + underscore only.
# This blocks injection of RFC_READ_TABLE OPTIONS/WHERE-clause syntax.
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_/]{1,30}$")


def _get_connection():
    """Open a fresh PyRFC connection per call using env-only credentials."""
    from pyrfc import Connection

    params = {
        "client": os.environ["SAP_CLIENT"],
        "user": os.environ["SAP_USER"],
        "passwd": os.environ["SAP_PASSWD"],
        "lang": os.getenv("SAP_LANG", "EN"),
    }
    if os.getenv("SAP_ASHOST"):
        params["ashost"] = os.environ["SAP_ASHOST"]
        params["sysnr"] = os.getenv("SAP_SYSNR", "00")
    else:
        params["mshost"] = os.environ["SAP_MSHOST"]
        params["msserv"] = os.getenv("SAP_MSSERV", "3600")
        params["r3name"] = os.environ["SAP_R3NAME"]
        params["group"] = os.getenv("SAP_GROUP", "PUBLIC")
    if os.getenv("SAP_SAPROUTER"):
        params["saprouter"] = os.environ["SAP_SAPROUTER"]
    return Connection(**params)


@mcp.tool()
def sap_system_info() -> dict[str, Any]:
    """Return basic SAP system info (system ID, host, DB system) to confirm connectivity."""
    conn = None
    try:
        conn = _get_connection()
        result = conn.call("RFC_SYSTEM_INFO")
        info = result.get("RFCSI_EXPORT", {})
        return {
            "system_id": info.get("RFCSAPRL"),
            "host": info.get("RFCHOST"),
            "db_system": info.get("RFCDBSYS"),
        }
    except Exception:
        return {"error": "Could not retrieve system info. Check server logs."}
    finally:
        if conn is not None:
            conn.close()


@mcp.tool()
def read_table(table_name: str, fields: list[str], max_rows: int = 100) -> dict[str, Any]:
    """
    Read rows from a SAP table (e.g. DFKKOP, VBAK) via RFC_READ_TABLE.

    Args:
        table_name: SAP table name, e.g. "DFKKOP".
        fields: list of column names to return, e.g. ["OPBEL", "BETRW"].
        max_rows: maximum number of rows to fetch (capped at 500).
    """
    if not _SAFE_IDENTIFIER.match(table_name):
        return {"error": "Invalid table name."}
    for f in fields:
        if not _SAFE_IDENTIFIER.match(f):
            return {"error": f"Invalid field name: {f!r}"}

    safe_max_rows = max(1, min(max_rows, 500))

    conn = None
    try:
        conn = _get_connection()
        result = conn.call(
            "RFC_READ_TABLE",
            QUERY_TABLE=table_name,
            DELIMITER="|",
            FIELDS=[{"FIELDNAME": f} for f in fields],
            ROWCOUNT=safe_max_rows,
        )
        rows = [row["WA"].split("|") for row in result.get("DATA", [])]
        return {"table": table_name, "fields": fields, "rows": rows}
    except Exception:
        # Generic message: avoid leaking internal SAP error text verbatim
        # to the model/user; log details server-side if you add logging.
        return {"error": f"Could not read table {table_name}. Check authorizations and field names."}
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    mcp.run()
