#!/usr/bin/env python3
"""
Confluence get-page workaround
-------------------------------
The mcp-atlassian `confluence_get_page` MCP tool fails against this
Confluence Server/Data Center instance the same way `confluence_search`
does (same underlying bug). This script fetches a page directly via the
REST API that confluence_search.py already proved works.

Requires CONFLUENCE_URL and CONFLUENCE_PERSONAL_TOKEN to be set in the
environment (same values used for the mcp-atlassian MCP server).

Usage:
    python3 confluence_get_page.py <page-id-or-url>

Accepts either a bare numeric page ID or a full Confluence page URL
(the ID is extracted from it).
"""

import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
CONFLUENCE_URL = os.environ.get("CONFLUENCE_URL", "").rstrip("/")
CONFLUENCE_PERSONAL_TOKEN = os.environ.get("CONFLUENCE_PERSONAL_TOKEN", "")


def extract_page_id(identifier: str) -> str:
    if identifier.isdigit():
        return identifier
    # e.g. /spaces/ECS/pages/3928204185/Title or ?pageId=3928204185
    m = re.search(r"/pages/(\d+)", identifier) or re.search(r"pageId=(\d+)", identifier)
    if m:
        return m.group(1)
    print(f"Could not extract a page ID from: {identifier}", file=sys.stderr)
    sys.exit(1)


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 confluence_get_page.py <page-id-or-url>", file=sys.stderr)
        sys.exit(1)
    if not CONFLUENCE_URL or not CONFLUENCE_PERSONAL_TOKEN:
        print(
            "CONFLUENCE_URL and/or CONFLUENCE_PERSONAL_TOKEN are not set in "
            "the environment.",
            file=sys.stderr,
        )
        sys.exit(1)

    page_id = extract_page_id(sys.argv[1])
    url = f"{CONFLUENCE_URL}/rest/api/content/{page_id}?expand=body.storage,version,space"

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

    title = data.get("title", "(untitled)")
    space = data.get("space", {}).get("key", "?")
    version = data.get("version", {})
    editor = version.get("by", {}).get("displayName", "unknown")
    when = version.get("when", "unknown")
    body = data.get("body", {}).get("storage", {}).get("value", "")

    print(f"# {title}")
    print(f"(space: {space} | last edited by: {editor} on {when})")
    print()
    print(body)


if __name__ == "__main__":
    main()
