"""Validated SMTP email transport. Approval belongs to the registry/policy."""

import re
import smtplib
import ssl
from dataclasses import asdict, dataclass
from email.message import EmailMessage

from ..errors import AgentError


@dataclass(frozen=True)
class EmailInput:
    to: str
    subject: str
    body: str


def valid_address(address):
    # Stage 1 accepts one plain ASCII mailbox, not display names or recipient lists.
    if not isinstance(address, str) or len(address) > 254 or not address.isascii():
        return False
    if address.count("@") != 1:
        return False
    local, domain = address.split("@")
    if (not local or len(local) > 64 or local.startswith(".") or local.endswith(".")
            or ".." in local or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", local)):
        return False
    labels = domain.split(".")
    return len(labels) >= 2 and all(
        re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
        for label in labels
    )


def task_recipients(task):
    """Only literal mailboxes supplied by the user; never model-invented contacts."""
    candidates = re.findall(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+", task)
    return {address for candidate in candidates
            if valid_address(address := candidate.rstrip("."))}


class EmailTool:
    name = "send_email"
    requires_approval = True
    definition = {
        "type": "function", "function": {
            "name": "send_email",
            "description": "Propose an email to one address. Requires user approval. Dry runs do not send.",
            "parameters": {"type": "object", "properties": {
                "to": {"type": "string", "description": "One plain email address"},
                "subject": {"type": "string", "maxLength": 998},
                "body": {"type": "string", "maxLength": 100000}},
                "required": ["to", "subject", "body"], "additionalProperties": False}}}

    def __init__(self, settings, dry_run, logger):
        self.settings = settings
        self.dry_run = dry_run
        self.logger = logger

    def validate(self, arguments):
        if not isinstance(arguments, dict) or set(arguments) != {"to", "subject", "body"}:
            raise AgentError("invalid_email", "Email requires exactly to, subject, and body.")
        for key, limit in (("to", 254), ("subject", 998), ("body", 100000)):
            value = arguments[key]
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise AgentError("invalid_email", f"Email {key} must be nonempty text of at most {limit} characters.")
            if any(ord(c) < 32 and (key != "body" or c not in "\n\r\t") for c in value):
                raise AgentError("invalid_email", f"Email {key} contains invalid control characters.")
            try:
                value.encode("utf-8")
            except UnicodeError:
                raise AgentError("invalid_email", f"Email {key} contains invalid Unicode.") from None
        if not valid_address(arguments["to"]):
            raise AgentError("invalid_email", "Use one plain ASCII email address, such as person@example.com.")
        return EmailInput(**arguments)

    def available_for(self, task):
        return bool(task_recipients(task))

    def check_task(self, request, task):
        if request.to not in task_recipients(task):
            raise AgentError(
                "recipient_not_provided",
                "No email was sent. The recipient must be supplied in the user's task. "
                "Answer ordinary questions directly; ask for a recipient only if the user requests email.",
            )

    def preview(self, request):
        return asdict(request)

    def execute(self, request):
        if self.dry_run:
            self.logger.emit("email_dry_run", message="DRY RUN — email would have been sent")
            return {"status": "dry_run", "message": "DRY RUN — email would have been sent. No email was sent."}
        config = self.settings
        if not config.host or not valid_address(config.sender):
            raise AgentError("smtp_configuration_error", "Real email requires SMTP_HOST and a valid SMTP_FROM.")
        if bool(config.username) != bool(config.password):
            raise AgentError("smtp_configuration_error", "Set both SMTP_USERNAME and SMTP_PASSWORD, or neither for an anonymous relay.")
        if config.username and not config.use_tls:
            raise AgentError("smtp_configuration_error", "SMTP authentication requires SMTP_USE_TLS=true.")
        message = EmailMessage()
        message["From"] = config.sender
        message["To"] = request.to
        message["Subject"] = request.subject
        message.set_content(request.body)
        try:
            with smtplib.SMTP(config.host, config.port, timeout=config.timeout) as smtp:
                smtp.ehlo()
                if config.use_tls:
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                if config.username:
                    smtp.login(config.username, config.password)
                refused = smtp.send_message(message, from_addr=config.sender, to_addrs=[request.to])
                if refused:
                    raise AgentError("smtp_recipient_rejected", "SMTP rejected the recipient.")
        except smtplib.SMTPAuthenticationError:
            raise AgentError("smtp_authentication_error", "SMTP authentication failed. Check credentials and provider settings.") from None
        except smtplib.SMTPRecipientsRefused:
            raise AgentError("smtp_recipient_rejected", "SMTP rejected the recipient.") from None
        except (smtplib.SMTPException, OSError):
            raise AgentError("smtp_connection_error", "SMTP delivery failed or is uncertain. Check the provider before retrying to avoid duplicates.") from None
        self.logger.emit("email_sent")
        return {"status": "sent", "message": "Email accepted by the SMTP server; inbox delivery is not guaranteed."}
