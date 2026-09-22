"""Offline demonstration: scripted HTTP replies, real validation and approval policy.

Run from the project root: .venv/bin/python -m tests.dry_run_demo
No Ollama server or SMTP credentials are needed. SMTP is guarded by a mock.
"""

import json
from unittest.mock import patch

import httpx

from src.agent import Agent
from src.approval import InteractiveApproval
from src.config import load_config
from src.llm_client import OllamaClient
from src.logger import EventLogger
from src.tools.email_tool import EmailTool
from src.tools.registry import ToolRegistry
from src.tools.web_tool import WebTool


def main():
    config = load_config(env={"EMAIL_DRY_RUN": "true"})
    logger = EventLogger(config.name)
    registry = ToolRegistry(config.tools, config.name, InteractiveApproval(), logger)
    registry.register(EmailTool(config.smtp, True, logger))

    registry.register(WebTool())

    def reply(request):
        messages = json.loads(request.content)["messages"]
        if messages[-1]["role"] == "tool":
            outcome = json.loads(messages[-1]["content"])
            message = {"role": "assistant", "content": outcome["message"]}
        else:
            message = {"role": "assistant", "content": "", "tool_calls": [{"function": {
                "name": "send_email", "arguments": {"to": "person@example.com",
                "subject": "Stage 1 dry run", "body": "The report is ready."}}}]}
        return httpx.Response(200, json={"done": True, "message": message})

    client = OllamaClient(config.base_url, config.model, transport=httpx.MockTransport(reply))
    print("OFFLINE DEMO: Ollama replies are scripted; SMTP must not be called.")
    try:
        with patch("src.tools.email_tool.smtplib.SMTP") as smtp:
            print(Agent(config, client, registry, logger).run("Send the demo email to person@example.com."))
            smtp.assert_not_called()
            print("Verified: SMTP was never opened.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
