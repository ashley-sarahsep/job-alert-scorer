"""Offline tests for scorer (provider-agnostic), using a fake provider."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import scorer  # noqa: E402
from providers.anthropic_provider import _wants_temperature  # noqa: E402

GOOD = {
    "score": 8, "fit_summary": "Strong fit.",
    "key_alignments": ["a"], "key_gaps": ["b"], "unique_match_signals": ["c"],
    "hard_blockers": [], "interesting_stretch": False, "transferable_angle": "",
    "compensation": "In range", "location": "Compatible", "recommendation": "Apply",
}

JOB = {"title": "Implementation Manager", "company": "Globex",
       "location": "Remote (US)", "salary": "$120K", "board": "LinkedIn", "url": "u"}


class FakeProvider:
    def __init__(self, payload):
        self.payload = payload
        self.model = "fake-model"
        self.last = None

    def score_job(self, **kwargs):
        self.last = kwargs
        return dict(self.payload)


def test_build_candidate_profile():
    p = scorer.build_candidate_profile("HANDBOOK_TEXT", "ADDENDUM_TEXT")
    assert "HANDBOOK_TEXT" in p and "ADDENDUM_TEXT" in p
    assert "takes priority" in p.lower()


def test_build_job_description_text():
    t = scorer.build_job_description_text(JOB, "Own onboarding end to end.")
    assert "Implementation Manager" in t and "Globex" in t
    assert "$120K" in t and "Own onboarding end to end." in t


def test_score_one_passes_prompt_and_clamps():
    fp = FakeProvider(GOOD)
    r = scorer.score_one(fp, "PROFILE", JOB, "desc", max_tokens=1500, temperature=0)
    assert r["score"] == 8 and r["recommendation"] == "Apply"
    assert fp.last["scoring_prompt"] == scorer.RUBRIC
    assert fp.last["candidate_profile"] == "PROFILE"
    assert fp.last["schema"] == scorer.SCORE_SCHEMA


def test_hard_blocker_caps_score():
    fp = FakeProvider(dict(GOOD, score=8, hard_blockers=["Requires SQL"]))
    assert scorer.score_one(fp, "p", JOB, "d")["score"] == 4


def test_score_clamped_to_range():
    fp = FakeProvider(dict(GOOD, score=99))
    assert scorer.score_one(fp, "p", JOB, "d")["score"] == 10


def test_error_passes_through():
    fp = FakeProvider({"_error": "refusal"})
    assert "_error" in scorer.score_one(fp, "p", JOB, "d")


def test_temperature_guard():
    assert _wants_temperature("claude-sonnet-4-6") is True
    assert _wants_temperature("claude-haiku-4-5") is True
    assert _wants_temperature("claude-opus-4-8") is False
    assert _wants_temperature("claude-fable-5") is False


def main():
    test_build_candidate_profile()
    test_build_job_description_text()
    test_score_one_passes_prompt_and_clamps()
    test_hard_blocker_caps_score()
    test_score_clamped_to_range()
    test_error_passes_through()
    test_temperature_guard()
    print("All scorer tests passed.")


if __name__ == "__main__":
    main()
