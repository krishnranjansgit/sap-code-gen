"""
SAP Code Generator — UI
------------------------
A local web UI (Streamlit) that drives Claude Code in headless "print mode"
as a subprocess — no API key, no terminal typing. Runs on your Claude
subscription via a long-lived token (see README for one-time setup).

Run with:
    streamlit run app.py
"""

import os
import re
import json
import signal
import socket
import subprocess
import time
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------
# This should be the folder containing CLAUDE.md and .claude/commands/
# (i.e. this same project folder) so Claude Code picks up your
# conventions and slash command automatically.
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
GENERATED_DIR = os.path.join(PROJECT_DIR, "generated")

# All machine-specific config comes from .env + sap_systems.json (both
# gitignored, both written by `python3 setup.py`) -- nothing here should
# be hardcoded to any one person's laptop/paths/MCP server names.
load_dotenv(os.path.join(PROJECT_DIR, ".env"))

# check_abapgit_repo.py / export_to_abapgit.py reach into this sibling
# directory (outside PROJECT_DIR), which Claude Code's Bash sandbox blocks
# by default -- --add-dir in run_claude() below is what grants access.
ABAPGIT_REPO_DIR = os.environ.get("ABAPGIT_REPO_DIR", "")

# abap-accelerator is a standalone HTTP MCP server (unlike the stdio
# servers Claude Code spawns itself) -- each SAP system runs as its own
# instance (own port, own .env) and is started/stopped manually from the
# sidebar. See "SAP system lifecycle" below.
ABAP_ACCELERATOR_DIR = os.environ.get("ABAP_ACCELERATOR_DIR", "")
ABAP_ACCELERATOR_HOST = "127.0.0.1"

JIRA_WIKI_MCP_NAME = os.environ.get("JIRA_WIKI_MCP_NAME", "mcp-atlassian")
SAP_RFC_MCP_NAME = os.environ.get("SAP_RFC_MCP_NAME", "sap-rfc")


def _load_sap_systems() -> dict:
    """Load SAP system definitions from sap_systems.json (see
    sap_systems.json.example). Returns {} if not configured yet --
    the UI shows a clear "run setup.py" prompt rather than crashing."""
    path = os.path.join(PROJECT_DIR, "sap_systems.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        raw = json.load(f)
    systems = {}
    for key, cfg in raw.items():
        systems[key] = {
            **cfg,
            "dir": os.path.join(ABAP_ACCELERATOR_DIR, "instances", key),
            "log": f"/tmp/abap_{key}.log",
        }
    return systems


SAP_SYSTEMS = _load_sap_systems()

# Tool permissions for headless runs (no interactive terminal to approve
# prompts). Names come from JIRA_WIKI_MCP_NAME/SAP_RFC_MCP_NAME/
# sap_systems.json -- must match whatever you used in `claude mcp add
# <name> ...` (setup.py handles this for you).
ALLOWED_TOOLS = [
    f"mcp__{JIRA_WIKI_MCP_NAME}__*",
    f"mcp__{SAP_RFC_MCP_NAME}__*",
    "Read",
    "Write",
    # confluence_search.py / confluence_get_page.py work around the same
    # bug in mcp-atlassian's own confluence_search / confluence_get_page
    # tools (both error against this Confluence Server/DC instance) by
    # hitting the working REST endpoints directly. Scoped to just these
    # two scripts — not general Bash access.
    "Bash(python3 confluence_search.py:*)",
    "Bash(python3 confluence_get_page.py:*)",
    # Read-only inspection of the abapGit repo (log/status/file listing) --
    # no push/write capability. Pushing stays a manual sidebar-button action.
    "Bash(python3 check_abapgit_repo.py:*)",
] + [
    # abap-accelerator (one per configured SAP system): proper ADT-backed
    # SAP tooling. Deliberately scoped to read-only tools only --
    # create/update/activate tools exist on this server but are
    # intentionally NOT allowed here.
    f"mcp__{cfg['mcp_name']}__{tool}"
    for cfg in SAP_SYSTEMS.values()
    for tool in [
        "aws_abap_cb_connection_status",
        "aws_abap_cb_get_objects",
        "aws_abap_cb_get_source",
        "aws_abap_cb_search_object",
        "aws_abap_cb_get_test_classes",
        "aws_abap_cb_get_migration_analysis",
        "aws_abap_cb_get_transport_requests",
        "aws_abap_cb_check_syntax",
        "aws_abap_cb_run_atc_check",
    ]
]

CLAUDE_TIMEOUT_SECONDS = 600


# ------------------------------------------------------------------
# Claude Code subprocess wrapper
# ------------------------------------------------------------------
def run_claude(prompt: str, resume_session_id: str = None) -> dict:
    """Call Claude Code headlessly and return its parsed JSON response.
    Raises RuntimeError with stderr content on failure."""
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--allowedTools", *ALLOWED_TOOLS,
    ]
    if ABAPGIT_REPO_DIR:
        cmd += ["--add-dir", ABAPGIT_REPO_DIR]
    if resume_session_id:
        cmd += ["--resume", resume_session_id]

    result = subprocess.run(
        cmd,
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        timeout=CLAUDE_TIMEOUT_SECONDS,
    )

    if result.returncode != 0:
        raise RuntimeError(f"claude exited {result.returncode}: {result.stderr.strip()}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Could not parse Claude Code output as JSON:\n{result.stdout}")


# ------------------------------------------------------------------
# SAP system lifecycle (each is a standalone HTTP MCP server process,
# not spawned by Claude Code itself -- started/stopped manually here)
# ------------------------------------------------------------------
def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _pid_on_port(port: int):
    """Find the PID of whatever's listening on a local port, if any.
    Looked up live (not tracked in session state) so Stop/Restart work
    correctly even after a Streamlit restart."""
    try:
        out = subprocess.run(
            ["lsof", "-ti", f":{port}"], capture_output=True, text=True, timeout=5
        )
        pids = [p for p in out.stdout.split() if p]
        return int(pids[0]) if pids else None
    except Exception:
        return None


def _parse_env_file(path: str) -> dict:
    env_vars = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env_vars[key.strip()] = value.strip()
    return env_vars


def start_sap_system(key: str, wait_seconds: float = 15) -> bool:
    """Start a SAP system's abap-accelerator instance if not already
    running. Returns True if it's up by the time this returns."""
    cfg = SAP_SYSTEMS[key]
    if _port_open(ABAP_ACCELERATOR_HOST, cfg["port"]):
        return True

    env_file = os.path.join(cfg["dir"], ".env")
    venv_python = os.path.join(ABAP_ACCELERATOR_DIR, ".venv", "bin", "python3")
    main_script = os.path.join(ABAP_ACCELERATOR_DIR, "src", "aws_abap_accelerator", "main.py")
    if not (os.path.exists(venv_python) and os.path.exists(main_script) and os.path.exists(env_file)):
        return False

    # Passed as real env vars rather than relying on main.py's own
    # load_dotenv(), which searches upward from its own script location
    # (not the cwd) and so can't find per-instance .env files here.
    env = os.environ.copy()
    env.update(_parse_env_file(env_file))
    env["PYTHONPATH"] = os.path.join(ABAP_ACCELERATOR_DIR, "src")
    with open(cfg["log"], "a") as log:
        subprocess.Popen(
            [venv_python, main_script],
            cwd=cfg["dir"],
            env=env,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if _port_open(ABAP_ACCELERATOR_HOST, cfg["port"]):
            return True
        time.sleep(0.5)
    return False


def stop_sap_system(key: str, wait_seconds: float = 5) -> bool:
    """Stop a SAP system's abap-accelerator instance. Returns True if
    it's confirmed stopped by the time this returns."""
    cfg = SAP_SYSTEMS[key]
    pid = _pid_on_port(cfg["port"])
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if not _port_open(ABAP_ACCELERATOR_HOST, cfg["port"]):
            return True
        time.sleep(0.3)
    return not _port_open(ABAP_ACCELERATOR_HOST, cfg["port"])


def restart_sap_system(key: str) -> bool:
    stop_sap_system(key)
    return start_sap_system(key)


# ------------------------------------------------------------------
# Parsing + saving generated code
# ------------------------------------------------------------------
def save_generated_files(ticket_key: str, raw_text: str, iteration: int):
    ticket_dir = os.path.join(GENERATED_DIR, ticket_key)
    os.makedirs(ticket_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    full_path = os.path.join(ticket_dir, f"v{iteration}_{timestamp}_full.md")
    with open(full_path, "w") as f:
        f.write(raw_text)

    saved_files = [full_path]

    code_section = re.search(r"##\s*Code(.*?)##\s*Notes", raw_text, re.DOTALL)
    if code_section:
        blocks = re.findall(r"```[\w-]*\n(.*?)```", code_section.group(1), re.DOTALL)
        for i, block in enumerate(blocks, start=1):
            first_line = block.strip().splitlines()[0] if block.strip() else ""
            m = re.search(r"([A-Za-z0-9_\-/]+\.\w+)", first_line)
            filename = (m.group(1) if m else f"file{i}.txt").replace("/", "_")
            path = os.path.join(ticket_dir, f"v{iteration}_{filename}")
            with open(path, "w") as f:
                f.write(block)
            saved_files.append(path)

    return saved_files


# ------------------------------------------------------------------
# Streamlit UI
# ------------------------------------------------------------------
st.set_page_config(page_title="SAP Code Generator", page_icon="🛠️", layout="wide")

st.markdown(
    """
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}

        div[data-testid="stChatMessage"] { border-radius: 12px; }
        div[data-testid="stExpander"] { border-radius: 10px; }
        .stButton>button { border-radius: 8px; }

        /* Header banner */
        .app-header {
            background: linear-gradient(90deg, #0a6ed1 0%, #4a9de0 100%);
            padding: 1.1rem 1.4rem;
            border-radius: 12px;
            margin-bottom: 1.2rem;
        }
        .app-header h1 { color: #ffffff; margin: 0; font-size: 1.6rem; }
        .app-header p { color: #eaf2fb; margin: 0.2rem 0 0 0; }

        /* Ticket card */
        .st-key-ticket-card {
            background-color: #eaf2fb;
            border: 1px solid #b8d7f5;
            border-radius: 12px;
            padding: 0.6rem 1rem;
        }

        /* Chat bubbles, tinted by role */
        div[class*="st-key-msg"][class*="-user"] {
            background-color: #eaf2fb;
            border-radius: 12px;
            padding: 0.2rem 0.6rem;
        }
        div[class*="st-key-msg"][class*="-assistant"] {
            background-color: #f0f7ee;
            border-radius: 12px;
            padding: 0.2rem 0.6rem;
        }

        /* Saved-files card */
        .st-key-saved-files {
            background-color: #fdf6e8;
            border-radius: 10px;
            padding: 0.3rem 0.8rem;
        }

        /* Chat input box */
        div[data-testid="stChatInput"] {
            border: 2px solid #b8d7f5;
            border-radius: 16px;
            background-color: #ffffff;
            box-shadow: 0 2px 8px rgba(10, 110, 209, 0.08);
            transition: border-color 0.15s ease, box-shadow 0.15s ease;
        }
        div[data-testid="stChatInput"]:focus-within {
            border-color: #0a6ed1;
            box-shadow: 0 2px 12px rgba(10, 110, 209, 0.18);
        }
        textarea[data-testid="stChatInputTextArea"] {
            color: #1a1d1f;
            font-size: 1rem;
        }
        button[data-testid="stChatInputSubmitButton"] {
            background-color: #0a6ed1;
            border-radius: 10px;
        }
    </style>
    <div class="app-header">
        <h1>🛠️ SAP Code Generator</h1>
        <p>Jira + Wiki → Claude Code → ABAP / Fiori code, refined through conversation.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "ticket_key" not in st.session_state:
    st.session_state.ticket_key = None
if "iteration" not in st.session_state:
    st.session_state.iteration = 0
if "history" not in st.session_state:
    st.session_state.history = []  # list of {"role": "user"/"assistant", "text": ...}


def send_message(text: str):
    """Send a message in the current (or a brand-new) session, resuming
    conversation history so Claude can answer questions or revise code
    with full context of the ticket/wiki/prior responses."""
    st.session_state.iteration += 1
    with st.spinner(f"Thinking (v{st.session_state.iteration})..."):
        try:
            data = run_claude(text, resume_session_id=st.session_state.session_id)
            st.session_state.session_id = data.get("session_id", st.session_state.session_id)
            reply = data.get("result", "")
            st.session_state.history.append({"role": "user", "text": text})
            st.session_state.history.append({"role": "assistant", "text": reply})
            folder = st.session_state.ticket_key or "session"
            saved = save_generated_files(folder, reply, st.session_state.iteration)
            st.session_state.last_saved = saved
            st.rerun()
        except RuntimeError as e:
            st.error(str(e))


with st.sidebar:
    st.markdown("### ⚙️ Environment")
    token_set = bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))
    if token_set:
        st.success("CLAUDE_CODE_OAUTH_TOKEN set", icon="✅")
    else:
        st.warning("CLAUDE_CODE_OAUTH_TOKEN not set — see README", icon="⚠️")

    st.divider()
    st.markdown("### 🖥️ SAP Systems")
    if not SAP_SYSTEMS:
        st.warning("No SAP systems configured — run `python3 setup.py`", icon="⚠️")
    for key, cfg in SAP_SYSTEMS.items():
        running = _port_open(ABAP_ACCELERATOR_HOST, cfg["port"])
        with st.container(border=True):
            st.markdown(f"**{cfg['label']}**")
            st.caption(("🟢 Running" if running else "⚪ Stopped") + f" · port {cfg['port']}")
            if running:
                c1, c2 = st.columns(2)
                if c1.button("⏹️ Stop", key=f"stop-{key}", use_container_width=True):
                    with st.spinner(f"Stopping {cfg['label']}..."):
                        stop_sap_system(key)
                    st.rerun()
                if c2.button("🔁 Restart", key=f"restart-{key}", use_container_width=True):
                    with st.spinner(f"Restarting {cfg['label']}..."):
                        if not restart_sap_system(key):
                            st.error(f"Failed to restart — check {cfg['log']}")
                    st.rerun()
            else:
                if st.button("▶️ Start", key=f"start-{key}", use_container_width=True):
                    with st.spinner(f"Starting {cfg['label']}..."):
                        if not start_sap_system(key):
                            st.error(f"Failed to start — check {cfg['log']}")
                    st.rerun()

    st.divider()
    st.caption(f"📁 `{PROJECT_DIR}`")
    if st.button("🔄 New ticket / reset session", use_container_width=True):
        st.session_state.session_id = None
        st.session_state.ticket_key = None
        st.session_state.iteration = 0
        st.session_state.history = []
        st.rerun()

# --- Ticket/wiki inputs (shown until code has actually been generated) ---
if st.session_state.ticket_key is None:
    with st.container(border=True, key="ticket-card"):
        st.markdown("#### 🎫 Start a new ticket")
        wiki_page = st.text_input(
            "Wiki / Confluence page (optional)",
            placeholder="Page URL, ID, or title — leave blank to use the page linked from the ticket",
        )
        ticket_key = st.text_input("Jira ticket key", placeholder="e.g. ACIS-1234")
        st.caption(
            "Not sure yet, or just want to review the requirement first? Skip this and "
            "ask about it in the chat below instead."
        )
        generate_clicked = st.button(
            "✨ Generate code", type="primary", disabled=not ticket_key, use_container_width=True
        )
    if generate_clicked:
        wiki_page = wiki_page.strip()
        if wiki_page:
            prompt = (
                f"Generate SAP code for Jira ticket {ticket_key.strip()}. "
                f"Fetch the ticket, then fetch this wiki/Confluence page for the design "
                f"doc: {wiki_page}. Use it to ground the requirement even if it differs "
                f"from (or isn't linked on) the ticket itself. Then follow the workflow "
                f"and output structure in CLAUDE.md."
            )
        else:
            prompt = (
                f"Generate SAP code for Jira ticket {ticket_key.strip()}. "
                f"Fetch the ticket and any linked wiki page first, then follow the "
                f"workflow and output structure in CLAUDE.md."
            )
        st.session_state.ticket_key = ticket_key.strip()
        send_message(prompt)
else:
    st.markdown(f"#### 🎫 Ticket: `{st.session_state.ticket_key}`")

st.divider()

# --- Conversation view (always visible) ---
for i, msg in enumerate(st.session_state.history):
    is_assistant = msg["role"] == "assistant"
    avatar = "🤖" if is_assistant else "🧑‍💻"
    with st.container(key=f"msg{i}-{'assistant' if is_assistant else 'user'}"):
        with st.chat_message("assistant" if is_assistant else "user", avatar=avatar):
            st.markdown(msg["text"])

if st.session_state.get("last_saved"):
    with st.container(key="saved-files"):
        with st.expander("📁 Files saved this round"):
            for p in st.session_state.last_saved:
                st.code(p, language=None)
        if st.button("📤 Push to abapGit repo", use_container_width=True):
            ticket_or_session = st.session_state.ticket_key or "session"
            with st.spinner("Converting and pushing to abapGit repo..."):
                result = subprocess.run(
                    ["python3", "export_to_abapgit.py", ticket_or_session, "--push"],
                    cwd=PROJECT_DIR, capture_output=True, text=True,
                )
            if result.returncode == 0:
                st.success("Pushed to abapGit repo")
            else:
                st.error("Push failed")
            st.code((result.stdout + result.stderr).strip(), language=None)

# --- Chat (always available — questions about the requirement/wiki/Jira/SAP
# code, or feedback to revise generated code, all share the same session) ---
chat_placeholder = (
    "Ask about the requirement, wiki, or Jira ticket — or request code"
    if st.session_state.session_id is None
    else "Ask a question, or tell me what to fix (or say it looks good)"
)
user_msg = st.chat_input(chat_placeholder)
if user_msg:
    send_message(user_msg)
