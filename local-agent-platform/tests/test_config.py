import tempfile
import unittest
from pathlib import Path

from src.config import load_config
from src.errors import AgentError


class ConfigTests(unittest.TestCase):
    def test_yaml_and_safe_defaults(self):
        config = load_config(env={})
        self.assertEqual(config.name, "agent-01")
        self.assertEqual(config.tools, ("read_email", "nasa_neo_feed", "read_webpage", "send_email"))
        self.assertTrue(config.dry_run)
        self.assertEqual(config.base_url, "http://host.containers.internal:11434")

    def test_environment_overrides(self):
        config = load_config(env={"OLLAMA_MODEL": "small:latest", "OLLAMA_BASE_URL": "http://localhost:11434/",
                                  "MAX_AGENT_ITERATIONS": "3", "EMAIL_DRY_RUN": "false",
                                  "SMTP_PORT": "2525", "SMTP_PASSWORD": "secret"})
        self.assertEqual(config.model, "small:latest")
        self.assertEqual(config.base_url, "http://localhost:11434")
        self.assertEqual(config.max_iterations, 3)
        self.assertFalse(config.dry_run)
        self.assertEqual(config.smtp.port, 2525)
        self.assertNotIn("secret", repr(config))
        self.assertNotIn("secret", repr(config.smtp))

    def test_invalid_environment(self):
        for values in ({"EMAIL_DRY_RUN": "maybe"}, {"MAX_AGENT_ITERATIONS": "0"},
                       {"MAX_AGENT_ITERATIONS": "101"}, {"SMTP_PORT": "bad"},
                       {"OLLAMA_TIMEOUT_SECONDS": "nan"}, {"OLLAMA_TIMEOUT_SECONDS": "inf"},
                       {"OLLAMA_BASE_URL": "ftp://localhost"},
                       {"OLLAMA_BASE_URL": "http://user:secret@localhost"},
                       {"OLLAMA_MODEL": ""}):
            with self.subTest(values=values), self.assertRaises(AgentError):
                load_config(env=values)

    def test_invalid_yaml_and_missing_file(self):
        with self.assertRaises(AgentError):
            load_config("/no-such-agent-config.yaml", env={})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agent.yaml"
            for value in ("[", "[]", "name: test", "!!python/object:evil {}"):
                path.write_text(value)
                with self.subTest(value=value), self.assertRaises(AgentError):
                    load_config(path, env={})


class IntegrationConfigTests(unittest.TestCase):
    def test_integration_defaults_and_overrides(self):
        config = load_config(env={})
        self.assertEqual(config.imap.host, "imap.mail.yahoo.com")
        self.assertEqual(config.imap.port, 993)
        self.assertEqual(config.nasa_api_key, "DEMO_KEY")
        config = load_config(env={"IMAP_USERNAME": "private-user", "IMAP_PASSWORD": "private-pass",
                                  "NASA_API_KEY": "private-key", "NASA_TIMEOUT_SECONDS": "60"})
        self.assertEqual(config.imap.username, "private-user")
        self.assertEqual(config.nasa_timeout, 60)
        self.assertNotIn("private", repr(config))
        self.assertNotIn("private", repr(config.imap))
        for env in ({"IMAP_PORT": "0"}, {"IMAP_TIMEOUT_SECONDS": "NaN"}, {"NASA_API_KEY": ""},
                    {"NASA_TIMEOUT_SECONDS": "0"}):
            with self.assertRaises(AgentError):
                load_config(env=env)
