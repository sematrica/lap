"""Interactive approval is independent of tool execution and SMTP."""

import unicodedata
from typing import Protocol


def terminal_text(value):
    # Escape terminal controls and bidi formatting so model text cannot hide the preview.
    return "".join(c if c in "\n\t" or not unicodedata.category(c).startswith("C")
                   else f"\\u{ord(c):04x}" for c in str(value))


class ApprovalPolicy(Protocol):
    def approve(self, agent: str, tool: str, preview: dict, dry_run: bool) -> bool: ...


class InteractiveApproval:
    def __init__(self, reader=input, writer=print):
        self.reader = reader
        self.writer = writer

    def approve(self, agent, tool, preview, dry_run):
        self.writer("\n----------------------------------------\nEMAIL SEND REQUEST")
        self.writer(f"Agent: {terminal_text(agent)}")
        self.writer("Mode: DRY RUN — no email will be sent" if dry_run else "Mode: REAL EMAIL")
        for key, value in preview.items():
            self.writer(f"{key.capitalize()}:\n{terminal_text(value)}")
        try:
            answer = self.reader("Approve this email operation? [y/N]: ")
        except (EOFError, KeyboardInterrupt):
            return False
        return answer.strip().lower() in {"y", "yes"}
