"""OpenAI-compatible chat completions client, defaulting to SpaceXAI."""

from openai import OpenAI


class LLMError(Exception):
    pass


_REASONING_KEYS = ("reasoning", "reasoning_content", "reasoning_details")


def _jsonable(value):
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


class Client:
    def __init__(self, cfg):
        self.base_url = (cfg.get("base_url") or "https://api.x.ai/v1").rstrip("/")
        self.api_key = cfg.get("api_key") or ""
        self.model = cfg.get("model") or "grok-4.6"
        self.provider = (cfg.get("provider") or "")
        self.temperature = cfg.get("temperature", 0.2)
        self.max_tokens = int(cfg.get("max_tokens") or 16384)
        self.timeout = int(cfg.get("request_timeout") or 120)
        self.reasoning_effort = (cfg.get("reasoning_effort") or "").strip()
        # Newer models renamed max_tokens and refuse a custom temperature.
        # Which applies is discovered from the API's own error.
        self._token_key = "max_tokens"
        self._send_temperature = True
        self._send_reasoning_effort = bool(self.reasoning_effort)
        self._strip_reasoning = False
        headers = None
        if self.provider == "openrouter":
            # Optional but recommended by OpenRouter for app rankings.
            headers = {
                "HTTP-Referer": "https://openrouter.ai",
                "X-Title": "alt-agent-harness",
            }
        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            default_headers=headers,
        )

    def _messages(self, messages):
        if not self._strip_reasoning:
            return messages
        cleaned = []
        for msg in messages:
            if any(k in msg for k in _REASONING_KEYS):
                msg = {k: v for k, v in msg.items() if k not in _REASONING_KEYS}
            cleaned.append(msg)
        return cleaned

    def _kwargs(self, messages, tools):
        kwargs = {
            "model": self.model,
            "messages": self._messages(messages),
        }
        kwargs[self._token_key] = self.max_tokens
        if self._send_temperature:
            kwargs["temperature"] = self.temperature
        if self._send_reasoning_effort:
            if self.provider == "openrouter":
                extra = kwargs.setdefault("extra_body", {})
                extra["reasoning"] = {"effort": self.reasoning_effort}
            else:
                kwargs["reasoning_effort"] = self.reasoning_effort
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
        if self._send_reasoning_effort and (
            "reasoning_effort" in text
            or "reasoning.effort" in text
            or "Unknown parameter: 'reasoning'" in text
        ):
            self._send_reasoning_effort = False
            print("[llm] %s rejects reasoning_effort; omitting it" % self.model)
            return True
        if not self._strip_reasoning and any(k in text for k in _REASONING_KEYS):
            self._strip_reasoning = True
            print("[llm] provider rejected reasoning traces; omitting them")
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
        for _ in range(4):
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
            message = choice.message
            parts = []
            if usage:
                parts.append("prompt=%s" % usage.prompt_tokens)
                parts.append("completion=%s" % usage.completion_tokens)
                details = getattr(usage, "completion_tokens_details", None)
                rtok = getattr(details, "reasoning_tokens", None) if details else None
                if rtok:
                    parts.append("reasoning=%s" % rtok)
            parts.append("finish=%s" % (choice.finish_reason or "?"))
            parts.append("content=%d" % len(message.content or ""))
            ntools = len(message.tool_calls or [])
            if ntools:
                parts.append("tools=%d" % ntools)
            print("[llm] " + " ".join(parts))

            content = message.content or ""
            out = {
                "role": "assistant",
                "content": content if content else (None if message.tool_calls else ""),
                "finish_reason": choice.finish_reason or "",
            }
            if message.tool_calls:
                out["tool_calls"] = []
                for i, tc in enumerate(message.tool_calls):
                    fn = tc.function
                    out["tool_calls"].append({
                        "id": tc.id or ("call_%d" % i),
                        "type": getattr(tc, "type", None) or "function",
                        "function": {
                            "name": getattr(fn, "name", None) or "",
                            "arguments": getattr(fn, "arguments", None) or "{}",
                        },
                    })
            reasoning_details = _jsonable(getattr(message, "reasoning_details", None))
            if reasoning_details:
                out["reasoning_details"] = reasoning_details
            reasoning = getattr(message, "reasoning", None) or getattr(
                message, "reasoning_content", None
            )
            if reasoning:
                out["reasoning"] = reasoning
            return out

        raise LLMError("API kept rejecting the request parameters: %s" % last_error)
