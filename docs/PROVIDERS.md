# AI Providers

Scoring runs through a pluggable provider (`src/providers/`). **This release
ships and tests Anthropic (Claude) only.**

Every provider returns the same JSON-schema dict (score, fit_summary,
key_alignments, key_gaps, unique_match_signals, hard_blockers,
interesting_stretch, transferable_angle, compensation, location,
recommendation). Score clamping and the hard-blocker cap happen in `scorer.py`
after the provider returns.

## Anthropic (default, tested)

Uses the Messages API with `output_config.format` (JSON schema) for reliable
parsing, and prompt caching on the rubric + profile so each job after the first
is cheap. Handles the `refusal` and `max_tokens` stop reasons. Sends
`temperature` only on models that accept it (Sonnet/Haiku); omits it on Opus
4.7+/Fable, which reject sampling params.

```yaml
scoring:
  provider: anthropic
  model: claude-sonnet-4-6
```

## Other providers (experimental, not in this release)

**OpenAI, Google (Gemini), and Groq** implementations exist on the
`experimental-providers` branch. They follow each SDK's documented shape but are
**unverified** - that branch's `docs/PROVIDERS.md` has a per-provider review and
the red flags to watch (model-support requirements, `max_tokens` vs
`max_completion_tokens` on OpenAI o-series, `google-generativeai` vs
`google-genai` SDK churn, Groq JSON-mode prerequisites).

To use one: check out that branch (or copy its `<name>_provider.py` into
`src/providers/` and register it in `__init__.py`), install the matching SDK
(`pip install openai` / `google-generativeai` / `groq`), put the key in `.env`,
and set `scoring.provider`.

## Adding a provider

Create `src/providers/<name>_provider.py` with a class subclassing
`BaseProvider` and implementing `score_job(...)` to return the schema dict, then
register it in `src/providers/__init__.py`.
