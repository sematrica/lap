"""Ollama HTTP transport. No tool execution happens in this module."""

import httpx

from .errors import AgentError

MAX_TOOL_CALLS = 8


class OllamaClient:
    def __init__(self, base_url, model, timeout=120, transport=None):
        self.model = model
        self.http = httpx.Client(base_url=base_url.rstrip("/") + "/", timeout=timeout,
                                 transport=transport, trust_env=False, follow_redirects=False)

    def close(self):
        self.http.close()

    def _request(self, method, path, **kwargs):
        try:
            response = self.http.request(method, path, **kwargs)
            response.raise_for_status()
        except httpx.TimeoutException:
            raise AgentError("llm_timeout", "Ollama timed out. Try a smaller model or increase OLLAMA_TIMEOUT_SECONDS.") from None
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                raise AgentError("model_not_found", "Ollama model or API not found. Check the endpoint and run ollama pull for the configured model.") from None
            raise AgentError("llm_http_error", f"Ollama returned HTTP {status}. Check model tool support and Ollama logs.") from None
        except httpx.RequestError:
            raise AgentError("llm_connection_error", "Cannot reach Ollama. Check OLLAMA_BASE_URL, the server, and Podman networking.") from None
        try:
            data = response.json()
        except ValueError:
            raise AgentError("llm_malformed_response", "Ollama returned invalid JSON.") from None
        if not isinstance(data, dict) or "error" in data:
            raise AgentError("llm_malformed_response", "Ollama returned an unexpected response. Check its server logs.")
        return data

    def verify(self):
        data = self._request("GET", "api/tags")
        models = data.get("models")
        if not isinstance(models, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("name"), str) for item in models
        ):
            raise AgentError("llm_malformed_response", "Ollama returned an invalid model list.")
        names = {item["name"] for item in models}
        # An omitted tag means :latest, including names with registry ports.
        model = self.model if ":" in self.model.rsplit("/", 1)[-1] else self.model + ":latest"
        if self.model not in names and model not in names:
            raise AgentError("model_not_found", "Configured model is not installed. Check ollama list and ollama pull.")
        return names

    def chat(self, messages, definitions):
        payload = {"model": self.model, "messages": messages, "stream": False}
        if definitions:
            payload["tools"] = definitions
        data = self._request("POST", "api/chat", json=payload)
        msg = data.get("message")
        if (data.get("done") is not True or not isinstance(msg, dict)
                or msg.get("role") != "assistant" or not isinstance(msg.get("content", ""), str)):
            raise AgentError("llm_malformed_response", "Ollama returned an incomplete or invalid assistant message.")
        calls = msg.get("tool_calls", [])
        if not isinstance(calls, list) or len(calls) > MAX_TOOL_CALLS:
            raise AgentError("llm_malformed_response", "Ollama returned an invalid or excessive tool-call list.")
        for call in calls:
            function = call.get("function") if isinstance(call, dict) else None
            if (not isinstance(function, dict) or not isinstance(function.get("name"), str)
                    or not function["name"] or not isinstance(function.get("arguments"), dict)):
                raise AgentError("llm_malformed_response", "Ollama returned malformed tool arguments; no tools were executed.")
        if not calls and not msg.get("content", "").strip():
            raise AgentError("llm_malformed_response", "Ollama returned an empty answer.")
        # Preserve the assistant message (including thinking/tool-call identifiers).
        return msg
