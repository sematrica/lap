import json
import unittest

import httpx

from src.errors import AgentError
from src.llm_client import OllamaClient


class ClientTests(unittest.TestCase):
    def client(self, handler):
        client = OllamaClient("http://ollama.test:11434", "qwen3", transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        return client

    def test_verify_and_model_tag(self):
        client = self.client(lambda req: httpx.Response(200, json={"models": [{"name": "qwen3:latest"}]}))
        self.assertIn("qwen3:latest", client.verify())

    def test_missing_model(self):
        client = self.client(lambda req: httpx.Response(200, json={"models": []}))
        with self.assertRaises(AgentError) as caught:
            client.verify()
        self.assertEqual(caught.exception.code, "model_not_found")

    def test_payload_and_tools(self):
        def handler(req):
            self.assertEqual(req.url.path, "/api/chat")
            payload = json.loads(req.content)
            self.assertFalse(payload["stream"])
            self.assertEqual(payload["model"], "qwen3")
            self.assertEqual(payload["tools"], [{"type": "function"}])
            return httpx.Response(200, json={"done": True, "message": {
                "role": "assistant", "content": "", "tool_calls": [
                    {"function": {"name": "send_email", "arguments": {"to": "x@example.com"}}}]}})
        result = self.client(handler).chat([], [{"type": "function"}])
        self.assertEqual(result["tool_calls"][0]["function"]["name"], "send_email")

    def test_timeouts_and_connection_failures(self):
        for error, code in ((httpx.ReadTimeout, "llm_timeout"), (httpx.ConnectError, "llm_connection_error")):
            def handler(req):
                raise error("secret server details", request=req)
            with self.subTest(code=code), self.assertRaises(AgentError) as caught:
                self.client(handler).chat([], [])
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn("secret", str(caught.exception))

    def test_http_errors_are_sanitized(self):
        for status, code in ((404, "model_not_found"), (400, "llm_http_error"), (500, "llm_http_error")):
            client = self.client(lambda req: httpx.Response(status, text="secret raw response"))
            with self.subTest(status=status), self.assertRaises(AgentError) as caught:
                client.chat([], [])
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn("secret", str(caught.exception))

    def test_malformed_responses(self):
        for data in ([], {}, {"error": "secret"}, {"done": False, "message": {}},
                     {"done": True, "message": {"role": "assistant", "content": ""}},
                     {"done": True, "message": {"role": "assistant", "content": 4}},
                     {"done": True, "message": {"role": "assistant", "tool_calls": "bad"}},
                     {"done": True, "message": {"role": "assistant", "tool_calls": [
                         {"function": {"name": "send_email", "arguments": "{}"}}]}},
                     {"done": True, "message": {"role": "assistant", "tool_calls": [{}] * 9}}):
            with self.subTest(data=data), self.assertRaises(AgentError):
                self.client(lambda req: httpx.Response(200, json=data)).chat([], [])
        with self.assertRaises(AgentError):
            self.client(lambda req: httpx.Response(200, text="not JSON")).chat([], [])
        with self.assertRaises(AgentError):
            self.client(lambda req: httpx.Response(200, json={"models": [None]})).verify()

    def test_plain_chat_omits_empty_tools(self):
        def handler(req):
            self.assertNotIn("tools", json.loads(req.content))
            return httpx.Response(200, json={"done": True, "message": {"role": "assistant", "content": "Hello"}})
        self.assertEqual(self.client(handler).chat([], [])["content"], "Hello")
