from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class LLMResponse:
    content: list[dict]            # {"type":"text","text":...} | {"type":"tool_use","id","name","input"}
    stop_reason: str = "end_turn"
    input_tokens: int = 0
    output_tokens: int = 0


class LLM(Protocol):
    model: str

    async def create(self, system: str, messages: list[dict], tools: list[dict] | None = None,
                     max_tokens: int = 2000) -> LLMResponse: ...


class AnthropicLLM:
    def __init__(self, api_key: str, model: str):
        from anthropic import AsyncAnthropic

        self.client, self.model = AsyncAnthropic(api_key=api_key), model

    async def create(self, system, messages, tools=None, max_tokens=2000) -> LLMResponse:
        kw = {"tools": tools} if tools else {}
        r = await self.client.messages.create(model=self.model, system=system, messages=messages, max_tokens=max_tokens, **kw)
        blocks = [b.model_dump(include={"type", "text", "id", "name", "input"}, exclude_none=True) for b in r.content]
        return LLMResponse(blocks, r.stop_reason or "end_turn", r.usage.input_tokens, r.usage.output_tokens)
