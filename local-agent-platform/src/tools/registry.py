"""The only tool dispatch boundary: allowlist, validate, approve, execute."""

from typing import Protocol

from ..approval import ApprovalPolicy, ApprovalRequired
from ..errors import AgentError
from ..retrieval import RetrievalState


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
        self.task = None
        self.retrieval = RetrievalState()

    def begin_task(self, task):
        self.task = task
        self.retrieval = RetrievalState()

    def register(self, tool: Tool):
        if tool.name in self.tools:
            raise AgentError("duplicate_tool", "A tool was registered twice.")
        self.tools[tool.name] = tool

    def definitions(self, task=None):
        if self.enabled - self.tools.keys():
            raise AgentError("unknown_configured_tool", "Agent YAML enables an unregistered tool.")
        return [tool.definition for name, tool in self.tools.items()
                if name in self.enabled and (task is None or tool.available_for(task)
                    or (name == "read_webpage" and task == self.task and self.retrieval.search_urls))]

    def required_results(self, task):
        # Optional policy for data requests that must not be answered from model memory.
        required = {name for name, tool in self.tools.items() if name in self.enabled
                    and getattr(tool, "requires_result_for", lambda task: False)(task)}
        if task == self.task and self.retrieval.needs_page(task, self.enabled):
            required.add("read_webpage")
        return required

    def finish_answer(self, answer, task):
        return self.retrieval.finish(answer, task, self.enabled)

    def candidate_urls(self, limit=3):
        # Concrete URLs a follow-up read_webpage reminder can point the model at.
        return list(dict.fromkeys(item["url"] for item in self.retrieval.search_results))[:limit]

    def dispatch(self, name, arguments, iteration, *, task):
        if task != self.task:
            self.begin_task(task)
        # Do not log untrusted names or arguments; they may contain sensitive data.
        known = name in self.tools and name in self.enabled
        fields = {"iteration": iteration, "tool": name if known else "unavailable"}
        self.logger.emit("tool_requested", **fields)
        searching = known and name == "search_web"
        if searching:
            self.logger.emit("web_search_requested", **fields)
        try:
            if not known:
                raise AgentError("unsupported_tool", "Tool is unknown or disabled for this agent.")
            tool = self.tools[name]
            request = tool.validate(arguments)
            if name == "read_webpage":
                tool.check_task(request, task, discovered_urls=frozenset(self.retrieval.search_urls))
            else:
                tool.check_task(request, task)
            if searching:
                self.retrieval.before_search()
            if tool.requires_approval:
                self.logger.emit("approval_requested", **fields)
                approved = self.approval.approve(self.agent, name, tool.preview(request), tool.dry_run)
                self.logger.emit("approval_granted" if approved else "approval_denied", **fields)
                if not approved:
                    return {"status": "rejected", "message": "User rejected the operation. No email was sent. Do not retry."}
            self.logger.emit("tool_started", **fields)
            if searching:
                self.logger.emit("web_search_started", **fields)
            result = tool.execute(request)
            self.retrieval.record(name, result)
            if searching:
                self.logger.emit("web_search_completed", result_count=len(result["results"]), **fields)
            self.logger.emit("tool_completed", status=result["status"], **fields)
            return result
        except ApprovalRequired:
            self.logger.emit("approval_unavailable", **fields)
            raise
        except AgentError as exc:
            if searching:
                self.logger.emit("web_search_failed", level="ERROR", error_code=exc.code, **fields)
            self.logger.emit("tool_failed", level="ERROR", error_code=exc.code, **fields)
            return {"status": "error", "code": exc.code, "message": str(exc)}
        except Exception:
            if searching:
                self.logger.emit("web_search_failed", level="ERROR", error_code="unexpected_tool_error", **fields)
            # External exceptions can include credentials, so never forward their text.
            self.logger.emit("tool_failed", level="ERROR", error_code="unexpected_tool_error", **fields)
            return {"status": "error", "code": "unexpected_tool_error",
                    "message": "Unexpected tool failure; do not automatically retry the operation."}
