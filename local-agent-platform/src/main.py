"""Run with python -m src.main from the project root."""

import argparse
import sys

from .agent import Agent
from .approval import InteractiveApproval, terminal_text
from .config import load_config
from .errors import AgentError
from .llm_client import OllamaClient
from .logger import EventLogger
from .tools.email_tool import EmailTool
from .tools.registry import ToolRegistry
from .tools.web_tool import WebTool


def main(argv=None):
    parser = argparse.ArgumentParser(description="Stage 1 local AI agent")
    parser.add_argument("--config", default="config/agent.yaml")
    parser.add_argument("--check", action="store_true", help="Verify Ollama and model, then exit")
    parser.add_argument("--task", help="Run one task; tool approval still reads stdin")
    args = parser.parse_args(argv)
    logger = EventLogger("startup")
    client = None
    try:
        config = load_config(args.config)
        logger = EventLogger(config.name)
        logger.emit("agent_started")
        registry = ToolRegistry(config.tools, config.name, InteractiveApproval(), logger)
        registry.register(EmailTool(config.smtp, config.dry_run, logger))
        registry.register(WebTool())
        registry.definitions()
        client = OllamaClient(config.base_url, config.model, config.timeout)
        client.verify()
        logger.emit("ollama_connected")
        print(f"Agent: {terminal_text(config.name)}\nModel: {terminal_text(config.model)}\nOllama: connected")
        if args.check:
            return 0
        agent = Agent(config, client, registry, logger)
        while True:
            task = args.task if args.task is not None else input("\nEnter a task (exit to quit):\n> ")
            if task.strip().lower() in {"exit", "quit"}:
                return 0
            if not task.strip():
                if args.task is not None:
                    raise AgentError("empty_task", "Please supply a nonempty task.")
                continue
            try:
                print("Agent is thinking...")
                answer = agent.run(task)
                print("\nAgent:\n" + terminal_text(answer))
            except AgentError as exc:
                logger.emit("agent_error", level="ERROR", error_code=exc.code)
                print(f"Error: {exc}")
                if args.task is not None:
                    return 1
            if args.task is not None:
                return 0
    except AgentError as exc:
        logger.emit("agent_error", level="ERROR", error_code=exc.code)
        print(f"Error: {exc}", file=sys.stdout)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nGoodbye.")
        return 0
    finally:
        if client:
            client.close()
        logger.emit("agent_stopped")


if __name__ == "__main__":
    if sys.version_info < (3, 12):
        sys.exit("Python 3.12 or newer is required.")
    raise SystemExit(main())
