"""An explicit, bounded conversation loop with no hidden framework."""

import json

from .errors import AgentError


class Agent:
    def __init__(self, config, client, registry, logger, writer=print):
        self.config, self.client, self.registry = config, client, registry
        self.logger, self.writer = logger, writer

    def run(self, task):
        self.logger.emit("task_received")
        messages = [{"role": "system", "content": self.config.system_prompt},
                    {"role": "user", "content": task}]
        definitions = self.registry.definitions(task)
        for iteration in range(1, self.config.max_iterations + 1):
            self.logger.emit("llm_request", iteration=iteration)
            message = self.client.chat(messages, definitions)
            self.logger.emit("llm_response", iteration=iteration)
            messages.append(message)
            calls = message.get("tool_calls", [])
            if not calls:
                self.logger.emit("agent_completed", iteration=iteration)
                return message["content"]
            for call in calls:
                function = call["function"]
                result = self.registry.dispatch(function["name"], function["arguments"], iteration, task=task)
                # Show the runtime outcome separately from the model's final prose.
                self.writer("Tool result: " + result["message"])
                messages.append({"role": "tool", "tool_name": function["name"],
                                 "content": json.dumps(result)})
        raise AgentError("iteration_limit", "Maximum agent iterations reached. Stopped safely; completed tool operations are not undone. Review the tool results before retrying.")
