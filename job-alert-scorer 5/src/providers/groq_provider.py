"""Groq scoring provider (Llama, Mixtral, etc. via Groq's OpenAI-compatible API).

Reads GROQ_API_KEY from the environment. Requires ``pip install groq``.

NOTE: Best-effort, not run against the live API in this project. Groq supports
JSON-object mode (not full JSON-schema), so the required fields are described in
the instructions; verify against your account before relying on it.
"""

from providers.base import BaseProvider
from providers.google_provider import _JSON_REMINDER  # same field reminder text


class GroqProvider(BaseProvider):
    def __init__(self, model):
        super().__init__(model)
        self._client = None

    def client(self):
        if self._client is None:
            try:
                from groq import Groq
            except ImportError as exc:
                raise RuntimeError("The 'groq' package is required for this "
                                   "provider. Install it with: pip install groq") from exc
            self._client = Groq()
        return self._client

    def score_job(self, *, scoring_prompt, candidate_profile, job_description,
                  schema, max_tokens=2000, temperature=0):
        system = self.system_text(scoring_prompt, candidate_profile) + _JSON_REMINDER
        response = self.client().chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": job_description},
            ],
            response_format={"type": "json_object"},
        )
        return self.parse_json(response.choices[0].message.content)
