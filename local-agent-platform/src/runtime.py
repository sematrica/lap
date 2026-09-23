"""Shared tool wiring for the CLI and HTTP service; execution stays in Agent."""

from .tools.email_tool import EmailTool
from .tools.inbox_tool import InboxTool
from .tools.nasa_tool import NasaTool
from .tools.registry import ToolRegistry
from .tools.web_tool import WebTool


def build_registry(config, approval, logger):
    registry = ToolRegistry(config.tools, config.name, approval, logger)
    registry.register(EmailTool(config.smtp, config.dry_run, logger))
    registry.register(WebTool())
    registry.register(InboxTool(config.imap))
    registry.register(NasaTool(config.nasa_api_key, config.nasa_timeout))
    registry.definitions()  # Fail at startup for unknown configured tools.
    return registry
