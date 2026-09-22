import io
import smtplib
import unittest
from unittest.mock import Mock, patch

from src.approval import InteractiveApproval
from src.config import SMTPConfig
from src.errors import AgentError
from src.logger import EventLogger
from src.tools.email_tool import EmailTool
from src.tools.registry import ToolRegistry

EMAIL = {"to": "person@example.com", "subject": "Hello", "body": "The report is ready."}


class EmailTests(unittest.TestCase):
    def setUp(self):
        self.logs = io.StringIO()
        self.logger = EventLogger("test-agent", self.logs)
        self.tool = EmailTool(SMTPConfig(), True, self.logger)
        self.approval = Mock()
        self.approval.approve.return_value = True
        self.registry = ToolRegistry(["send_email"], "test-agent", self.approval, self.logger)
        self.registry.register(self.tool)

    def test_valid_email(self):
        self.assertEqual(self.tool.validate(EMAIL).to, EMAIL["to"])

    def test_bad_addresses_and_injection(self):
        for address in ("bad", "a@localhost", "a@example.com,b@example.com", "Name <a@example.com>",
                        "a@example.com\nBcc: victim@example.com", "a@-example.com", "a..b@example.com", "a@é.com"):
            with self.subTest(address=address), self.assertRaises(AgentError):
                self.tool.validate({**EMAIL, "to": address})
        for bad in ({**EMAIL, "subject": "Hello\r\nBcc: x@example.com"}, {**EMAIL, "body": " "},
                    {**EMAIL, "subject": 1}, {**EMAIL, "body": "x" * 100001}, {**EMAIL, "extra": "no"},
                    {"to": "x@example.com"}, {**EMAIL, "body": "\ud800"}):
            with self.subTest(bad_type=list(bad)), self.assertRaises(AgentError):
                self.tool.validate(bad)

    @patch("src.tools.email_tool.smtplib.SMTP")
    def test_dry_run_never_opens_smtp(self, smtp):
        result = self.registry.dispatch("send_email", EMAIL, 1, task="Send email to person@example.com.")
        self.assertEqual(result["status"], "dry_run")
        smtp.assert_not_called()
        self.approval.approve.assert_called_once_with("test-agent", "send_email", EMAIL, True)
        self.assertIn("email_dry_run", self.logs.getvalue())
        self.assertNotIn(EMAIL["body"], self.logs.getvalue())
        self.assertNotIn(EMAIL["to"], self.logs.getvalue())

    @patch("src.tools.email_tool.smtplib.SMTP")
    def test_rejection_prevents_real_send(self, smtp):
        self.tool.dry_run = False
        self.approval.approve.return_value = False
        self.assertEqual(self.registry.dispatch("send_email", EMAIL, 1, task="Send email to person@example.com.")["status"], "rejected")
        smtp.assert_not_called()
        self.assertIn("approval_denied", self.logs.getvalue())

    @patch("src.tools.email_tool.smtplib.SMTP")
    def test_unknown_disabled_and_invalid_tools(self, smtp):
        self.assertEqual(self.registry.dispatch("shell", {}, 1, task="Send email to person@example.com.")["code"], "unsupported_tool")
        self.assertEqual(self.registry.dispatch("send_email", {}, 1, task="Send email to person@example.com.")["code"], "invalid_email")
        self.registry.enabled = frozenset()
        self.assertEqual(self.registry.dispatch("send_email", EMAIL, 1, task="Send email to person@example.com.")["code"], "unsupported_tool")
        self.approval.approve.assert_not_called()
        smtp.assert_not_called()
        self.assertEqual(self.registry.definitions(), [])

    def test_task_scoped_definitions(self):
        self.assertEqual(self.registry.definitions("What is the capital of France?"), [])
        self.assertEqual(self.registry.definitions("Email John about the report."), [])
        self.assertEqual(len(self.registry.definitions("Email person@example.com.")), 1)

    def test_bad_tool_configuration(self):
        self.registry.enabled = frozenset(["shell"])
        with self.assertRaises(AgentError):
            self.registry.definitions()
        with self.assertRaises(AgentError):
            self.registry.register(self.tool)

    def test_interactive_approval_defaults_to_no(self):
        for answer, expected in (("", False), ("n", False), ("sure", False), ("y", True), (" YES ", True)):
            policy = InteractiveApproval(reader=lambda _: answer, writer=lambda _: None)
            self.assertEqual(policy.approve("test", "send_email", EMAIL, True), expected)
        for error in (EOFError, KeyboardInterrupt):
            policy = InteractiveApproval(reader=Mock(side_effect=error), writer=lambda _: None)
            self.assertFalse(policy.approve("test", "send_email", EMAIL, False))

    def test_preview_escapes_terminal_control(self):
        output = []
        policy = InteractiveApproval(reader=lambda _: "n", writer=output.append)
        policy.approve("test", "send_email", {**EMAIL, "body": "\x1b[2J\u202eevil"}, True)
        self.assertNotIn("\x1b", "".join(output))
        self.assertIn("\\u001b", "".join(output))
        self.assertIn("\\u202e", "".join(output))

    @patch("src.tools.email_tool.smtplib.SMTP")
    def test_real_smtp_sequence_is_mocked(self, smtp_class):
        self.tool.dry_run = False
        self.tool.settings = SMTPConfig(host="smtp.example.com", username="user", password="secret", sender="me@example.com")
        smtp = smtp_class.return_value.__enter__.return_value
        smtp.send_message.return_value = {}
        result = self.registry.dispatch("send_email", EMAIL, 1, task="Send email to person@example.com.")
        self.assertEqual(result["status"], "sent")
        self.assertEqual([call[0] for call in smtp.method_calls], ["ehlo", "starttls", "ehlo", "login", "send_message"])
        sent = smtp.send_message.call_args
        self.assertEqual(sent.kwargs["to_addrs"], [EMAIL["to"]])
        self.assertEqual(sent.args[0]["Subject"], EMAIL["subject"])
        self.assertNotIn("secret", self.logs.getvalue())

    @patch("src.tools.email_tool.smtplib.SMTP")
    def test_smtp_failures_are_safe(self, smtp_class):
        self.tool.dry_run = False
        self.assertEqual(self.registry.dispatch("send_email", EMAIL, 1, task="Send email to person@example.com.")["code"], "smtp_configuration_error")
        smtp_class.assert_not_called()
        self.tool.settings = SMTPConfig(host="smtp.example.com", sender="me@example.com")
        for error, code in ((smtplib.SMTPAuthenticationError(535, b"secret"), "smtp_authentication_error"),
                            (OSError("secret"), "smtp_connection_error"),
                            (smtplib.SMTPRecipientsRefused({}), "smtp_recipient_rejected")):
            smtp_class.side_effect = error
            result = self.registry.dispatch("send_email", EMAIL, 1, task="Send email to person@example.com.")
            self.assertEqual(result["code"], code)
            self.assertNotIn("secret", str(result))
        self.assertNotIn("secret", self.logs.getvalue())

    @patch("src.tools.email_tool.smtplib.SMTP")
    def test_credentials_require_tls_and_pair(self, smtp):
        self.tool.dry_run = False
        for settings in (SMTPConfig(host="smtp.example.com", sender="me@example.com", username="u"),
                         SMTPConfig(host="smtp.example.com", sender="me@example.com", username="u", password="p", use_tls=False)):
            self.tool.settings = settings
            self.assertEqual(self.registry.dispatch("send_email", EMAIL, 1, task="Send email to person@example.com.")["code"], "smtp_configuration_error")
        smtp.assert_not_called()
