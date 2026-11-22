"""
SAP Code Generator — UI
------------------------
A local Streamlit UI with session-scoped Cloud MCP and LLM connections.

Run with:
    streamlit run app.py
"""

import os
import re
import json
import hashlib
import io
import uuid
import zipfile
from datetime import datetime

import streamlit as st
from demo_backend import fetch_context, generate_reply, validate_settings, validate_llm_settings
from demo_backend import connection_settings as resolve_connection_settings, shared_mode, shared_allowlist
from prompts import requirements_prompt, codegen_prompt

# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
GENERATED_DIR = os.path.join(PROJECT_DIR, "generated")
GENERATED_DIR = os.environ.get("ARTIFACT_DIR", GENERATED_DIR)

# ------------------------------------------------------------------
# Session connections
# ------------------------------------------------------------------
def connection_settings() -> dict:
    return resolve_connection_settings({key: value for key, value in st.session_state.items() if key.startswith("demo_")})


def reset_session():
    for key in list(st.session_state):
        if key.startswith(("requirement_editor_", "approve_", "publish_confirm_")):
            del st.session_state[key]
    st.session_state.session_id = None
    st.session_state.ticket_key = None
    st.session_state.iteration = 0
    st.session_state.history = []
    st.session_state.context = {}
    st.session_state.last_saved = []
    st.session_state.workspace_id = uuid.uuid4().hex
    st.session_state.requirement_history = []
    st.session_state.requirement_draft = ""
    st.session_state.final_requirement = ""
    st.session_state.requirement_iteration = 0


def invalidate_approval():
    st.session_state.final_requirement = ""
    st.session_state.history = []
    st.session_state.iteration = 0
    st.session_state.last_saved = []


def requirement_edited(editor_key: str):
    st.session_state.requirement_draft = st.session_state[editor_key]
    invalidate_approval()


def approval_changed(approval_key: str):
    if not st.session_state[approval_key]:
        invalidate_approval()


# ------------------------------------------------------------------
# Parsing + saving generated code
# ------------------------------------------------------------------
def save_generated_files(ticket_key: str, raw_text: str, iteration: int):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", ticket_key):
        raise RuntimeError("Invalid output folder name.")
    ticket_dir = os.path.join(GENERATED_DIR, st.session_state.workspace_id, ticket_key)
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
            m = re.search(r"([A-Za-z0-9_\-/]+(?:\.[A-Za-z0-9_]+)+)", first_line)
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
        <p>Jira Cloud + Confluence + SAP code generation</p>
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

for state_key, default in {
    "workspace_id": uuid.uuid4().hex,
    "requirement_history": [],
    "requirement_draft": "",
    "final_requirement": "",
    "requirement_iteration": 0,
    "context": {},
}.items():
    if state_key not in st.session_state:
        st.session_state[state_key] = default

if shared_mode():
    shared_identity = json.dumps([connection_settings(), sorted(shared_allowlist("TICKETS")),
                                  sorted(shared_allowlist("PAGES"))], sort_keys=True)
    shared_fingerprint = hashlib.sha256(shared_identity.encode()).hexdigest()
    if st.session_state.get("shared_configuration") != shared_fingerprint:
        reset_session()
        st.session_state.shared_configuration = shared_fingerprint
elif "shared_configuration" in st.session_state:
    reset_session()
    del st.session_state["shared_configuration"]


def show_spec(document: str):
    sections = re.split(r"(?m)^##\s+", document)
    if sections[0].strip():
        st.markdown(sections[0])
    for section in sections[1:]:
        heading, _, body = section.partition("\n")
        with st.expander(heading.strip()):
            st.markdown(body)


def show_source(preview: dict):
    ticket = preview.get("ticket", {})
    ticket_key = ticket.get("key") or preview.get("ticket_key", "Ticket")
    summary = ticket.get("summary") or "Requirement"
    with st.expander(f"{ticket_key}: {summary}", expanded=True):
        description = ticket.get("description")
        if isinstance(description, str) and description.strip():
            st.markdown(description)
        else:
            st.info("No ticket description available.")
    for page in preview.get("design_pages", []):
        metadata = page.get("metadata", page)
        content = page.get("content") or metadata.get("content", "")
        if isinstance(content, dict):
            content = content.get("value", "")
        with st.expander(metadata.get("title") or "Linked design", expanded=True):
            if isinstance(content, str) and content.strip():
                st.markdown(content)
            else:
                st.info("No design content available.")


def refine_message(text: str, fetch: bool = False):
    with st.spinner("Preparing requirement specification..."):
        try:
            settings = connection_settings()
            validate_llm_settings(settings)
            context = dict(st.session_state.context)
            ticket = st.session_state.ticket_key or ""
            if fetch and st.session_state.get("source_mode", "Jira / wiki") == "Jira / wiki":
                ticket = st.session_state.get("ticket_input", "").strip().upper()
                context = fetch_context(settings, ticket, st.session_state.get("wiki_page", "").strip())
            elif fetch:
                source = st.session_state.get("pasted_requirement", "").strip()
                if not source:
                    raise RuntimeError("Paste a requirement before summarizing it.")
                context = {"pasted_requirement": source, "notes": "User-provided content; no SAP objects inspected."}
                ticket = ""
            context["current_document"] = "" if fetch else st.session_state.requirement_draft
            history = [] if fetch else list(st.session_state.requirement_history)
            reply = generate_reply(settings, text, history, context,
                                   system_prompt=requirements_prompt(st.session_state.get("review_role", "bsa")))
            st.session_state.context = context
            st.session_state.ticket_key = ticket or None
            st.session_state.requirement_iteration += 1
            st.session_state.requirement_draft = reply
            st.session_state.final_requirement = ""
            st.session_state.requirement_history = history + [
                {"role": "user", "text": text}, {"role": "assistant", "text": reply},
            ]
            st.session_state.history = []
            st.session_state.iteration = 0
            st.session_state.last_saved = []
            st.rerun()
        except (RuntimeError, ValueError) as error:
            st.error(str(error) if isinstance(error, RuntimeError) else "A connection URL is invalid.")


def finalize_requirement(document: str):
    try:
        approval_key = f"approve_{st.session_state.workspace_id}_{st.session_state.requirement_iteration}_" + hashlib.sha256(document.encode()).hexdigest()[:16]
        if not document.strip() or len(document.encode("utf-8")) > 100000:
            raise RuntimeError("Approve a nonempty requirement smaller than 100 KB.")
        if not st.session_state.get(approval_key):
            raise RuntimeError("Approve the current specification before finalizing it.")
        save_generated_files(st.session_state.ticket_key or "requirements", document,
                             st.session_state.requirement_iteration)
        st.session_state.final_requirement = document
        st.session_state.requirement_draft = document
        st.session_state.history = []
        st.session_state.iteration = 0
        st.session_state.last_saved = []
        st.rerun()
    except RuntimeError as error:
        st.error(str(error))
    except OSError:
        st.error("Could not save the specification. Check output storage permissions.")


def send_message(text: str, ticket: str = "", reference: str = ""):
    """Commit a successful reply with its ticket/design and revision history."""
    iteration = st.session_state.iteration + 1
    with st.spinner(f"Thinking (v{iteration})..."):
        try:
            settings = connection_settings()
            validate_llm_settings(settings)
            if not st.session_state.final_requirement:
                raise RuntimeError("Finalize and approve the requirement before code generation.")
            context = dict(st.session_state.get("context", {}))
            context["finalized_requirement"] = st.session_state.final_requirement
            context.pop("current_document", None)
            reply = generate_reply(settings, text, list(st.session_state.history), context,
                                   system_prompt=codegen_prompt())
            folder = ticket or st.session_state.ticket_key or "session"
            saved = save_generated_files(folder, reply, iteration)
            st.session_state.context = context
            st.session_state.ticket_key = ticket or st.session_state.ticket_key
            st.session_state.session_id = "demo"
            st.session_state.iteration = iteration
            st.session_state.history.append({"role": "user", "text": text})
            st.session_state.history.append({"role": "assistant", "text": reply})
            st.session_state.last_saved = saved
            st.rerun()
        except RuntimeError as e:
            st.error(str(e))
        except OSError:
            st.error("Could not save generated files. Check permissions and available disk space.")


with st.sidebar:
    if shared_mode():
        st.markdown("### Shared demo")
    else:
        st.markdown("### Demo Connections")
        st.caption("Session-only credentials. Writes require explicit confirmation.")
        with st.expander("Jira Cloud", expanded=True):
            st.text_input("Jira URL", placeholder="https://your-site.atlassian.net", key="demo_jira_url", on_change=reset_session)
            st.text_input("Jira account email", placeholder="you@example.com", key="demo_jira_email", on_change=reset_session)
            st.text_input("Jira API token", type="password", placeholder="Enter Jira API token", key="demo_jira_token", on_change=reset_session)
        with st.expander("Wiki / Confluence", expanded=True):
            st.text_input("Wiki URL", placeholder="https://your-site.atlassian.net/wiki", key="demo_wiki_url", on_change=reset_session)
            st.text_input("Wiki account email", placeholder="you@example.com", key="demo_wiki_email", on_change=reset_session)
            st.text_input("Wiki API token", type="password", placeholder="Enter Confluence API token", key="demo_wiki_token", on_change=reset_session)
        with st.expander("LLM", expanded=True):
            provider = st.selectbox("LLM provider", ["Anthropic", "OpenAI", "Azure OpenAI", "Google Gemini"], key="demo_llm_provider", on_change=reset_session)
            st.text_input("LLM API token", type="password", placeholder="Enter provider API key", key="demo_llm_token", on_change=reset_session)
            st.text_input("Model / deployment name", placeholder="claude-sonnet-4-5, gpt-4.1 or gemini-3.8-flash", key="demo_llm_model", on_change=reset_session)
            if provider == "Azure OpenAI":
                st.text_input("Azure OpenAI endpoint", placeholder="https://your-resource.openai.azure.com", key="demo_llm_endpoint", on_change=reset_session)
            if st.button("Test LLM (API request)", key="test_llm", width="stretch"):
                try:
                    with st.spinner("Checking LLM..."):
                        generate_reply(connection_settings(), "Reply with OK only.", [], {})
                    st.success("LLM returned text successfully.")
                except RuntimeError as error:
                    st.error(str(error))
        if st.button("Clear connection settings", width="stretch"):
            for connection_key in list(st.session_state):
                if connection_key.startswith("demo_"):
                    del st.session_state[connection_key]
            reset_session()
            st.rerun()

    st.divider()
    if st.button("🔄 New ticket / reset session", width="stretch"):
        reset_session()
        st.rerun()

try:
    validate_llm_settings(connection_settings())
    chat_ready = True
    generation_blocker = ""
except RuntimeError as error:
    chat_ready = False
    generation_blocker = "The owner must configure the server's model connection." if shared_mode() else str(error)
except ValueError:
    chat_ready = False
    generation_blocker = "The LLM endpoint URL is invalid."

requirements_tab, code_tab = st.tabs(["Requirements", "Code generation"])

with requirements_tab:
    st.subheader("Requirements refinement")
    st.markdown("#### 1. Fetch & summarize")
    sources = ["Jira / wiki", "Pasted requirement"] if not shared_mode() or shared_allowlist("TICKETS") else ["Pasted requirement"]
    source_mode = st.segmented_control("Requirement source", sources,
                                       default=sources[0], key="source_mode", on_change=reset_session)
    if source_mode == "Jira / wiki":
        wiki_page = st.text_input(
            "Wiki / Confluence page (optional)",
            placeholder="Published page URL or numeric ID",
            key="wiki_page",
            on_change=reset_session,
        )
        ticket_key = st.text_input("Jira ticket key", placeholder="e.g. KAN-4", key="ticket_input",
                                   on_change=reset_session).strip().upper()
        if st.button("Test Jira / wiki", key="test_atlassian", disabled=not ticket_key, width="stretch"):
            try:
                with st.spinner("Fetching ticket and design through MCP..."):
                    preview = fetch_context(connection_settings(), ticket_key, wiki_page.strip())
                st.success(f"Read {ticket_key} and {len(preview['design_pages'])} design page(s).")
                show_source(preview)
            except RuntimeError as error:
                st.error(str(error))
        try:
            validate_settings(connection_settings(), require_llm=False)
            source_ready = bool(ticket_key)
        except (RuntimeError, ValueError) as error:
            source_ready = False
            st.warning(str(error) if isinstance(error, RuntimeError) else "A source URL is invalid.")
    else:
        pasted = st.text_area("Raw requirement", height=180, key="pasted_requirement", on_change=reset_session)
        source_ready = bool(pasted.strip())
    if not chat_ready:
        st.warning(f"Summarization unavailable: {generation_blocker}")
    if st.button("Fetch & summarize", type="primary", key="summarize", disabled=not (chat_ready and source_ready)):
        refine_message("Prepare a complete developer-ready specification from the supplied requirement. Return the full document, open questions and sources.", fetch=True)

    st.markdown("#### 2. Refine with AI")
    st.selectbox("Reviewing as", ["bsa", "qa", "developer"],
                 format_func=lambda role: {"bsa": "BSA / Product Manager", "qa": "QA", "developer": "Developer"}[role], key="review_role")
    for message in st.session_state.requirement_history:
        with st.chat_message(message["role"]):
            if message["role"] == "assistant":
                show_spec(message["text"])
            else:
                st.markdown(message["text"])
    if not chat_ready:
        st.warning(f"Refinement unavailable: {generation_blocker}")
    elif not st.session_state.requirement_draft and not source_ready:
        st.info("Refinement unavailable: no requirement source or imported specification.")
    refinement = st.chat_input("Refine the requirement", key="requirement_chat",
                               disabled=not (chat_ready and (st.session_state.requirement_draft or source_ready)))
    if refinement:
        refine_message(refinement, fetch=not bool(st.session_state.requirement_draft))

    st.markdown("#### 3. Finalize / edit")
    imported = st.file_uploader("Import a specification", type=["md", "txt"], key="import_spec")
    if imported and st.button("Use imported specification", key="use_import"):
        try:
            if imported.size > 100000:
                raise RuntimeError("The specification exceeds 100 KB.")
            imported_document = imported.getvalue().decode("utf-8")
            if not imported_document.strip():
                raise RuntimeError("The imported specification is empty.")
            reset_session()
            st.session_state.requirement_draft = imported_document
            st.session_state.requirement_iteration = 1
            st.rerun()
        except (UnicodeDecodeError, RuntimeError):
            st.error("Import a UTF-8 markdown specification smaller than 100 KB.")
    if st.session_state.requirement_draft:
        editor_key = f"requirement_editor_{st.session_state.requirement_iteration}"
        document = st.text_area("Requirement document", value=st.session_state.requirement_draft,
                                height=320, key=editor_key, on_change=requirement_edited, args=(editor_key,))
        approval_key = f"approve_{st.session_state.workspace_id}_{st.session_state.requirement_iteration}_" + hashlib.sha256(document.encode()).hexdigest()[:16]
        approved = st.checkbox("I approve this specification for code generation", key=approval_key,
                               on_change=approval_changed, args=(approval_key,))
        if st.button("Finalize requirement", key="finalize", disabled=not approved) and approved:
            finalize_requirement(document)
    if st.session_state.final_requirement:
        st.success("Finalized specification ready for code generation.")
        st.download_button("Download specification", st.session_state.final_requirement,
                           file_name=f"{st.session_state.ticket_key or 'requirement'}_spec.md", mime="text/markdown")
    if st.session_state.final_requirement and not shared_mode():
        with st.expander("Publish finalized requirement"):
            from demo_backend import publish_requirement
            target = st.selectbox("Publish target", ["Jira comment", "Replace Jira description", "New Confluence page", "Update Confluence page"], key="publish_target")
            publish_ticket = st.text_input("Publish Jira ticket", value=st.session_state.ticket_key or "", key="publish_ticket")
            publish_title = st.text_input("Page title", key="publish_title")
            publish_space = st.text_input("Confluence space key", key="publish_space")
            publish_page = st.text_input("Existing page URL / ID", key="publish_page")
            publish_parent = st.text_input("Parent page URL / ID (optional)", key="publish_parent")
            publish_identity = json.dumps([target, publish_ticket, publish_title, publish_space, publish_page,
                                           publish_parent, st.session_state.final_requirement])
            confirm_key = "publish_confirm_" + hashlib.sha256(publish_identity.encode()).hexdigest()[:16]
            confirmed = st.checkbox("I confirm the target and authorize this write", key=confirm_key)
            if st.button("Publish requirement", key="publish", disabled=not confirmed) and confirmed:
                try:
                    with st.spinner("Publishing approved specification..."):
                        publish_requirement(connection_settings(), target, st.session_state.final_requirement,
                                            ticket=publish_ticket.strip().upper(), title=publish_title.strip(),
                                            space=publish_space.strip(), page=publish_page.strip(), parent=publish_parent.strip())
                    st.success("Requirement published successfully.")
                except (RuntimeError, ValueError) as error:
                    st.error(str(error) if isinstance(error, RuntimeError) else "Invalid publish target.")

with code_tab:
    st.subheader("Code generation")
    if not st.session_state.final_requirement:
        st.info("Finalize and approve a specification in Requirements before generating code.")
    else:
        with st.expander("Finalized requirement"):
            show_spec(st.session_state.final_requirement)
    if not chat_ready:
        st.warning(f"Generation unavailable: {generation_blocker}")
    if st.button("✨ Generate code", type="primary", key="generate", disabled=not (chat_ready and st.session_state.final_requirement)):
        send_message("Generate the complete ABAP Cloud objects required by the finalized specification. Preserve scope and report unverified dependencies.")
    for message in st.session_state.history:
        with st.chat_message(message["role"]):
            st.markdown(message["text"])
    code_feedback = st.chat_input("Review or revise generated code", key="code_chat",
                                  disabled=not (chat_ready and st.session_state.history))
    if code_feedback:
        send_message(code_feedback)
    if st.session_state.get("last_saved"):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in st.session_state.last_saved:
                bundle.write(path, arcname=os.path.basename(path))
        st.download_button("Download generated files", archive.getvalue(), file_name="generated_code.zip", mime="application/zip")
        with st.expander("Generated files"):
            for path in st.session_state.last_saved:
                st.text(os.path.basename(path))
