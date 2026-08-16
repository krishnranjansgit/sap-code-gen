"""
Quick sanity check that the NWRFC SDK, PyRFC, and your SAP credentials
all work together before wiring anything into an MCP server.

Setup:
    1. cp .env.example .env
    2. Fill in your real SAP connection details in .env
    3. pip install pyrfc python-dotenv
    4. python3 test_connection.py

Security notes:
    - Credentials are loaded from environment variables / .env only.
      Never hardcode them in source code.
    - .env should be listed in .gitignore and never committed.
    - Connection errors are reported generically here; if you adapt
      this script for a shared/multi-user context, avoid echoing
      raw exception text (it can leak hostnames or internal details)
      to anyone other than the person running it locally.
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

REQUIRED_VARS = ["SAP_CLIENT", "SAP_USER", "SAP_PASSWD"]


def load_connection_params() -> dict:
    """Build PyRFC connection kwargs from environment variables only."""
    missing = [v for v in REQUIRED_VARS if not os.getenv(v)]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in your SAP details.")
        sys.exit(1)

    params = {
        "client": os.environ["SAP_CLIENT"],
        "user": os.environ["SAP_USER"],
        "passwd": os.environ["SAP_PASSWD"],
        "lang": os.getenv("SAP_LANG", "EN"),
    }

    # Direct application server connection
    if os.getenv("SAP_ASHOST"):
        params["ashost"] = os.environ["SAP_ASHOST"]
        params["sysnr"] = os.getenv("SAP_SYSNR", "00")
    # Message server / logon group routing
    elif os.getenv("SAP_MSHOST"):
        params["mshost"] = os.environ["SAP_MSHOST"]
        params["msserv"] = os.getenv("SAP_MSSERV", "3600")
        params["r3name"] = os.environ["SAP_R3NAME"]
        params["group"] = os.getenv("SAP_GROUP", "PUBLIC")
    else:
        print("Set either SAP_ASHOST or SAP_MSHOST (+ related vars) in .env")
        sys.exit(1)

    if os.getenv("SAP_SAPROUTER"):
        params["saprouter"] = os.environ["SAP_SAPROUTER"]

    return params


def main() -> None:
    try:
        from pyrfc import Connection
    except ImportError:
        print("pyrfc is not installed, or the arm64 SDK/Python/PyRFC "
              "versions don't match. Re-check the install steps.")
        sys.exit(1)

    params = load_connection_params()

    try:
        conn = Connection(**params)
    except Exception:
        # Fail securely: don't print raw exception details that might
        # contain hostnames or credentials embedded in error text.
        print("Connection failed. Check your .env values, network/SAProuter "
              "reachability, and that SAPNWRFC_HOME / DYLD_LIBRARY_PATH are set.")
        sys.exit(1)

    try:
        result = conn.call("RFC_SYSTEM_INFO")
        info = result.get("RFCSI_EXPORT", {})
        print("Connected successfully.")
        print(f"  System ID:   {info.get('RFCSAPRL', 'n/a')}")
        print(f"  Host:        {info.get('RFCHOST', 'n/a')}")
        print(f"  DB system:   {info.get('RFCDBSYS', 'n/a')}")
    except Exception:
        print("Connected, but the test RFC call failed. "
              "Check your user's RFC authorizations.")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
