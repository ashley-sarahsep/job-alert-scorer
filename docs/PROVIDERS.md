# AI Providers - notes and a hypothetical review

The tool scores jobs through a pluggable provider (`src/providers/`). Anthropic
is the default and the only one exercised against a live API in this project.
The other three are written to each SDK's documented shape but are **unverified**
- this page reviews how each should behave and the red flags to watch for when
you test them.

All providers return the same JSON-schema dict (score, fit_summary,
key_alignments, key_gaps, unique_match_signals, hard_blockers,
interesting_stretch, transferable_angle, compensation, location,
recommendation). Score clamping and the hard-blocker cap happen in
`scorer.py`, after the provider returns.

| Provider | `provider` | Suggested model | Env key | Install |
|---|---|---|---|---|
| Anthropic | `anthropic` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` | (in requirements) |
| OpenAI | `openai` | `gpt-4o-mini` | `OPENAI_API_KEY` | `pip install openai` |
| Google | `google` | `gemini-1.5-flash` | `GOOGLE_API_KEY` | `pip install google-generativeai` |
| Groq | `groq` | `llama-3.1-70b-versatile` | `GROQ_API_KEY` | `pip install groq` |

## Anthropic (tested)

Uses the Messages API with `output_config.format` (JSON schema) for reliable
parsing, and prompt caching on the rubric + profile so each job after the first
is cheap. Handles `refusal` and `max_tokens` stop reasons. Sends `temperature`
only on models that accept it (Sonnet/Haiku); omits it on Opus 4.7+/Fable, which
reject sampling params.

## OpenAI (unverified)

Uses Chat Completions with `response_format` = `json_schema` + `strict: true`.

- **Model support:** strict structured outputs require `gpt-4o-2024-08-06` or
  later, or `gpt-4o-mini`. Older models will reject the `json_schema` format -
  use `gpt-4o-mini` or newer.
- **Refusals:** with structured outputs the model can refuse, returning
  `message.refusal` and `content == None`. Handled - returns an `_error`.
- **`max_tokens` vs `max_completion_tokens`:** the reasoning models (o1/o3) drop
  `max_tokens` in favour of `max_completion_tokens`, and ignore `temperature`. If
  you point this provider at an o-series model, those params need changing. For
  the gpt-4o family the current code is correct.
- **Schema strictness:** `strict: true` requires `additionalProperties: false`
  and every property in `required` - our schema satisfies both.

## Google / Gemini (unverified)

Uses `google.generativeai` (`GenerativeModel.generate_content`) with
`response_mime_type: application/json`; the required fields are described in the
system instruction rather than via a binding-specific `response_schema`.

- **SDK churn:** `google-generativeai` is the older SDK and is being superseded
  by `google-genai` (`google.genai`). If you install the newer package the
  import and client shape differ - this provider targets the older one.
- **Empty/blocked responses:** `response.text` raises if the response was blocked
  by safety filters or returned no candidates. Handled - returns an `_error`.
- **No hard schema enforcement:** JSON mode + instructions is softer than a true
  schema. Expect to validate output and possibly tighten the prompt. Adding a
  `response_schema` is an option if you pin a known SDK version.

## Groq (unverified)

Uses Groq's OpenAI-compatible Chat Completions with
`response_format: {"type": "json_object"}` (Groq does not support full
`json_schema`), so the required fields are described in the prompt.

- **JSON mode prerequisite:** like OpenAI's json-object mode, the prompt must
  mention JSON (it does, via the field reminder) or the call errors.
- **Model support:** not every Groq-hosted model supports JSON mode; pick one
  that does (e.g. a recent Llama 3.1 instruct model).
- **Softer guarantees:** json-object mode guarantees valid JSON but not your
  exact fields - validate before relying on it.

## Adding a provider

Create `src/providers/<name>_provider.py` with a class subclassing
`BaseProvider` and implementing `score_job(...)` to return the schema dict, then
register it in `src/providers/__init__.py`.
