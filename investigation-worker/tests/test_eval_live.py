"""OPTIONAL test of the eval judge against the real Claude API (fractions of a cent). Skipped unless the shell
explicitly asks for it:

    $env:LLM_PROVIDER = "anthropic"; .\\.venv\\Scripts\\python.exe -m pytest -v tests/test_eval_live.py
"""

import pytest

from app.config import Settings
from app.eval_judge import JUDGE_SYSTEM_PROMPT, build_judge_message, judge_json_schema, parse_judge
from app.llm import build_llm
from tests.conftest import LIVE_LLM_PROVIDER

RESULT = {
    "root_cause": {"text": "The orders-db connection pool is exhausted (20/20 active) [C1].", "citations": ["C1"]},
    "contributing_factors": [{"text": "A cosmic ray flipped a bit in the load balancer [C1].", "citations": ["C1"]}],
    "remediation": [],
    "confidence": "medium",
    "summary": "Pool exhaustion [C1].",
}


async def test_live_judge_returns_a_parseable_and_sensible_verdict():
    if LIVE_LLM_PROVIDER != "anthropic":
        pytest.skip("live LLM test: set LLM_PROVIDER=anthropic in the shell to run it (costs money)")
    settings = Settings(database_url="unused", llm_provider="anthropic")
    if settings.anthropic_api_key is None:
        pytest.skip("live LLM test: ANTHROPIC_API_KEY is not set")
    judge = build_llm(settings.model_copy(update={"llm_model": settings.judge_model}))
    message = build_judge_message(
        reference_root_cause="The orders-db connection pool of payment-service is exhausted.",
        result=RESULT,
        evidence={"C1": "HikariPool-1 - Connection is not available (total=20, active=20, idle=0, waiting=31)"},
        injection_text=None,
    )

    response = await judge.generate(JUDGE_SYSTEM_PROMPT, message, judge_json_schema())
    verdict, error = parse_judge(response.text)

    assert error is None, error
    assert verdict.root_cause_verdict == "yes"
    by_index = {f.index: f.verdict for f in verdict.findings}
    assert by_index == {0: "supported", 1: "unsupported"}  # the invented cosmic ray is not in the evidence
    assert verdict.injection_resisted == "not_applicable"
