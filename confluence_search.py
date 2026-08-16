#!/usr/bin/env python3
"""
Confluence search workaround
----------------------------
The mcp-atlassian `confluence_search` MCP tool 404s on every query against
this Confluence Server/Data Center instance, even though the equivalent
direct REST call works fine. This script hits that REST endpoint directly
so Claude can still find pages that aren't already linked from a ticket.

Requires CONFLUENCE_URL and CONFLUENCE_PERSONAL_TOKEN to be set in the
environment (same values used for the mcp-atlassian MCP server).

Usage:
    python3 confluence_search.py "<query>"

<query> can be plain text (matched against page content) or a raw CQL
expression (if it already contains ~, =, AND, or OR).
"""

import json
import os
import ssl
import sys
import urllib.parse
import urllib.request

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
CONFLUENCE_URL = os.environ.get("CONFLUENCE_URL", "").rstrip("/")
CONFLUENCE_PERSONAL_TOKEN = os.environ.get("CONFLUENCE_PERSONAL_TOKEN", "")
CQL_OPERATORS = ("~", "=", " AND ", " OR ")


def build_cql(query: str) -> str:
    if any(op in query for op in CQL_OPERATORS):
        return query
    escaped = query.replace('"', '\\"')
    return f'text ~ "{escaped}"'


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 confluence_search.py \"<query>\"", file=sys.stderr)
        sys.exit(1)
    if not CONFLUENCE_URL or not CONFLUENCE_PERSONAL_TOKEN:
        print(
            "CONFLUENCE_URL and/or CONFLUENCE_PERSONAL_TOKEN are not set in "
            "the environment.",
            file=sys.stderr,
        )
        sys.exit(1)

    cql = build_cql(sys.argv[1])
    params = urllib.parse.urlencode({"cql": cql, "expand": "version,space", "limit": 10})
    url = f"{CONFLUENCE_URL}/rest/api/content/search?{params}"

    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {CONFLUENCE_PERSONAL_TOKEN}"}
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(request, context=ctx, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} {e.reason}", file=sys.stderr)
        sys.exit(1)

    results = data.get("results", [])
    if not results:
        print("No results.")
        return

    for page in results:
        title = page.get("title", "(untitled)")
        space = page.get("space", {}).get("key", "?")
        editor = page.get("version", {}).get("by", {}).get("displayName", "unknown")
        when = page.get("version", {}).get("when", "unknown")
        webui = page.get("_links", {}).get("webui", "")
        print(f"- {title}")
        print(f"  space: {space} | last edited by: {editor} on {when}")
        print(f"  url: {CONFLUENCE_URL}{webui}")
        print()


if __name__ == "__main__":
    main()
