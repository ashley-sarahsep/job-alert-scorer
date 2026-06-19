"""Anthropic (Claude) scoring provider.

Uses the Messages API with structured outputs (a JSON schema) for reliable
parsing, and prompt caching: the rubric + candidate profile are identical for
every job in a run, so they sit in the cached portion of the prompt and each
job after the first is billed at cache-read rates.
"""

from providers.base import BaseProvider

# Models that reject sampling params (temperature). Sonnet/Haiku accept them.
_NO_TEMPERATURE_PREFIXES = ("claude-opus-4-7", "claude-opus-4-8", "claude-fable", "claude-mythos")


def _wants_temperature(model):
    m = (model or "").lower()
    return not any(m.startswith(p) for p in _NO_TEMPERATURE_PREFIXES)


class AnthropicProvider(BaseProvider):
    def __init__(self, model):
        super().__init__(model)
        self._client = None

    def client(self):
        if self._client is None:
            from anthropic_client import get_client
            self._client = get_client()
        return self._client

    def score_job(self, *, scoring_prompt, candidate_profile, job_description,
                  schema, max_tokens=2000, temperature=0):
        system = [
            {"type": "text", "text": scoring_prompt},
            {"type": "text", "text": candidate_profile,
             "cache_control": {"type": "ephemeral"}},
        ]
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": job_description}],
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
        }
        if _wants_temperature(self.model):
            kwargs["temperature"] = temperature

        response = self.client().messages.create(**kwargs)

        if response.stop_reason == "refusal":
            return {"_error": "refusal"}
        if response.stop_reason == "max_tokens":
            return {"_error": "truncated (increase scoring.max_tokens)"}

        text = next((b.text for b in response.content
                     if getattr(b, "type", None) == "text"), "")
        return self.parse_json(text)
