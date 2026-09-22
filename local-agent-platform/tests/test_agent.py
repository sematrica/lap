import io
import json
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from src.agent import Agent
from src.config import load_config
from src.errors import AgentError
from src.logger import EventLogger
from src.main import main
from src.tools.email_tool import EmailTool
from src.tools.registry import ToolRegistry
from src.tools.web_tool import WebTool

EMAIL = {"to": "person@example.com", "subject": "Hello", "body": "Report ready."}
CALL = {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "send_email", "arguments": EMAIL}}]}
FINAL = {"role": "assistant", "content": "Done"}


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(env={})
        self.logs = io.StringIO()
        self.logger = EventLogger("agent-01", self.logs)
        self.client = Mock()
        self.approval = Mock()
        self.approval.approve.return_value = True
        self.registry = ToolRegistry(self.config.tools, self.config.name, self.approval, self.logger)
        self.registry.register(EmailTool(self.config.smtp, True, self.logger))
        self.registry.register(WebTool())
        self.output = []
        self.agent = Agent(self.config, self.client, self.registry, self.logger, self.output.append)

    def test_plain_question(self):
        self.client.chat.return_value = FINAL
        self.assertEqual(self.agent.run("What is 2+2?"), "Done")
        self.approval.approve.assert_not_called()
        self.assertEqual(self.client.chat.call_count, 1)
        self.assertEqual(self.client.chat.call_args.args[1], [])

    @patch("src.tools.email_tool.smtplib.SMTP")
    def test_tool_round_trip_and_denial(self, smtp):
        for approved, status in ((True, "dry_run"), (False, "rejected")):
            self.approval.approve.return_value = approved
            self.client.chat.side_effect = [CALL, FINAL]
            self.agent.run("Please send the email to person@example.com.")
            messages = self.client.chat.call_args.args[0]
            result = next(msg for msg in messages if msg["role"] == "tool")
            self.assertEqual(result["tool_name"], "send_email")
            self.assertEqual(json.loads(result["content"])["status"], status)
            self.assertTrue(self.output)
        smtp.assert_not_called()

    @patch("src.tools.email_tool.smtplib.SMTP")
    def test_unsolicited_email_cannot_reach_approval(self, smtp):
        self.client.chat.side_effect = [CALL, {"role": "assistant", "content": "Paris."}]
        answer = self.agent.run("What is the capital of France? Do not compose or send an email.")
        self.assertEqual(answer, "Paris.")
        self.approval.approve.assert_not_called()
        smtp.assert_not_called()
        for call in self.client.chat.call_args_list:
            self.assertEqual(call.args[1], [])
        messages = self.client.chat.call_args.args[0]
        result = next(msg for msg in messages if msg["role"] == "tool")
        self.assertEqual(json.loads(result["content"])["code"], "recipient_not_provided")

    @patch("src.tools.email_tool.smtplib.SMTP")
    def test_invented_recipient_cannot_reach_approval(self, smtp):
        self.client.chat.side_effect = [CALL, FINAL]
        self.agent.run("Send a message to someone-else@example.com.")
        self.approval.approve.assert_not_called()
        smtp.assert_not_called()

    @patch("src.tools.web_tool.fetch_once")
    @patch("src.tools.email_tool.smtplib.SMTP")
    def test_webpage_result_reaches_model_without_email(self, smtp, fetch):
        fetch.return_value = (200, "text/html", "utf-8", b"<p>Example domain.</p>")
        self.client.chat.side_effect = [{"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_webpage", "arguments": {"url": "https://example.com/"}}}]},
            {"role": "assistant", "content": "Example domain. Source: https://example.com/"}]
        answer = self.agent.run("Read https://example.com/ and summarize it.")
        self.assertIn("https://example.com/", answer)
        messages = self.client.chat.call_args.args[0]
        result = json.loads(next(msg["content"] for msg in messages if msg["role"] == "tool"))
        self.assertEqual(result["untrusted_text"], "Example domain.")
        self.assertEqual(result["source_url"], "https://example.com/")
        self.assertIn("untrusted source data", messages[0]["content"])
        self.approval.approve.assert_not_called()
        smtp.assert_not_called()

    def test_loop_is_bounded(self):
        self.agent.config = replace(self.config, max_iterations=2)
        self.client.chat.return_value = {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "unknown", "arguments": {}}}]}
        with self.assertRaises(AgentError) as caught:
            self.agent.run("test")
        self.assertEqual(caught.exception.code, "iteration_limit")
        self.assertEqual(self.client.chat.call_count, 2)

    def test_logs_are_structured_and_omit_task(self):
        self.client.chat.return_value = FINAL
        self.agent.run("private task content")
        events = [json.loads(line) for line in self.logs.getvalue().splitlines()]
        self.assertEqual(events[-1]["event"], "agent_completed")
        for event in events:
            self.assertTrue({"timestamp", "level", "agent", "event"} <= event.keys())
        self.assertNotIn("private task content", self.logs.getvalue())

    @patch("src.main.OllamaClient")
    def test_cli_check_and_startup_error(self, client_class):
        with patch("sys.stdout", new_callable=io.StringIO), patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(main(["--check"]), 0)
            client_class.return_value.chat.assert_not_called()
            client_class.return_value.close.assert_called_once()
            client_class.return_value.verify.side_effect = AgentError("llm_connection_error", "Cannot connect")
            self.assertEqual(main(["--check"]), 1)

    @patch("src.main.OllamaClient")
    def test_cli_recovers_after_task_error(self, client_class):
        client_class.return_value.chat.side_effect = [AgentError("llm_timeout", "Timed out"), FINAL]
        with patch("builtins.input", side_effect=["first", "second", "exit"]), patch("sys.stdout", new_callable=io.StringIO) as output, patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(main([]), 0)
            self.assertIn("Timed out", output.getvalue())
            self.assertIn("Done", output.getvalue())
