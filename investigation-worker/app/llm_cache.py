"""An LLM wrapper for evaluation runs: on-disk response cache + a hard spending limit.

    cache key = sha256(model, prompt_version, system, user, schema, salt)

Re-running a report replays the cached responses and pays nothing. `salt` makes deliberate repeats
(the consistency check) separate cache entries. The budget is checked BEFORE each uncached call with a
worst-case estimate (the whole max_tokens as output), so a run stops cleanly before it can exceed the
limit, never after. Only token counts and costs are recorded: never prompts in logs, never the API key.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.llm import LLM, LLMResponse

CHARS_PER_TOKEN_ESTIMATE = 3  # conservative (real English text is ~4 chars per token)


class BudgetExceeded(RuntimeError):
    """The next uncached call could push the spend over --max-cost-usd. Not an LLM error: the graph
    does not catch it, so it ends the evaluation run (cleanly, with a partial report)."""


def cost_usd(input_tokens: int, output_tokens: int, price_in_per_m: float, price_out_per_m: float) -> float:
    return (input_tokens * price_in_per_m + output_tokens * price_out_per_m) / 1_000_000


@dataclass
class Budget:
    max_usd: float
    price_in_per_m: float
    price_out_per_m: float
    max_output_tokens: int
    spent_usd: float = 0.0
    calls: int = 0

    def estimate(self, prompt_chars: int) -> float:
        return cost_usd(prompt_chars // CHARS_PER_TOKEN_ESTIMATE + 1, self.max_output_tokens,
                        self.price_in_per_m, self.price_out_per_m)

    def reserve(self, prompt_chars: int) -> None:
        if self.spent_usd + self.estimate(prompt_chars) > self.max_usd:
            raise BudgetExceeded(
                f"stopping: the next call could exceed the budget (spent ${self.spent_usd:.4f} of ${self.max_usd:.2f})"
            )

    def record(self, response: LLMResponse) -> None:
        self.calls += 1
        self.spent_usd += cost_usd(response.input_tokens, response.output_tokens, self.price_in_per_m, self.price_out_per_m)


def cache_key(model: str, prompt_version: str, system: str, user: str, schema: dict[str, Any], salt: str = "") -> str:
    payload = json.dumps([model, prompt_version, system, user, schema, salt], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0


@dataclass
class CachingLLM:
    inner: LLM
    model: str
    prompt_version: str
    cache_dir: Path | None
    budget: Budget
    salt: str = ""
    stats: CacheStats = field(default_factory=CacheStats)

    def _path(self, key: str) -> Path | None:
        return self.cache_dir / f"{key}.json" if self.cache_dir else None

    async def generate(self, system: str, user: str, schema: dict[str, Any]) -> LLMResponse:
        path = self._path(cache_key(self.model, self.prompt_version, system, user, schema, self.salt))
        if path is not None and path.exists():
            self.stats.hits += 1
            return LLMResponse(**json.loads(path.read_text(encoding="utf-8")))
        self.budget.reserve(len(system) + len(user) + len(json.dumps(schema)))
        response = await self.inner.generate(system, user, schema)
        self.budget.record(response)
        self.stats.misses += 1
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(response), ensure_ascii=False), encoding="utf-8")
        return response
