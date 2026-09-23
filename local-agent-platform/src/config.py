"""Load identity from YAML and runtime settings from the environment."""

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from .errors import AgentError


@dataclass(frozen=True)
class SMTPConfig:
    host: str = ""
    port: int = 587
    username: str = field(default="", repr=False)
    password: str = field(default="", repr=False)
    sender: str = ""
    use_tls: bool = True
    timeout: float = 30


@dataclass(frozen=True)
class IMAPConfig:
    host: str = "imap.mail.yahoo.com"
    port: int = 993
    username: str = field(default="", repr=False)
    password: str = field(default="", repr=False)
    timeout: float = 30


@dataclass(frozen=True)
class Config:
    name: str
    role: str
    description: str
    system_prompt: str
    model: str
    tools: tuple[str, ...]
    base_url: str = "http://host.containers.internal:11434"
    timeout: float = 120
    max_iterations: int = 10
    dry_run: bool = True
    smtp: SMTPConfig = field(default_factory=SMTPConfig, repr=False)
    imap: IMAPConfig = field(default_factory=IMAPConfig, repr=False)
    nasa_api_key: str = field(default="DEMO_KEY", repr=False)
    nasa_timeout: float = 30


def invalid(message):
    raise AgentError("configuration_error", message)


def boolean(env, name, default):
    value = env.get(name, str(default)).strip().lower()
    if value not in ("true", "false"):
        invalid(f"{name} must be true or false.")
    return value == "true"


def number(env, name, default, minimum, maximum, integer=False):
    try:
        value = (int if integer else float)(env.get(name, str(default)))
    except (TypeError, ValueError):
        invalid(f"{name} must be a number.")
    if not math.isfinite(value) or not minimum <= value <= maximum:
        invalid(f"{name} must be between {minimum} and {maximum}.")
    return value


def load_config(path="config/agent.yaml", env=None):
    env = os.environ if env is None else env
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        invalid("Cannot read agent YAML. Check the path and YAML syntax.")
    if not isinstance(data, dict):
        invalid("Agent YAML must contain a mapping.")
    required = {"name", "role", "description", "system_prompt", "model", "tools"}
    if set(data) != required:
        invalid("Agent YAML requires only: name, role, description, system_prompt, model, tools.")
    for key in required - {"tools"}:
        if not isinstance(data[key], str) or not data[key].strip():
            invalid(f"Agent YAML {key} must be a nonempty string.")
    enabled = data["tools"]
    if (not isinstance(enabled, list) or any(not isinstance(t, str) or not t for t in enabled)
            or len(enabled) != len(set(enabled))):
        invalid("tools must be a list of unique tool names (or []).")
    model = env.get("OLLAMA_MODEL", data["model"]).strip()
    if not model:
        invalid("OLLAMA_MODEL must not be empty.")
    base_url = env.get("OLLAMA_BASE_URL", "http://host.containers.internal:11434").rstrip("/")
    try:
        url = urlsplit(base_url)
        valid = (url.scheme in ("http", "https") and url.hostname and not url.username
                 and not url.password and not url.query and not url.fragment)
        _ = url.port
    except ValueError:
        valid = False
    if not valid:
        invalid("OLLAMA_BASE_URL must be an HTTP(S) URL without credentials, query, or fragment.")
    smtp = SMTPConfig(
        host=env.get("SMTP_HOST", "").strip(),
        port=number(env, "SMTP_PORT", 587, 1, 65535, integer=True),
        username=env.get("SMTP_USERNAME", ""), password=env.get("SMTP_PASSWORD", ""),
        sender=env.get("SMTP_FROM", "").strip(),
        use_tls=boolean(env, "SMTP_USE_TLS", True),
        timeout=number(env, "SMTP_TIMEOUT_SECONDS", 30, 1, 300),
    )
    imap = IMAPConfig(
        host=env.get("IMAP_HOST", "imap.mail.yahoo.com").strip(),
        port=number(env, "IMAP_PORT", 993, 1, 65535, integer=True),
        username=env.get("IMAP_USERNAME", ""), password=env.get("IMAP_PASSWORD", ""),
        timeout=number(env, "IMAP_TIMEOUT_SECONDS", 30, 1, 300),
    )
    nasa_key = env.get("NASA_API_KEY", "DEMO_KEY").strip()
    if not nasa_key or any(ord(c) < 33 or ord(c) > 126 for c in nasa_key):
        invalid("NASA_API_KEY must be a nonempty ASCII token without whitespace.")
    return Config(
        **{k: data[k] for k in ("name", "role", "description", "system_prompt")},
        model=model, tools=tuple(enabled), base_url=base_url,
        timeout=number(env, "OLLAMA_TIMEOUT_SECONDS", 120, 1, 3600),
        max_iterations=number(env, "MAX_AGENT_ITERATIONS", 10, 1, 100, integer=True),
        dry_run=boolean(env, "EMAIL_DRY_RUN", True), smtp=smtp, imap=imap,
        nasa_api_key=nasa_key, nasa_timeout=number(env, "NASA_TIMEOUT_SECONDS", 30, 1, 300),
    )
