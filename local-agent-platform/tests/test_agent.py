import io
import json
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from src.agent import Agent, parse_text_tool_call
from src.config import load_config
from src.errors import AgentError
from src.logger import EventLogger
from src.main import main
from src.tools.email_tool import EmailTool
from src.tools.registry import ToolRegistry
from src.tools.web_tool import WebTool
from src.tools.inbox_tool import InboxTool
from src.tools.nasa_tool import NasaTool
from src.tools.search_tool import SearchTool

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
        self.registry.register(SearchTool(Mock()))
        self.registry.register(InboxTool(self.config.imap))
        self.registry.register(NasaTool())
        self.output = []
        self.agent = Agent(self.config, self.client, self.registry, self.logger, self.output.append)

    def test_plain_question(self):
        self.client.chat.return_value = FINAL
        self.assertEqual(self.agent.run("What is 2+2?"), "Done")
        self.approval.approve.assert_not_called()
        self.assertEqual(self.client.chat.call_count, 1)
        # search_web is offered by default (search_allowed) but not required for stable facts.
        definitions = self.client.chat.call_args.args[1]
        self.assertEqual([d["function"]["name"] for d in definitions], ["search_web"])

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
        with self.assertRaises(AgentError) as caught:
            self.agent.run("What is the capital of France? Do not compose or send an email.")
        self.assertEqual(caught.exception.code, "unresolved_tool_error")
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
        with self.assertRaises(AgentError):
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

    def test_inbox_and_nasa_results_reach_model(self):
        for name, args, task, result in (
            ("read_email", {"limit": 1}, "Summarize my latest email", {
                "status": "read", "message": "Read one message.",
                "messages": [{"subject": "Report", "untrusted_body": "The report is ready."}]}),
            ("nasa_neo_feed", {"start_date": "2015-09-07", "end_date": "2015-09-08"},
                "Get NASA feed for 2015-09-07 to 2015-09-08", {
                "status": "read", "message": "NASA data retrieved.", "total_count": 21})):
            with self.subTest(tool=name), patch.object(self.registry.tools[name], "execute", return_value=result):
                self.client.chat.side_effect = [{"role": "assistant", "content": "", "tool_calls": [
                    {"function": {"name": name, "arguments": args}}]}, FINAL]
                self.agent.run(task)
                messages = self.client.chat.call_args.args[0]
                returned = next(message for message in messages if message["role"] == "tool")
                self.assertEqual(returned["tool_name"], name)
                self.assertEqual(json.loads(returned["content"]), result)
                self.approval.approve.assert_not_called()

    def test_failed_api_cannot_be_followed_by_invented_success(self):
        call = {"role": "assistant", "content": "", "tool_calls": [{"function": {
            "name": "nasa_neo_feed", "arguments": {"start_date": "bad", "end_date": "bad"}}}]}
        self.client.chat.side_effect = [call, {"role": "assistant", "content": "NASA found 999 objects."}]
        with self.assertRaises(AgentError) as caught:
            self.agent.run("Get NASA asteroid data")
        self.assertEqual(caught.exception.code, "unresolved_tool_error")
        self.assertNotIn("999", str(caught.exception))

    def test_corrected_api_call_clears_previous_failure(self):
        bad = {"role": "assistant", "content": "", "tool_calls": [{"function": {
            "name": "nasa_neo_feed", "arguments": {"start_date": "bad", "end_date": "bad"}}}]}
        good = {"role": "assistant", "content": "", "tool_calls": [{"function": {
            "name": "nasa_neo_feed", "arguments": {"start_date": "2015-09-07", "end_date": "2015-09-08"}}}]}
        self.client.chat.side_effect = [bad, good, FINAL]
        with patch.object(self.registry.tools["nasa_neo_feed"], "execute", return_value={"status": "read", "message": "NASA data retrieved."}):
            self.assertEqual(self.agent.run("Get NASA asteroid data"), "Done")

    def test_invented_answer_without_required_call_is_blocked(self):
        for task in ("Use nasa_neo_feed for 2015-09-07 through 2015-09-08", "Read my latest 5 emails"):
            self.client.chat.return_value = {"role": "assistant", "content": "Invented answer"}
            self.client.chat.reset_mock()
            with self.subTest(task=task), self.assertRaises(AgentError) as caught:
                self.agent.run(task)
            self.assertEqual(caught.exception.code, "required_tool_not_called")
            self.assertEqual(self.client.chat.call_count, 2)

    def test_reminder_allows_real_tool_call(self):
        self.client.chat.side_effect = [FINAL,
            {"role": "assistant", "content": "", "tool_calls": [{"function": {
                "name": "nasa_neo_feed", "arguments": {"start_date": "2015-09-07", "end_date": "2015-09-08"}}}]}, FINAL]
        with patch.object(self.registry.tools["nasa_neo_feed"], "execute", return_value={"status": "read", "message": "NASA data retrieved."}):
            self.assertEqual(self.agent.run("NASA data for 2015-09-07 to 2015-09-08"), "Done")

    def test_text_tool_call_is_recovered_and_dispatched(self):
        self.client.chat.side_effect = [
            {"role": "assistant", "content":
                'assistant\n\n{"name": "nasa_neo_feed", "parameters": {"start_date": "2015-09-07", "end_date": "2015-09-08"}}'},
            FINAL]
        with patch.object(self.registry.tools["nasa_neo_feed"], "execute",
                          return_value={"status": "read", "message": "NASA data retrieved."}):
            self.assertEqual(self.agent.run("NASA data for 2015-09-07 to 2015-09-08"), "Done")
        events = [json.loads(line)["event"] for line in self.logs.getvalue().splitlines()]
        self.assertIn("text_tool_call_recovered", events)

    def test_prose_resembling_json_is_not_treated_as_a_tool_call(self):
        content = 'The config looks like {"name": "example", "value": 1} in the docs.'
        self.client.chat.return_value = {"role": "assistant", "content": content}
        self.assertEqual(self.agent.run("Explain this config"), content)
        self.approval.approve.assert_not_called()

    def test_parse_text_tool_call_shape(self):
        offered = {"x"}
        self.assertIsNone(parse_text_tool_call("", offered))
        self.assertIsNone(parse_text_tool_call("Just a plain answer.", offered))
        self.assertIsNone(parse_text_tool_call('{"name": "x"}', offered))
        self.assertIsNone(parse_text_tool_call('{"name": "x", "parameters": {}, "extra": 1}', offered))
        self.assertIsNone(parse_text_tool_call('{"name": 1, "parameters": {}}', offered))
        self.assertIsNone(parse_text_tool_call('{"name": "x", "parameters": "not a dict"}', offered))
        self.assertIsNone(parse_text_tool_call('prefix {"name": "x", "parameters": {}} suffix', offered))
        self.assertIsNone(parse_text_tool_call('{"name": "x", "parameters": {}}', frozenset()))
        self.assertEqual(parse_text_tool_call('{"name": "x", "parameters": {"a": 1}}', offered),
                         {"function": {"name": "x", "arguments": {"a": 1}}})
        self.assertEqual(parse_text_tool_call('assistant\n\n{"name": "x", "arguments": {"a": 1}}', offered),
                         {"function": {"name": "x", "arguments": {"a": 1}}})

    def test_hallucinated_call_to_unoffered_tool_falls_back_to_reminder(self):
        # read_webpage isn't offered yet (no search happened this task), so a
        # hallucinated text call to it must not be dispatched at all; it should
        # fall through to the normal missing-required-tool reminder instead.
        self.client.chat.return_value = {"role": "assistant",
            "content": '{"name": "read_webpage", "parameters": {"url": "https://example.com/"}}'}
        with patch.object(self.registry, "dispatch", wraps=self.registry.dispatch) as dispatch:
            with self.assertRaises(AgentError) as caught:
                self.agent.run("What is the latest news?")
        self.assertEqual(caught.exception.code, "required_tool_not_called")
        self.assertEqual(self.client.chat.call_count, 2)
        dispatch.assert_not_called()

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
