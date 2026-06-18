"""Google (Gemini) scoring provider.

Reads GOOGLE_API_KEY from the environment. Requires
``pip install google-generativeai``.

NOTE: Best-effort, not run against the live API in this project. The rubric and
the required JSON fields are sent in the instructions and JSON output mode is
requested; verify against your account before relying on it.
"""

import os

from providers.base import BaseProvider

_JSON_REMINDER = (
    "\n\nRespond ONLY with a single JSON object containing these keys: score "
    "(integer 1-10), fit_summary (string), key_alignments (array of strings), "
    "key_gaps (array of strings), unique_match_signals (array of strings), "
    "hard_blockers (array of strings), interesting_stretch (boolean), "
    "transferable_angle (string), compensation (string), location (string), "
    "recommendation (string). No prose outside the JSON."
)


class GoogleProvider(BaseProvider):
    def _model(self, system_instruction):
        try:
            import google.generativeai as genai
        except ImportError as exc:
            raise RuntimeError("The 'google-generativeai' package is required for "
                               "this provider. Install: pip install google-generativeai") from exc
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY is not set.")
        genai.configure(api_key=api_key)
        return genai.GenerativeModel(self.model, system_instruction=system_instruction)

    def score_job(self, *, scoring_prompt, candidate_profile, job_description,
                  schema, max_tokens=2000, temperature=0):
        system = self.system_text(scoring_prompt, candidate_profile) + _JSON_REMINDER
        model = self._model(system)
        response = model.generate_content(
            job_description,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": temperature,
                "max_output_tokens": max_tokens,
            },
        )
        # response.text raises if the response was blocked or empty.
        try:
            text = response.text
        except (ValueError, AttributeError) as exc:
            return {"_error": f"no text in response ({exc})"}
        return self.parse_json(text)
