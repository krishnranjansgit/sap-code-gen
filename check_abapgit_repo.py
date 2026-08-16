#!/usr/bin/env python3
"""
Read-only inspection of the abapGit repo (path from ABAPGIT_REPO_DIR in
.env) so Claude can check what's been pushed without needing GitHub login
or broader git/gh access.

Usage:
    python3 check_abapgit_repo.py            # overview: log + status + files
    python3 check_abapgit_repo.py log
    python3 check_abapgit_repo.py status
    python3 check_abapgit_repo.py files
    python3 check_abapgit_repo.py show <path-under-src>
"""

import os
import subprocess
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
REPO_DIR = os.environ.get("ABAPGIT_REPO_DIR", "")
if not REPO_DIR:
    print("ABAPGIT_REPO_DIR is not set. Run `python3 setup.py` first, or set it in .env.", file=sys.stderr)
    sys.exit(1)


def _git(*args):
    result = subprocess.run(
        ["git", *args], cwd=REPO_DIR, capture_output=True, text=True, timeout=15
    )
    return result.stdout.strip() or result.stderr.strip()


def cmd_log():
    print(_git("log", "--oneline", "-15"))


def cmd_status():
    print(_git("status", "--short"))


def cmd_files():
    print(_git("ls-files", "src/"))


def cmd_show(rel_path: str):
    full_path = os.path.normpath(os.path.join(REPO_DIR, "src", rel_path))
    src_dir = os.path.normpath(os.path.join(REPO_DIR, "src"))
    if not full_path.startswith(src_dir + os.sep):
        print("Refusing to show a path outside src/.", file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile(full_path):
        print(f"No such file: src/{rel_path}", file=sys.stderr)
        sys.exit(1)
    with open(full_path) as f:
        print(f.read())


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("=== Recent commits ===")
        cmd_log()
        print("\n=== Working tree status ===")
        cmd_status()
        print("\n=== Files in src/ ===")
        cmd_files()
    elif args[0] == "log":
        cmd_log()
    elif args[0] == "status":
        cmd_status()
    elif args[0] == "files":
        cmd_files()
    elif args[0] == "show" and len(args) > 1:
        cmd_show(args[1])
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
