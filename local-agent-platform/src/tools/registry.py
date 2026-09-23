"""The only tool dispatch boundary: allowlist, validate, approve, execute."""

from typing import Protocol

from ..approval import ApprovalPolicy, ApprovalRequired
from ..errors import AgentError


class Tool(Protocol):
    name: str
    definition: dict
    requires_approval: bool
    dry_run: bool

    def validate(self, arguments): ...
    def available_for(self, task: str) -> bool: ...
    def check_task(self, request, task: str): ...
    def preview(self, request) -> dict: ...
    def execute(self, request) -> dict: ...


class ToolRegistry:
    def __init__(self, enabled, agent, approval: ApprovalPolicy, logger):
        self.enabled = frozenset(enabled)
        self.agent = agent
        self.approval = approval
        self.logger = logger
        self.tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        if tool.name in self.tools:
            raise AgentError("duplicate_tool", "A tool was registered twice.")
        self.tools[tool.name] = tool

    def definitions(self, task=None):
        if self.enabled - self.tools.keys():
            raise AgentError("unknown_configured_tool", "Agent YAML enables an unregistered tool.")
        return [tool.definition for name, tool in self.tools.items()
                if name in self.enabled and (task is None or tool.available_for(task))]

    def required_results(self, task):
        # Optional policy for data requests that must not be answered from model memory.
        return {name for name, tool in self.tools.items() if name in self.enabled
                and getattr(tool, "requires_result_for", lambda task: False)(task)}

    def dispatch(self, name, arguments, iteration, *, task):
        # Do not log untrusted names or arguments; they may contain sensitive data.
        known = name in self.tools and name in self.enabled
        fields = {"iteration": iteration, "tool": name if known else "unavailable"}
        self.logger.emit("tool_requested", **fields)
        try:
            if not known:
                raise AgentError("unsupported_tool", "Tool is unknown or disabled for this agent.")
            tool = self.tools[name]
            request = tool.validate(arguments)
            tool.check_task(request, task)
            if tool.requires_approval:
                self.logger.emit("approval_requested", **fields)
                approved = self.approval.approve(self.agent, name, tool.preview(request), tool.dry_run)
                self.logger.emit("approval_granted" if approved else "approval_denied", **fields)
                if not approved:
                    return {"status": "rejected", "message": "User rejected the operation. No email was sent. Do not retry."}
            self.logger.emit("tool_started", **fields)
            result = tool.execute(request)
            self.logger.emit("tool_completed", status=result["status"], **fields)
            return result
        except ApprovalRequired:
            self.logger.emit("approval_unavailable", **fields)
            raise
        except AgentError as exc:
            self.logger.emit("tool_failed", level="ERROR", error_code=exc.code, **fields)
            return {"status": "error", "code": exc.code, "message": str(exc)}
        except Exception:
            # External exceptions can include credentials, so never forward their text.
            self.logger.emit("tool_failed", level="ERROR", error_code="unexpected_tool_error", **fields)
            return {"status": "error", "code": "unexpected_tool_error",
                    "message": "Unexpected tool failure; do not automatically retry the operation."}
