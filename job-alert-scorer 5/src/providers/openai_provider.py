"""OpenAI (GPT) scoring provider.

Uses Chat Completions with a JSON-schema response format. Reads OPENAI_API_KEY
from the environment. Requires ``pip install openai``.

NOTE: This provider follows the documented OpenAI SDK shape but has not been
run against the live API in this project (Anthropic is the tested default).
Verify against your account before relying on it.
"""

from providers.base import BaseProvider


class OpenAIProvider(BaseProvider):
    def __init__(self, model):
        super().__init__(model)
        self._client = None

    def client(self):
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError("The 'openai' package is required for this "
                                   "provider. Install it with: pip install openai") from exc
            self._client = OpenAI()
        return self._client

    def score_job(self, *, scoring_prompt, candidate_profile, job_description,
                  schema, max_tokens=2000, temperature=0):
        response = self.client().chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": self.system_text(scoring_prompt, candidate_profile)},
                {"role": "user", "content": job_description},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "job_fit", "schema": schema, "strict": True},
            },
        )
        message = response.choices[0].message
        # Structured-output refusals come back on .refusal with .content == None.
        if getattr(message, "refusal", None):
            return {"_error": f"refusal: {message.refusal}"}
        return self.parse_json(message.content)
