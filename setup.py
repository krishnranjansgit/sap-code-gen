#!/usr/bin/env python3
"""
Interactive onboarding for SAP Code Generator.

Run this once after cloning:
    python3 setup.py

Prompts for credentials/config, writes .env + sap_systems.json, registers
MCP servers with Claude Code, and verifies connectivity where possible.
Safe to re-run — each section can be skipped if already configured.

What this can't automate: downloading the SAP NW RFC SDK (behind an SAP
support portal login) -- see sap-rfc-mcp/README.md for that one manual step.
"""

import getpass
import json
import os
import shutil
import subprocess
import sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
ABAP_ACCELERATOR_REPO_URL = (
    "https://github.com/aws-solutions-library-samples/"
    "guidance-for-deploying-sap-abap-accelerator-for-amazon-q-developer.git"
)

ABAPGIT_XML_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">
 <asx:values>
  <DATA>
   <MASTER_LANGUAGE>E</MASTER_LANGUAGE>
   <STARTING_FOLDER>/src/</STARTING_FOLDER>
   <FOLDER_LOGIC>PREFIX</FOLDER_LOGIC>
   <IGNORE_SUBPACKAGES>X</IGNORE_SUBPACKAGES>
  </DATA>
 </asx:values>
</asx:abap>
"""


# ------------------------------------------------------------------
# Small helpers
# ------------------------------------------------------------------
def section(title: str):
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def ask(prompt: str, default: str = None, secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    if secret:
        value = getpass.getpass(f"{prompt}{suffix}: ")
    else:
        value = input(f"{prompt}{suffix}: ").strip()
    return value or (default or "")


def yes_no(prompt: str, default: bool = True) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    value = input(f"{prompt}{suffix}: ").strip().lower()
    if not value:
        return default
    return value.startswith("y")


def run(cmd, check: bool = True, **kwargs):
    """subprocess.run with output visible, returning the CompletedProcess."""
    result = subprocess.run(cmd, **kwargs)
    if check and result.returncode != 0:
        print(f"  Command failed: {' '.join(str(c) for c in cmd)}")
    return result


def run_quiet(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


# ------------------------------------------------------------------
# 0. Prerequisites
# ------------------------------------------------------------------
def check_prerequisites():
    section("0. Checking prerequisites")
    missing = [tool for tool in ("claude", "git", "python3") if shutil.which(tool) is None]
    if missing:
        print(f"Missing required tools: {', '.join(missing)}. Install them first, then re-run.")
        sys.exit(1)
    if shutil.which("gh") is None:
        print("Note: `gh` (GitHub CLI) not found -- you'll need it for the abapGit repo step, "
              "or you can set that repo up manually and just point this script at it.")
    print("Required tools found.")


# ------------------------------------------------------------------
# 1. Claude Code OAuth token
# ------------------------------------------------------------------
def setup_claude_token():
    section("1. Claude Code OAuth token")
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        print("CLAUDE_CODE_OAUTH_TOKEN is already set in this shell -- skipping.")
        return
    print("Run `claude setup-token` in another terminal if you haven't already "
          "(it opens a browser once, then prints a token starting sk-ant-oat01-...).")
    if not yes_no("Do you have that token ready to paste in now?", default=True):
        print("Skipping -- add it to your shell profile yourself before running the app:")
        print('  export CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat01-..."')
        return
    token = ask("Paste your CLAUDE_CODE_OAUTH_TOKEN", secret=True)
    if not token:
        print("No token entered -- skipping.")
        return
    shell = os.environ.get("SHELL", "")
    profile = os.path.expanduser("~/.zshrc" if "zsh" in shell else "~/.bashrc")
    with open(profile, "a") as f:
        f.write(f'\nexport CLAUDE_CODE_OAUTH_TOKEN="{token}"\n')
    print(f"Appended to {profile}. Open a new terminal for it to take effect.")


# ------------------------------------------------------------------
# 2. Jira / Confluence
# ------------------------------------------------------------------
def setup_jira_confluence(env_updates: dict):
    section("2. Jira / Confluence (mcp-atlassian)")
    if not yes_no("Configure Jira/Confluence now?", default=True):
        return
    mcp_name = ask("MCP server name to register", default="mcp-atlassian")
    jira_url = ask("Jira base URL", default="https://jira.example.com")
    jira_token = ask("Jira Personal Access Token", secret=True)
    confluence_url = ask("Confluence base URL", default="https://wiki.example.com")
    confluence_token = ask("Confluence Personal Access Token", secret=True)

    run_quiet(["claude", "mcp", "remove", mcp_name, "-s", "user"])
    result = run([
        "claude", "mcp", "add", mcp_name, "-s", "user",
        "-e", f"JIRA_URL={jira_url}",
        "-e", f"JIRA_PERSONAL_TOKEN={jira_token}",
        "-e", "JIRA_SSL_VERIFY=false",
        "-e", f"CONFLUENCE_URL={confluence_url}",
        "-e", f"CONFLUENCE_PERSONAL_TOKEN={confluence_token}",
        "-e", "CONFLUENCE_SSL_VERIFY=false",
        "--", "uvx", "mcp-atlassian",
    ], check=False)
    if result.returncode == 0:
        print(f"Registered '{mcp_name}' with Claude Code.")

    env_updates["JIRA_WIKI_MCP_NAME"] = mcp_name
    env_updates["CONFLUENCE_URL"] = confluence_url
    env_updates["CONFLUENCE_PERSONAL_TOKEN"] = confluence_token


# ------------------------------------------------------------------
# 3. SAP RFC MCP server
# ------------------------------------------------------------------
def setup_sap_rfc(env_updates: dict):
    section("3. SAP RFC MCP server (table reads)")
    if not yes_no("Configure the SAP RFC server now?", default=True):
        return
    rfc_dir = os.path.join(PROJECT_DIR, "sap-rfc-mcp")

    sdk_path = ask("Path to your extracted NW RFC SDK", default="/usr/local/sap/nwrfcsdk")
    if not os.path.isdir(sdk_path):
        print(f"  Warning: {sdk_path} doesn't exist. See sap-rfc-mcp/README.md -- "
              "this needs a manual SAP SDK download before pyrfc will work.")

    host = ask("SAP application server host (SAP_ASHOST)")
    sysnr = ask("Instance number (SAP_SYSNR)", default="00")
    client = ask("Client (SAP_CLIENT)", default="100")
    user = ask("SAP username")
    passwd = ask("SAP password", secret=True)
    mcp_name = ask("MCP server name to register", default="sap-rfc")

    with open(os.path.join(rfc_dir, ".env"), "w") as f:
        f.write(
            f"SAP_ASHOST={host}\nSAP_SYSNR={sysnr}\nSAP_CLIENT={client}\n"
            f"SAP_USER={user}\nSAP_PASSWD={passwd}\nSAP_LANG=EN\n"
        )
    print(f"Wrote {rfc_dir}/.env")

    venv_dir = os.path.join(rfc_dir, ".venv")
    if not os.path.exists(venv_dir):
        print("Creating virtualenv and installing dependencies (pyrfc may fail here "
              "without the SDK in place -- that's OK, fix it later and re-run pip install)...")
        run([sys.executable, "-m", "venv", venv_dir])
        run([os.path.join(venv_dir, "bin", "pip"), "install", "-q", "-r",
             os.path.join(rfc_dir, "requirements.txt")], check=False)

    run_quiet(["claude", "mcp", "remove", mcp_name, "-s", "user"])
    result = run([
        "claude", "mcp", "add", mcp_name, "-s", "user",
        "-e", f"SAPNWRFC_HOME={sdk_path}",
        "-e", f"DYLD_LIBRARY_PATH={sdk_path}/lib",
        "--", os.path.join(venv_dir, "bin", "python3"), os.path.join(rfc_dir, "sap_mcp_server.py"),
    ], check=False)
    if result.returncode == 0:
        print(f"Registered '{mcp_name}' with Claude Code.")

    env_updates["SAP_RFC_MCP_NAME"] = mcp_name


# ------------------------------------------------------------------
# 4. abap-accelerator (one or more SAP systems)
# ------------------------------------------------------------------
def setup_abap_accelerator(env_updates: dict):
    section("4. ABAP Accelerator (source/object access per SAP system)")
    if not yes_no("Configure ABAP Accelerator now?", default=True):
        return

    accel_dir = ask("Local path for abap-accelerator-mcp",
                     default=os.path.expanduser("~/abap-accelerator-mcp"))
    accel_dir = os.path.expanduser(accel_dir)
    if not os.path.isdir(accel_dir):
        if yes_no(f"Clone the AWS abap-accelerator repo into {accel_dir}?", default=True):
            run(["git", "clone", ABAP_ACCELERATOR_REPO_URL, accel_dir])
        else:
            print("Skipping ABAP Accelerator setup -- point ABAP_ACCELERATOR_DIR at your "
                  "own clone in .env later.")
            return

    venv_dir = os.path.join(accel_dir, ".venv")
    if not os.path.exists(venv_dir):
        print("Creating virtualenv and installing dependencies...")
        run([sys.executable, "-m", "venv", venv_dir])
        run([os.path.join(venv_dir, "bin", "pip"), "install", "-q", "-r",
             os.path.join(accel_dir, "requirements.txt")], check=False)

    systems = {}
    port = 8010
    print("\nAdd one entry per SAP system (e.g. dev, stage). Leave the key blank to stop.")
    while True:
        key = ask("System key (e.g. dev)")
        if not key:
            break
        label = ask("Display label", default=key.capitalize())
        host = ask("SAP host (include :port here for a non-standard ADT port)")
        instance_number = ask("Instance number", default="00")
        client = ask("Client", default="100")
        username = ask("Username")
        password = ask("Password", secret=True)
        secure = yes_no("Use HTTPS?", default=True)

        instance_dir = os.path.join(accel_dir, "instances", key)
        os.makedirs(instance_dir, exist_ok=True)
        lines = [f"SAP_HOST={host}"]
        if ":" not in host:
            lines.append(f"SAP_INSTANCE_NUMBER={instance_number}")
        lines += [
            f"SAP_CLIENT={client}",
            f"SAP_USERNAME={username}",
            f"SAP_PASSWORD={password}",
            "SAP_LANGUAGE=EN",
            f"SAP_SECURE={'true' if secure else 'false'}",
            "SERVER_HOST=127.0.0.1",
            f"SERVER_PORT={port}",
            "SSL_VERIFY=false",
            "LOG_LEVEL=INFO",
        ]
        with open(os.path.join(instance_dir, ".env"), "w") as f:
            f.write("\n".join(lines) + "\n")
        print(f"Wrote {instance_dir}/.env")

        mcp_name = f"abap-accelerator-{key}"
        run_quiet(["claude", "mcp", "remove", mcp_name, "-s", "user"])
        result = run([
            "claude", "mcp", "add", "--transport", "http", mcp_name,
            f"http://127.0.0.1:{port}/mcp", "-s", "user",
        ], check=False)
        if result.returncode == 0:
            print(f"Registered '{mcp_name}' with Claude Code (not started yet -- "
                  "use the Streamlit sidebar to start it).")

        systems[key] = {"label": label, "mcp_name": mcp_name, "port": port}
        port += 1
        if not yes_no("Add another SAP system?", default=False):
            break

    with open(os.path.join(PROJECT_DIR, "sap_systems.json"), "w") as f:
        json.dump(systems, f, indent=2)
    print(f"Wrote sap_systems.json ({len(systems)} system(s))")

    env_updates["ABAP_ACCELERATOR_DIR"] = accel_dir


# ------------------------------------------------------------------
# 5. abapGit target repo
# ------------------------------------------------------------------
def setup_abapgit_repo(env_updates: dict):
    section("5. abapGit target repo")
    if not yes_no("Configure the abapGit repo now?", default=True):
        return

    local_path = ask("Local path to clone the abapGit repo into",
                      default=os.path.expanduser("~/sap-abapgit-repo"))
    local_path = os.path.expanduser(local_path)

    if os.path.isdir(os.path.join(local_path, ".git")):
        print("Already exists locally -- skipping clone/create.")
    elif yes_no("Create a new private GitHub repo for this via `gh`?", default=True):
        repo_name = ask("GitHub repo name", default="sap-abapgit-repo")
        parent = os.path.dirname(local_path) or "."
        os.makedirs(parent, exist_ok=True)
        result = run([
            "gh", "repo", "create", repo_name, "--private",
            "--description", "Generated ABAP code, pulled into SAP via zabapgit",
        ], check=False)
        if result.returncode != 0:
            print("`gh repo create` failed -- create the repo manually and re-run, "
                  "or answer 'n' next time and paste an existing remote URL.")
            return
        clone_result = run(["gh", "repo", "clone", repo_name, local_path], check=False)
        if clone_result.returncode != 0:
            print(f"Repo created but clone failed -- clone it manually to {local_path}.")
            return
    else:
        remote_url = ask("Existing git remote URL to clone")
        if not remote_url:
            print("No URL given -- skipping.")
            return
        run(["git", "clone", remote_url, local_path])

    os.makedirs(os.path.join(local_path, "src"), exist_ok=True)
    abapgit_xml = os.path.join(local_path, ".abapgit.xml")
    if not os.path.exists(abapgit_xml):
        with open(abapgit_xml, "w") as f:
            f.write(ABAPGIT_XML_TEMPLATE)
        open(os.path.join(local_path, "src", ".gitkeep"), "a").close()
        run(["git", "add", "-A"], cwd=local_path, check=False)
        run(["git", "commit", "-m", "Initial abapGit repo structure"], cwd=local_path, check=False)
        run(["git", "push"], cwd=local_path, check=False)
        print(f"Initialized abapGit repo structure at {local_path}")

    env_updates["ABAPGIT_REPO_DIR"] = local_path


# ------------------------------------------------------------------
# 6. Personalize CLAUDE.md
# ------------------------------------------------------------------
def personalize_claude_md():
    section("6. Personalize CLAUDE.md")
    path = os.path.join(PROJECT_DIR, "CLAUDE.md")
    with open(path) as f:
        content = f.read()
    if "<CUSTOM_PREFIX>" not in content:
        print("CLAUDE.md already personalized -- skipping.")
        return
    prefix = ask("Custom ABAP object naming prefix (e.g. ZJDOE)", default="ZDEV").upper()
    content = content.replace("<CUSTOM_PREFIX>", prefix)
    with open(path, "w") as f:
        f.write(content)
    print(f"CLAUDE.md updated with prefix {prefix}_*")


# ------------------------------------------------------------------
# Write .env (merging with anything already there)
# ------------------------------------------------------------------
def write_env_file(env_updates: dict):
    section("Writing .env")
    path = os.path.join(PROJECT_DIR, ".env")
    existing = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    existing[k] = v
    existing.update(env_updates)
    with open(path, "w") as f:
        for k, v in existing.items():
            f.write(f"{k}={v}\n")
    print(f"Wrote {path} ({len(existing)} variable(s))")


def main():
    print("SAP Code Generator -- interactive setup")
    check_prerequisites()
    env_updates = {}
    setup_claude_token()
    setup_jira_confluence(env_updates)
    setup_sap_rfc(env_updates)
    setup_abap_accelerator(env_updates)
    setup_abapgit_repo(env_updates)
    write_env_file(env_updates)
    personalize_claude_md()

    section("Done")
    print("Next steps:")
    print("  1. Open a NEW terminal (so CLAUDE_CODE_OAUTH_TOKEN loads, if you set it).")
    print("  2. pip install -r requirements.txt --break-system-packages")
    print("  3. streamlit run app.py")
    print("\nRe-run `python3 setup.py` any time to reconfigure or add another SAP system.")


if __name__ == "__main__":
    main()
