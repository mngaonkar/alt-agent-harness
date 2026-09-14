"""OpenAI-compatible chat completions client, defaulting to SpaceXAI."""

from openai import OpenAI


class LLMError(Exception):
    pass


class Client:
    def __init__(self, cfg):
        self.base_url = (cfg.get("base_url") or "https://api.x.ai/v1").rstrip("/")
        self.api_key = cfg.get("api_key") or ""
        self.model = cfg.get("model") or "grok-4.6"
        self.temperature = cfg.get("temperature", 0.2)
        self.max_tokens = int(cfg.get("max_tokens") or 4096)
        self.timeout = int(cfg.get("request_timeout") or 120)
        # Newer models renamed max_tokens and refuse a custom temperature.
        # Which applies is discovered from the API's own error.
        self._token_key = "max_tokens"
        self._send_temperature = True
        headers = None
        if (cfg.get("provider") or "") == "openrouter":
            # Optional but recommended by OpenRouter for app rankings.
            headers = {
                "HTTP-Referer": "https://openrouter.ai",
                "X-Title": "agent-harness",
            }
        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            default_headers=headers,
        )

    def _kwargs(self, messages, tools):
        kwargs = {
            "model": self.model,
            "messages": messages,
        }
        kwargs[self._token_key] = self.max_tokens
        if self._send_temperature:
            kwargs["temperature"] = self.temperature
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return kwargs

    def _adapt(self, detail):
        """Adjust to an unsupported-parameter error. True if worth retrying."""
        text = str(detail)
        if "max_completion_tokens" in text and self._token_key == "max_tokens":
            self._token_key = "max_completion_tokens"
            print("[llm] switching to max_completion_tokens for %s" % self.model)
            return True
        if "'temperature'" in text and self._send_temperature:
            self._send_temperature = False
            print("[llm] %s rejects a custom temperature; using its default"
                  % self.model)
            return True
        return False

    def chat(self, messages, tools=None):
        """One completion round. Returns the assistant message dict."""
        if not self.api_key:
            raise LLMError(
                "no api_key configured; set XAI_API_KEY, OPENROUTER_API_KEY, "
                "or api_key in config.json"
            )

        last_error = None
        for _ in range(3):
            try:
                resp = self._client.chat.completions.create(
                    **self._kwargs(messages, tools)
                )
            except Exception as exc:
                detail = str(exc)
                last_error = exc
                if self._adapt(detail):
                    continue
                raise LLMError("API error talking to %s: %s"
                               % (self.base_url, exc)) from exc

            choice = (resp.choices or [None])[0]
            if choice is None or choice.message is None:
                raise LLMError("API returned no choices")

            usage = resp.usage
            if usage:
                print("[llm] tokens prompt=%s completion=%s" % (
                    usage.prompt_tokens, usage.completion_tokens))

            message = choice.message
            out = {
                "role": "assistant",
                "content": message.content or "",
            }
            if message.tool_calls:
                out["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments or "{}",
                        },
                    }
                    for tc in message.tool_calls
                ]
            return out

        raise LLMError("API kept rejecting the request parameters: %s" % last_error)
