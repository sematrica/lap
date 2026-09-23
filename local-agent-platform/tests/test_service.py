import io
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from src.config import load_config, SMTPConfig, IMAPConfig
from src.errors import AgentError
from src.logger import EventLogger
from src.service import create_app, MAX_BODY_BYTES


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.config = replace(load_config(env={}), name="test-agent",
                              smtp=SMTPConfig(password="smtp-secret"),
                              imap=IMAPConfig(password="imap-secret"),
                              nasa_api_key="nasa-secret")
        self.llm = Mock()
        self.llm.chat.return_value = {"role": "assistant", "content": "Paris."}
        self.probe = Mock()
        self.factory = Mock(side_effect=[self.llm, self.probe])
        self.logs = io.StringIO()
        self.app = create_app(self.config, self.factory,
                              lambda name, **kw: EventLogger(name, self.logs, **kw))
        self.http = TestClient(self.app, base_url="http://localhost")
        self.http.__enter__()
        self.addCleanup(self.http.__exit__, None, None, None)

    def test_health(self):
        response = self.http.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ollama"], "ready")
        self.assertTrue(response.json()["alive"])
        self.assertFalse(response.json()["busy"])
        self.probe.verify.assert_called_once()
        self.assertEqual(self.factory.call_args_list[1].args[2], 3)

    def test_health_unavailable_then_recovers(self):
        self.probe.verify.side_effect = AgentError("llm_connection_error", "secret-detail")
        response = self.http.get("/health")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret-detail", response.text)
        self.probe.verify.side_effect = None
        self.assertEqual(self.http.get("/health").status_code, 200)

    def test_missing_model(self):
        self.probe.verify.side_effect = AgentError("model_not_found", "Model not installed")
        self.assertEqual(self.http.get("/health").json()["code"], "model_not_found")

    def test_info_is_explicit_allowlist(self):
        response = self.http.get("/info")
        data = response.json()
        self.assertEqual(data["agent"], "test-agent")
        self.assertEqual(data["model"], self.config.model)
        self.assertEqual(data["tools"], list(self.config.tools))
        self.assertEqual(set(data), {"agent", "role", "description", "model", "tools", "approval_policy"})
        for secret in ("smtp-secret", "imap-secret", "nasa-secret", "system_prompt", "base_url"):
            self.assertNotIn(secret, response.text)

    def test_success_and_task_log_correlation(self):
        response = self.http.post("/tasks", json={"task": "private question"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["result"], "Paris.")
        self.assertEqual(data["agent"], "test-agent")
        self.assertEqual(response.headers["cache-control"], "no-store")
        events = [json.loads(line) for line in self.logs.getvalue().splitlines()]
        for event in events[1:]:
            self.assertEqual(event["task_id"], data["task_id"])
        self.assertNotIn("private question", self.logs.getvalue())
        second = self.http.post("/tasks", json={"task": "Another question"})
        self.assertNotEqual(data["task_id"], second.json()["task_id"])
        messages = self.llm.chat.call_args.args[0]
        self.assertNotIn("private question", json.dumps(messages))

    def test_malformed_empty_and_extra_fields(self):
        for body in ('{', 'null', '[]', '{}', '{"task":null}', '{"task":1}',
                     '{"task":""}', '{"task":"   "}', '{"task":"x","approved":true}',
                     json.dumps({"task": "x" * 16001})):
            with self.subTest(body=body[:40]):
                response = self.http.post("/tasks", content=body,
                                          headers={"Content-Type": "application/json"})
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["code"], "invalid_task")
        self.llm.chat.assert_not_called()

    def test_wrong_content_type_and_oversize(self):
        self.assertEqual(self.http.post("/tasks", data={"task": "x"}).status_code, 415)
        response = self.http.post("/tasks", content=b"x" * (MAX_BODY_BYTES + 1),
                                  headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 413)
        self.llm.chat.assert_not_called()

    def test_busy_is_immediate_and_health_stays_available(self):
        entered, release = Event(), Event()

        def chat(*args):
            entered.set()
            self.assertTrue(release.wait(5))
            return {"role": "assistant", "content": "Done"}

        self.llm.chat.side_effect = chat
        with ThreadPoolExecutor(max_workers=1) as pool:
            active = pool.submit(self.http.post, "/tasks", json={"task": "first"})
            try:
                self.assertTrue(entered.wait(3))
                response = self.http.post("/tasks", json={"task": "second"})
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["status"], "busy")
                self.assertTrue(self.http.get("/health").json()["busy"])
                self.assertEqual(self.http.get("/info").status_code, 200)
                self.assertEqual(self.llm.chat.call_count, 1)
            finally:
                release.set()
            self.assertEqual(active.result(timeout=3).status_code, 200)
        self.assertFalse(self.http.get("/health").json()["busy"])

    def test_ollama_unavailable_releases_lock(self):
        self.llm.chat.side_effect = AgentError("llm_connection_error", "Cannot reach Ollama.")
        response = self.http.post("/tasks", json={"task": "Hello"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "llm_connection_error")
        self.llm.chat.side_effect = None
        self.assertEqual(self.http.post("/tasks", json={"task": "Hello"}).status_code, 200)

    def test_unexpected_exception_does_not_leak_and_recovers(self):
        self.llm.chat.side_effect = RuntimeError("smtp-secret imap-secret nasa-secret")
        response = self.http.post("/tasks", json={"task": "Hello"})
        self.assertEqual(response.status_code, 500)
        for secret in ("smtp-secret", "imap-secret", "nasa-secret"):
            self.assertNotIn(secret, response.text + self.logs.getvalue())
        self.assertFalse(self.app.state.busy.locked())

    @patch("src.tools.email_tool.smtplib.SMTP")
    @patch("src.tools.email_tool.EmailTool.execute")
    def test_approval_required_never_executes_or_prompts(self, execute, smtp):
        self.llm.chat.return_value = {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "send_email", "arguments": {
                "to": "person@example.com", "subject": "private subject", "body": "private body"}}}]}
        for dry_run in (True, False):
            self.app.state.config = replace(self.config, dry_run=dry_run)
            with patch("builtins.input", side_effect=AssertionError("Must not prompt")):
                response = self.http.post("/tasks", json={"task": "Send email to person@example.com"})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["status"], "approval_required")
            self.assertIn("No email was sent", response.json()["result"])
        execute.assert_not_called()
        smtp.assert_not_called()
        self.assertEqual(self.llm.chat.call_count, 2)
        self.assertNotIn("private subject", self.logs.getvalue())
        self.assertNotIn("private body", self.logs.getvalue())
        self.assertIn("approval_unavailable", self.logs.getvalue())

    def test_registry_allowlist_still_applies(self):
        self.llm.chat.side_effect = [
            {"role": "assistant", "content": "", "tool_calls": [{"function": {
                "name": "shell", "arguments": {"command": "dangerous"}}}]},
            {"role": "assistant", "content": "Pretend success"}]
        response = self.http.post("/tasks", json={"task": "Hello"})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("Pretend success", response.text)

    def test_browser_origin_and_rebinding_are_rejected(self):
        for headers in ({"Origin": "https://evil.example"}, {"Origin": "http://localhost"},
                        {"Host": "evil.example"}):
            self.assertEqual(self.http.post("/tasks", json={"task": "x"}, headers=headers).status_code, 403)
        self.assertEqual(self.http.options("/tasks", headers={"Origin": "https://evil.example"}).status_code, 403)
        self.llm.chat.assert_not_called()

    def test_lifespan_closes_both_clients(self):
        llm, probe = Mock(), Mock()
        with TestClient(create_app(self.config, Mock(side_effect=[llm, probe])),
                        base_url="http://localhost"):
            pass
        llm.close.assert_called_once()
        probe.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
