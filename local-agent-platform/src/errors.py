"""Safe, user-facing errors. Never include server responses or credentials."""


class AgentError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
