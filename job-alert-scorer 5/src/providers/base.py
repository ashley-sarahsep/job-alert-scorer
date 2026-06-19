"""Provider-agnostic scoring interface.

A provider takes the scoring rubric, the candidate profile, and a single job
description, and returns the model's assessment as a plain dict matching the
shared JSON schema (score, fit_summary, key_alignments, key_gaps,
unique_match_signals, hard_blockers, interesting_stretch, transferable_angle,
compensation, location, recommendation).

Each concrete provider assembles the request in whatever way its SDK expects and
parses the JSON back out. Post-processing (score clamping, the hard-blocker cap)
happens in scorer.py, so providers only have to return the raw parsed dict.
"""

import json


class BaseProvider:
    def __init__(self, model):
        self.model = model

    def score_job(self, *, scoring_prompt, candidate_profile, job_description,
                  schema, max_tokens=2000, temperature=0):
        """Return the parsed assessment dict, or {"_error": ...} on failure."""
        raise NotImplementedError

    @staticmethod
    def parse_json(text):
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return {"_error": "unparseable response", "_raw": (text or "")[:500]}

    @staticmethod
    def system_text(scoring_prompt, candidate_profile):
        """Single combined system string, for providers without a cached system."""
        return f"{scoring_prompt}\n\n{candidate_profile}"
