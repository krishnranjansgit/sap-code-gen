import asyncio
import json
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from streamlit.testing.v1 import AppTest

import demo_backend as backend
import prompts


SETTINGS = {
    "demo_jira_url": "https://demo.atlassian.net",
    "demo_jira_email": "demo@example.com",
    "demo_jira_token": "jira-test-secret",
    "demo_wiki_url": "https://demo.atlassian.net/wiki",
    "demo_wiki_email": "wiki@example.com",
    "demo_wiki_token": "wiki-test-secret",
    "demo_llm_provider": "OpenAI",
    "demo_llm_token": "llm-test-secret",
    "demo_llm_model": "gpt-4.1",
}
REPLY = "## Ticket Summary\nDemo\n## Classification\nABAP\n## Code\n```abap\n* Z_DEMO.clas.abap\nCLASS z_demo DEFINITION PUBLIC.\nENDCLASS.\n```\n## Notes\nNot activated."


class PromptTests(unittest.TestCase):
    def test_requirements_include_shared_security_and_reference_persona(self):
        for role, focus in prompts.REQUIREMENTS_ROLE_FOCUS.items():
            with self.subTest(role=role):
                system_prompt = prompts.requirements_prompt(role)
                self.assertTrue(system_prompt.startswith(prompts.BASE_SECURITY_SYSTEM_PROMPT + "\n\n"))
                self.assertIn(prompts.SAP_REQUIREMENTS_PERSONA, system_prompt)
                self.assertIn(focus, system_prompt)
                self.assertTrue(system_prompt.endswith(prompts.EXTERNAL_CLOUD_POLICY))

    def test_codegen_includes_shared_security_and_reference_persona(self):
        system_prompt = prompts.codegen_prompt()
        self.assertTrue(system_prompt.startswith(prompts.BASE_SECURITY_SYSTEM_PROMPT + "\n\n"))
        self.assertIn(prompts.SAP_CODE_GEN_PERSONA, system_prompt)
        self.assertIn(prompts.EXTERNAL_CLOUD_POLICY, system_prompt)
        self.assertTrue(system_prompt.endswith(prompts.CODE_OUTPUT_POLICY))


class BackendTests(unittest.TestCase):
    def test_connector_launcher_preserves_local_pin_and_container_install(self):
        with patch.dict("os.environ", {"MCP_ATLASSIAN_EXECUTABLE": ""}), patch.object(backend.shutil, "which", return_value="/test/uvx"):
            self.assertEqual(backend.atlassian_command(), ("/test/uvx", ["mcp-atlassian==0.24.6"]))
        with patch.dict("os.environ", {"MCP_ATLASSIAN_EXECUTABLE": "/opt/atlassian/bin/mcp-atlassian"}):
            self.assertEqual(backend.atlassian_command(), ("/opt/atlassian/bin/mcp-atlassian", []))

    def test_publish_exposes_one_write_tool_and_no_model_credentials(self):
        environments = []
        session = MagicMock()
        session.initialize = AsyncMock()
        tool = SimpleNamespace(name="jira_add_comment", inputSchema={"properties": {"issue_key": {}, "body": {}}})
        session.list_tools = AsyncMock(return_value=SimpleNamespace(tools=[tool]))
        session.call_tool = AsyncMock(return_value=SimpleNamespace(isError=False, content=[SimpleNamespace(type="text", text='{"success":true}')]))

        @asynccontextmanager
        async def transport(parameters, **keywords):
            environments.append(parameters.env)
            yield (None, None)

        @asynccontextmanager
        async def client(*arguments, **keywords):
            yield session

        with patch.object(backend, "stdio_client", transport), patch.object(backend, "ClientSession", client), patch.object(backend, "atlassian_command", return_value=("/test/connector", [])):
            backend.publish_requirement(SETTINGS, "Jira comment", "Approved spec", ticket="KAN-4")
        self.assertEqual(environments[0]["READ_ONLY_MODE"], "false")
        self.assertEqual(environments[0]["ENABLED_TOOLS"], "jira_add_comment")
        self.assertNotIn(SETTINGS["demo_llm_token"], json.dumps(environments))
        session.call_tool.assert_awaited_once_with("jira_add_comment", {"issue_key": "KAN-4", "body": "Approved spec"})
        self.assertEqual(backend.connector_environment(SETTINGS)["READ_ONLY_MODE"], "true")

    def test_credentials_are_connector_specific(self):
        with patch.dict("os.environ", {"JIRA_PERSONAL_TOKEN": "legacy-secret"}):
            environment = backend.connector_environment(SETTINGS)
        self.assertEqual(environment["READ_ONLY_MODE"], "true")
        self.assertEqual(environment["JIRA_API_TOKEN"], SETTINGS["demo_jira_token"])
        self.assertNotIn("legacy-secret", json.dumps(environment))
        self.assertNotIn(SETTINGS["demo_llm_token"], json.dumps(environment))
        self.assertEqual(set(environment["ENABLED_TOOLS"].split(",")), backend.ATLASSIAN_TOOLS)

    def test_trusted_urls_and_pages(self):
        self.assertEqual(backend.page_id("https://demo.atlassian.net/wiki/spaces/SBDD/pages/425985/Design", SETTINGS["demo_wiki_url"]), "425985")
        self.assertEqual(backend.linked_pages({"content": {"href": "https://demo.atlassian.net/wiki/spaces/SBDD/pages/425985"}}, SETTINGS["demo_wiki_url"]), ["425985"])
        for address in ("http://demo.atlassian.net", "https://demo.atlassian.net.evil.test", "https://user:secret@demo.atlassian.net"):
            with self.assertRaises(RuntimeError):
                backend.cloud_url(address, "Jira")
        with self.assertRaises(RuntimeError):
            backend.page_id("https://other.atlassian.net/wiki/pages/425985", SETTINGS["demo_wiki_url"])

    def test_context_uses_discovered_schema_and_follows_design(self):
        properties = {key: {} for key in ("issue_key", "fields", "comment_limit", "update_history", "include")}
        tools = [SimpleNamespace(name="jira_get_issue", inputSchema={"properties": properties}),
                 SimpleNamespace(name="confluence_get_page", inputSchema={"properties": {key: {} for key in ("page_id", "include_metadata", "convert_to_markdown")}})]
        session = MagicMock()
        session.initialize = AsyncMock()
        session.list_tools = AsyncMock(return_value=SimpleNamespace(tools=tools))
        payloads = [{"key": "KAN-4", "summary": "Demo", "description": "https://demo.atlassian.net/wiki/spaces/SBDD/pages/425985"},
                    {"metadata": {"content": "Five synthetic orders"}}]
        session.call_tool = AsyncMock(side_effect=[SimpleNamespace(isError=False, content=[SimpleNamespace(type="text", text=json.dumps(payload))]) for payload in payloads])

        @asynccontextmanager
        async def transport(*arguments, **keywords):
            yield (None, None)

        @asynccontextmanager
        async def client(*arguments, **keywords):
            yield session

        with patch.object(backend, "stdio_client", transport), patch.object(backend, "ClientSession", client), patch.object(backend.shutil, "which", return_value="/test/uvx"):
            context = backend.fetch_context(SETTINGS, "KAN-4")
        self.assertEqual(len(context["design_pages"]), 1)
        calls = session.call_tool.call_args_list
        self.assertFalse(calls[0].args[1]["update_history"])
        self.assertEqual(calls[1].args[1]["page_id"], "425985")

    def test_tool_error_payload_is_not_design_context(self):
        session = SimpleNamespace(call_tool=AsyncMock(return_value=SimpleNamespace(isError=False, content=[SimpleNamespace(type="text", text='{"error":"secret-token"}')])))
        tools = {"confluence_get_page": SimpleNamespace(inputSchema={"properties": {"page_id": {}}})}
        with self.assertRaises(RuntimeError) as raised:
            asyncio.run(backend.call_read_tool(session, tools, "confluence_get_page", {"page_id": "1"}))
        self.assertNotIn("secret-token", str(raised.exception))

    def test_openai_reply_keeps_history_not_credentials(self):
        with patch("openai.OpenAI") as factory:
            client = factory.return_value
            client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=REPLY))])
            result = backend.generate_reply(SETTINGS, "Revise", [{"role": "assistant", "text": "previous code"}], {"ticket_key": "KAN-4"})
            messages = client.chat.completions.create.call_args.kwargs["messages"]
        self.assertEqual(result, REPLY)
        self.assertIn("previous code", json.dumps(messages))
        for key in ("demo_jira_token", "demo_wiki_token", "demo_llm_token"):
            self.assertNotIn(SETTINGS[key], json.dumps(messages))

    def test_workflow_prompt_is_separate_from_retrieved_content(self):
        with patch("openai.OpenAI") as factory:
            client = factory.return_value
            client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=REPLY))])
            backend.generate_reply(SETTINGS, "Refine", [], {"ticket": "Reference data"}, system_prompt="Requirements persona")
            messages = client.chat.completions.create.call_args.kwargs["messages"]
        self.assertEqual(messages[0], {"role": "system", "content": "Requirements persona"})
        self.assertIn("Reference data", messages[1]["content"])

    def test_llm_independent_and_errors_are_sanitized(self):
        settings = {key: value for key, value in SETTINGS.items() if key.startswith("demo_llm_")}
        with patch("openai.OpenAI", side_effect=ValueError("llm-test-secret")):
            with self.assertRaises(RuntimeError) as raised:
                backend.generate_reply(settings, "test", [], {})
        self.assertNotIn("llm-test-secret", str(raised.exception))

    def test_anthropic_provider_and_truncated_output(self):
        settings = {**SETTINGS, "demo_llm_provider": "Anthropic", "demo_llm_model": "claude-sonnet-4-5"}
        with patch("anthropic.Anthropic") as factory:
            client = factory.return_value.__enter__.return_value
            client.messages.create.return_value = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=REPLY)])
            self.assertEqual(backend.generate_reply(settings, "Generate", [], {}), REPLY)
            self.assertEqual(client.messages.create.call_args.kwargs["model"], settings["demo_llm_model"])
            client.messages.create.return_value.stop_reason = "max_tokens"
            with self.assertRaisesRegex(RuntimeError, "exceeded"):
                backend.generate_reply(settings, "Generate", [], {})

    def test_azure_provider_uses_explicit_resource(self):
        settings = {**SETTINGS, "demo_llm_provider": "Azure OpenAI", "demo_llm_endpoint": "https://demo.openai.azure.com"}
        with patch("openai.AzureOpenAI") as factory:
            client = factory.return_value
            client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=REPLY))])
            self.assertEqual(backend.generate_reply(settings, "Generate", [], {}), REPLY)
            self.assertEqual(factory.call_args.kwargs["azure_endpoint"], settings["demo_llm_endpoint"])
            client.chat.completions.create.return_value.choices[0].finish_reason = "length"
            with self.assertRaisesRegex(RuntimeError, "exceeded"):
                backend.generate_reply(settings, "Generate", [], {})

    def test_google_provider_keeps_prompts_and_uses_explicit_endpoint(self):
        settings = {**SETTINGS, "demo_llm_provider": "Google Gemini", "demo_llm_model": "gemini-3.8-flash",
                    "demo_llm_endpoint": "https://untrusted.example", "demo_llm_token": "google-test-secret"}
        with patch("openai.OpenAI") as factory:
            client = factory.return_value
            response = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=REPLY))])
            client.chat.completions.create.return_value = response
            self.assertEqual(backend.generate_reply(settings, "Refine", [{"role": "assistant", "text": "previous draft"}],
                                                   {"ticket_key": "KAN-4"}, system_prompt="Requirements persona"), REPLY)
            self.assertEqual(factory.call_args.kwargs["base_url"], "https://generativelanguage.googleapis.com/v1beta/openai/")
            self.assertEqual(factory.call_args.kwargs["api_key"], settings["demo_llm_token"])
            self.assertEqual(factory.call_args.kwargs["max_retries"], 0)
            request = client.chat.completions.create.call_args.kwargs
            self.assertEqual(request["model"], settings["demo_llm_model"])
            self.assertEqual(request["messages"][0], {"role": "system", "content": "Requirements persona"})
            self.assertIn("previous draft", json.dumps(request["messages"]))
            for key in ("demo_jira_token", "demo_wiki_token", "demo_llm_token"):
                self.assertNotIn(settings[key], json.dumps(request["messages"]))
            response.choices[0].finish_reason = "length"
            with self.assertRaisesRegex(RuntimeError, "exceeded"):
                backend.generate_reply(settings, "Generate", [], {})
            response.choices[0].finish_reason = "stop"
            response.choices[0].message.content = ""
            with self.assertRaisesRegex(RuntimeError, "no text"):
                backend.generate_reply(settings, "Generate", [], {})

    def test_google_rate_limit_error_is_sanitized(self):
        from openai import RateLimitError
        import httpx

        settings = {**SETTINGS, "demo_llm_provider": "Google Gemini", "demo_llm_model": "gemini-3.8-flash"}
        response = httpx.Response(429, request=httpx.Request("POST", "https://generativelanguage.googleapis.com"))
        with patch("openai.OpenAI") as factory:
            factory.return_value.chat.completions.create.side_effect = RateLimitError("llm-test-secret", response=response, body=None)
            with self.assertRaisesRegex(RuntimeError, "HTTP 429") as raised:
                backend.generate_reply(settings, "Generate", [], {})
        self.assertNotIn("llm-test-secret", str(raised.exception))
        for missing in ("demo_llm_token", "demo_llm_model"):
            with self.assertRaisesRegex(RuntimeError, "API key and model"):
                backend.validate_llm_settings({**settings, missing: ""})

    def test_publish_requires_explicit_separate_destination(self):
        name, arguments = backend.publication_parameters(SETTINGS, "Jira comment", "Approved spec", ticket="KAN-4")
        self.assertEqual(name, "jira_add_comment")
        self.assertEqual(arguments["body"], "Approved spec")
        with self.assertRaises(RuntimeError):
            backend.publication_parameters(SETTINGS, "Update Confluence page", "Approved spec", title="Design")
        name, arguments = backend.publication_parameters(SETTINGS, "New Confluence page", "Approved spec", title="Design", space="SBDD", parent="425985")
        self.assertEqual(name, "confluence_create_page")
        self.assertEqual(arguments["parent_id"], "425985")
        with self.assertRaises(RuntimeError):
            backend.publication_parameters(SETTINGS, "New Confluence page", "Approved spec", title="Design", space="A display name")

class DemoUITests(unittest.TestCase):
    def configured_app(self, output_directory=None):
        if output_directory:
            source = Path("app.py").read_text().replace(
                'GENERATED_DIR = os.path.join(PROJECT_DIR, "generated")',
                f"GENERATED_DIR = {output_directory!r}",
            )
            app = AppTest.from_string(source).run()
        else:
            app = AppTest.from_file("app.py").run()
        for key, value in SETTINGS.items():
            if key != "demo_llm_provider":
                app.text_input(key=key).set_value(value)
        app.selectbox(key="demo_llm_provider").select("OpenAI")
        app.text_input(key="ticket_input").set_value("KAN-4")
        return app.run()

    def finalize(self, app):
        next(checkbox for checkbox in app.checkbox if "approve this specification" in checkbox.label).check().run()
        app.button(key="finalize").click().run()
        self.assertFalse(app.exception)

    def test_sap_connection_controls_are_absent(self):
        app = self.configured_app()
        self.assertFalse(app.exception)
        self.assertFalse(any("SAP BTP" in expander.label for expander in app.expander))
        self.assertFalse(any("SAP BTP" in button.label for button in app.button))
        self.assertFalse(any(field.key.startswith("demo_btp_") for field in app.text_input))

    def test_google_settings_enable_refinement_and_invalidate_approval(self):
        with patch.object(backend, "generate_reply", return_value=REPLY) as generate:
            app = self.configured_app()
            app.selectbox(key="demo_llm_provider").select("Google Gemini").run()
            app.text_input(key="demo_llm_model").set_value("gemini-3.8-flash").run()
            token = app.text_input(key="demo_llm_token")
            self.assertEqual(token.value, SETTINGS["demo_llm_token"])
            self.assertEqual(token.proto.DESCRIPTOR.fields_by_name["type"].enum_type.values_by_number[token.proto.type].name, "PASSWORD")
            app.button(key="test_llm").click().run()
            self.assertEqual(generate.call_args.args[0]["demo_llm_provider"], "Google Gemini")
            app.session_state["requirement_draft"] = "## Requirement\nSynthetic scope"
            app.run()
            self.assertFalse(app.chat_input(key="requirement_chat").disabled)
            app.chat_input(key="requirement_chat").set_value("Specify error cases").run()
            self.assertEqual(generate.call_args.args[0]["demo_llm_model"], "gemini-3.8-flash")
            self.finalize(app)
            self.assertFalse(app.button(key="generate").disabled)
            app.selectbox(key="demo_llm_provider").select("OpenAI").run()
            self.assertTrue(app.button(key="generate").disabled)
            self.assertFalse(app.exception)

    def test_generation_refinement_and_reset(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(backend, "fetch_context", return_value={"ticket_key": "KAN-4"}) as fetch, patch.object(backend, "generate_reply", return_value=REPLY) as generate:
            histories = []

            def respond(settings, prompt, history, context, **keywords):
                histories.append(list(history))
                return REPLY

            generate.side_effect = respond
            app = self.configured_app(directory)
            self.assertTrue(app.button(key="generate").disabled)
            app.button(key="summarize").click().run()
            app.chat_input(key="requirement_chat").set_value("Specify error cases").run()
            editor = next(field for field in app.text_area if field.label == "Requirement document")
            editor.set_value("## Requirement\nManually approved synthetic-data scope").run()
            self.finalize(app)
            app.button(key="generate").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["iteration"], 1)
            self.assertTrue(list(Path(directory).rglob("v1_Z_DEMO.clas.abap")))
            self.assertEqual(generate.call_args.args[3]["finalized_requirement"], "## Requirement\nManually approved synthetic-data scope")
            app.chat_input(key="code_chat").set_value("Change the status").run()
            self.assertEqual(app.session_state["iteration"], 2)
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual([len(history) for history in histories], [0, 2, 0, 2])
            self.assertEqual(len(app.session_state["requirement_history"]), 4)
            editor = next(field for field in app.text_area if field.label == "Requirement document")
            editor.set_value("Changed scope").run()
            self.assertEqual(app.session_state["final_requirement"], "")
            self.assertTrue(app.button(key="generate").disabled)
            self.assertEqual(app.session_state["last_saved"], [])
            app.text_input(key="demo_jira_token").set_value("changed-test-secret").run()
            self.assertEqual(app.session_state["history"], [])
            self.assertEqual(app.session_state["last_saved"], [])

    def test_connection_preview_is_readable_and_initial_refinement_creates_spec(self):
        context = {
            "ticket_key": "KAN-4",
            "ticket": {"summary": "Synthetic demo", "description": "Print five synthetic orders.", "remote_links": [{"id": 10000}]},
            "design_pages": [{"metadata": {"title": "Sales order design", "content": {"value": "## Scope\nFive orders in the console.", "format": "markdown"}}}],
        }
        specification = "## Requirement\nFive synthetic orders.\n## Acceptance Criteria\nPrint all five orders."
        with patch.object(backend, "fetch_context", return_value=context) as fetch, patch.object(backend, "generate_reply", return_value=specification) as generate:
            app = self.configured_app()
            self.assertFalse(app.chat_input(key="requirement_chat").disabled)
            app.button(key="test_atlassian").click().run()
            self.assertFalse(app.exception)
            preview = next(expander for expander in app.expander if expander.label == "KAN-4: Synthetic demo")
            self.assertTrue(preview.proto.expanded)
            self.assertTrue(any(expander.label == "Sales order design" for expander in app.expander))
            text = " ".join(element.value for element in app.markdown)
            self.assertIn("Print five synthetic orders.", text)
            self.assertIn("Five orders in the console.", text)
            self.assertNotIn("remote_links", text)
            self.assertEqual(app.get("json"), [])
            self.assertEqual(app.session_state["requirement_draft"], "")
            generate.assert_not_called()
            app.chat_input(key="requirement_chat").set_value("Create the specification and include error cases").run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["requirement_draft"], specification)
            self.assertEqual(generate.call_args.args[3]["ticket_key"], "KAN-4")
            self.assertIn("Acceptance Criteria", " ".join(expander.label for expander in app.expander))
            self.assertEqual(len(app.session_state["requirement_history"]), 2)
            self.assertEqual(fetch.call_count, 2)
            self.assertTrue(app.button(key="generate").disabled)

    def test_disabled_generation_explains_missing_model(self):
        app = self.configured_app()
        app.text_input(key="demo_llm_model").set_value("").run()
        self.assertFalse(app.exception)
        self.assertTrue(next(button for button in app.button if "Generate code" in button.label).disabled)
        self.assertTrue(any("LLM API key and model/deployment name" in warning.value for warning in app.warning))
        app.text_input(key="demo_llm_model").set_value("gpt-4.1").run()
        self.assertTrue(next(button for button in app.button if "Generate code" in button.label).disabled)
        self.assertFalse(app.button(key="summarize").disabled)
        self.assertFalse(any("Generation unavailable" in warning.value for warning in app.warning))

    def test_disabled_generation_explains_invalid_wiki_url(self):
        app = self.configured_app()
        app.text_input(key="demo_wiki_url").set_value("https://demo.atlassian.net").run()
        self.assertFalse(app.exception)
        self.assertTrue(next(button for button in app.button if "Generate code" in button.label).disabled)
        self.assertTrue(any("Wiki: use the base URL ending in '/wiki'" in warning.value for warning in app.warning))

    def test_failure_does_not_commit_and_clear_masks_tokens(self):
        with patch.object(backend, "fetch_context", side_effect=RuntimeError("Permission denied")):
            app = self.configured_app()
            app.button(key="summarize").click().run()
        self.assertFalse(app.exception)
        self.assertIsNone(app.session_state["ticket_key"])
        self.assertEqual(app.session_state["iteration"], 0)
        self.assertEqual(app.session_state["history"], [])
        for key in ("demo_jira_token", "demo_wiki_token", "demo_llm_token"):
            field = app.text_input(key=key)
            self.assertEqual(field.proto.type, 1)
        next(button for button in app.button if button.label == "Clear connection settings").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.text_input(key="demo_llm_token").value, "")
        self.assertTrue(app.chat_input[0].disabled)

    def test_pasted_requirement_needs_only_llm_and_sessions_are_isolated(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(backend, "fetch_context") as fetch, patch.object(backend, "generate_reply", return_value="## Requirement\nSynthetic demo"):
            app = self.configured_app(directory)
            other = self.configured_app(directory)
            self.assertNotEqual(app.session_state["workspace_id"], other.session_state["workspace_id"])
            app.segmented_control(key="source_mode").set_value("Pasted requirement").run()
            app.text_area(key="pasted_requirement").set_value("Synthetic BTP example").run()
            app.text_input(key="demo_jira_token").set_value("").run()
            app.button(key="summarize").click().run()
            self.assertFalse(app.exception)
            fetch.assert_not_called()
            self.finalize(app)
            self.assertIsNone(app.session_state["ticket_key"])
            app.chat_input(key="requirement_chat").set_value("Add test cases").run()
            self.assertEqual(app.session_state["final_requirement"], "")
            self.assertTrue(app.button(key="generate").disabled)

    def test_publish_confirmation_is_invalidated_by_destination_change(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(backend, "fetch_context", return_value={}), patch.object(backend, "generate_reply", return_value="## Requirement\nSynthetic demo"), patch.object(backend, "publish_requirement") as publish:
            app = self.configured_app(directory)
            app.button(key="summarize").click().run()
            self.finalize(app)
            self.assertTrue(app.button(key="publish").disabled)
            next(checkbox for checkbox in app.checkbox if "authorize this write" in checkbox.label).check().run()
            app.text_input(key="publish_ticket").set_value("KAN-5").run()
            self.assertTrue(app.button(key="publish").disabled)
            publish.assert_not_called()
            next(checkbox for checkbox in app.checkbox if "authorize this write" in checkbox.label).check().run()
            app.button(key="publish").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(publish.call_args.kwargs["ticket"], "KAN-5")


if __name__ == "__main__":
    unittest.main()