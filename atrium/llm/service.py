"""LLMService — the platform's one gateway to Claude.

One instance per module run: token usage accumulates here and the runner writes
it onto the run row. Defaults: claude-opus-4-8, adaptive thinking, streaming
(timeout-safe for long outputs). Modules may override model/effort per call.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 8000


@dataclass
class TokenUsage:
    tokens_in: int = 0   # input + cache reads/writes
    tokens_out: int = 0


class LLMService:
    def __init__(self, default_model: str, configured: bool):
        self._default_model = default_model
        self._configured = configured
        self._client = None
        self.usage = TokenUsage()

    # -- plumbing ---------------------------------------------------------------

    def _ensure_client(self):
        if not self._configured:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not configured — set it in .env to use ctx.llm"
            )
        if self._client is None:
            import anthropic

            self._client = anthropic.AsyncAnthropic()
        return self._client

    def add_usage(self, usage) -> None:
        """Accumulate an anthropic Usage object (or ints via keywords elsewhere)."""
        self.usage.tokens_in += (
            (usage.input_tokens or 0)
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
            + (getattr(usage, "cache_read_input_tokens", 0) or 0)
        )
        self.usage.tokens_out += usage.output_tokens or 0

    def _request_kwargs(self, model: str | None, effort: str | None) -> dict:
        kwargs: dict = {
            "model": model or self._default_model,
            "thinking": {"type": "adaptive"},
        }
        if effort:
            kwargs["output_config"] = {"effort": effort}
        return kwargs

    # -- single completions --------------------------------------------------------

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        effort: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> str:
        """One-shot completion; streams under the hood and returns the final text."""
        client = self._ensure_client()
        kwargs = self._request_kwargs(model, effort)
        if system:
            kwargs["system"] = system
        async with client.messages.stream(
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        ) as stream:
            message = await stream.get_final_message()
        self.add_usage(message.usage)
        return "".join(b.text for b in message.content if b.type == "text")

    async def parse(
        self,
        prompt: str,
        output_format,
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
    ):
        """Structured output: returns a validated instance of `output_format`."""
        client = self._ensure_client()
        kwargs = self._request_kwargs(model, None)
        kwargs.pop("thinking", None)  # structured extraction: direct answer
        if system:
            kwargs["system"] = system
        response = await client.messages.parse(
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            output_format=output_format,
            **kwargs,
        )
        self.add_usage(response.usage)
        if response.parsed_output is None:
            raise ValueError("model returned no parseable structured output")
        return response.parsed_output

    # -- agent loop -------------------------------------------------------------------

    async def agent(
        self,
        prompt: str,
        *,
        tools: list,
        system: str | None = None,
        model: str | None = None,
        effort: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> str:
        """Run a tool-use loop (SDK beta tool runner) and return the final text.

        `tools` are @beta_tool/@beta_async_tool functions — see atrium.llm.tools
        for the platform-provided librarian toolset.
        """
        client = self._ensure_client()
        kwargs = self._request_kwargs(model, effort)
        if system:
            kwargs["system"] = system
        runner = client.beta.messages.tool_runner(
            max_tokens=max_tokens,
            tools=tools,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
        final_text = ""
        async for message in runner:
            self.add_usage(message.usage)
            text = "".join(b.text for b in message.content if b.type == "text")
            if text.strip():
                final_text = text
        return final_text
