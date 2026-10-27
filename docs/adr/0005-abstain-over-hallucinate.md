# ADR 0005: Abstain rather than guess; validate every citation

Status: accepted (milestone 2)

## Context

An on-call engineer acts on the root cause the system proposes. A confident wrong answer is worse than no answer: it
sends people down the wrong path at the worst moment. LLMs will produce a plausible cause when asked for one, even
without evidence.

## Decision

- **Evidence first.** The worker retrieves evidence for the incident (hybrid search, per-type caps) and labels it
  C1..Cn. With no evidence at all, it stores an "insufficient evidence" result without calling the LLM.
- **Abstaining is a valid answer.** The prompt and the output schema allow `root_cause: null`; the schema enforces
  that a missing root cause comes with `confidence: "low"`, and the prompt asks for "high" only when several evidence
  items agree. The UI writes confidence out ("Low confidence — not enough evidence to confirm a cause").
- **Every finding cites evidence, and citations are checked.** Structured outputs (one Pydantic model generates the
  schema and validates the answer). `validate_output` rejects unknown citation labels; one repair attempt gets the
  error back, and a second invalid answer marks the investigation FAILED rather than storing it.
- **Evidence is data, not instructions**: delimited and sanitised in the prompt, tested with injected log lines.

## Consequences

- Evaluation (`docs/evaluation.md`, 28 synthetic cases, Claude Haiku 5.5): 100% valid citations, 94% of findings
  supported by their cited evidence (LLM judge), both no-evidence cases abstained, both injection cases resisted.
- The check is that a citation **exists**, not that it **supports** the claim; the 6% unsupported findings show the
  gap. Claim-level validation is future work.
- Some real incidents will get "low confidence" answers that a human would have guessed right; that is the trade-off.

## Alternatives considered

- **Free-text answers**: no reliable citation check.
- **Always produce a best-guess cause**: higher apparent "coverage", lower trust.
- **A second LLM pass that verifies each finding against its evidence**: better faithfulness, about double the cost and
  latency; the planned next step.
