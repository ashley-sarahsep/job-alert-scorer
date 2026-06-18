"""AI scoring logic, provider-agnostic.

Holds the scoring rubric and the structured-output schema, assembles the
candidate profile and per-job prompt, then delegates the actual model call to a
provider (Anthropic, OpenAI, Google, Groq). Post-processing (score clamping and
the hard-blocker cap) happens here so it's consistent across providers.
"""

import os
import time

from job_fetcher import load_cache, save_cache

# The scoring rubric. The model returns its assessment through SCORE_SCHEMA.
RUBRIC = """You are a job fit assessment tool. You are given a candidate profile and a \
job posting. Score the fit on a scale of 1-10 and provide brief reasoning.

SCORING RUBRIC:
- 9-10: Strong fit. Core requirements align with the candidate's verified \
experience. No hard blockers. Compensation in range. Worth applying immediately.
- 7-8: Good fit with manageable gaps. Most requirements match. Gaps are soft \
(learnable skills, adjacent experience) not hard (wrong profession, wrong domain \
entirely). Worth applying.
- 5-6: Partial fit. Some alignment but significant gaps in experience level, \
domain, or specific required skills. Could be worth applying if the candidate is \
interested in the company, but expectations should be realistic.
- 3-4: Weak fit. The role requires fundamentally different experience, a \
different career track, or has hard blockers.
- 1-2: Not a fit. Wrong profession, wrong level entirely, or requirements that \
cannot be addressed.

HARD BLOCKERS (automatic score cap of 4):
- Role requires proficiency in SQL, Python, or data engineering (candidate is \
currently learning, not proficient)
- Role requires hands-on coding or software engineering
- Role requires formal people management of 10+ direct reports
- Role requires deep domain expertise in healthcare, fintech, cybersecurity, or \
developer tools
- Role requires Salesforce administration depth (candidate has familiarity, not \
admin-level)
- Role is director/VP level at a company with 200+ employees
- Role requires a specific degree the candidate does not have (e.g., MBA \
required, not preferred)

SOFT GAPS (note but don't treat as blockers):
- Single employer history (candidate has a strong explanation)
- Lack of formal certifications (candidate is self-taught on all systems)
- Small team experience (scaling is about logic, not team size)
- Industry-specific terminology the candidate hasn't used but has equivalent \
experience

UNIQUE MATCH SIGNALS (flag these positively):
- "Build from scratch" / "no existing processes" language - strong match
- "Ambiguity" / "figure things out" / "founder mentality" - strong match
- AI adoption, AI enablement, deploying AI to non-technical users - direct match
- Cross-functional coordination, bridging technical and business teams - core \
strength
- Enterprise client management, client onboarding, customer success - strong match
- Training programme design, enablement content, documentation - strong match
- Remote-first or async culture
- Growth-stage company - ideal environment match
- Chief of Staff or executive support - direct experience
- Executive Business Partner / EA roles - strong target

COMPENSATION CHECK:
- Use the candidate profile's stated target. US remote roles paying in USD: \
check if the company hires Canadian contractors or uses an EOR. If compensation \
is listed and clearly below the candidate's floor, flag as below range.

LOCATION CHECK:
- Use the candidate profile's stated location and commuting tolerance. Remote \
roles open to the candidate's country are fully compatible. Do not lower the \
numeric score for an acceptable or light-hybrid location; reflect location in \
the location field, not the score.

TRANSFERABLE STRETCH FLAG (separate from the score):
Set interesting_stretch = true when the role is NOT a clean requirements match \
(so it would not score 7+) but the candidate's transferable experience makes it \
genuinely worth applying to anyway ("same architecture, different vocabulary": \
a role in a new industry whose underlying work mirrors what they have done). Do \
NOT set it for roles with a hard blocker, or a genuinely wrong profession or \
level. Do not inflate the numeric score to surface these; that is what this flag \
is for. When interesting_stretch = true, set transferable_angle to one sentence \
on the bridge; otherwise leave transferable_angle as an empty string.

IMPORTANT: The candidate profile may have two parts: a Reference Handbook and an \
Addendum. When they conflict, the ADDENDUM TAKES PRIORITY - follow it.

Base every judgement on the candidate's verified experience. Do not invent \
qualifications. Apply the hard-blocker score cap when a hard blocker is present."""

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "description": "Overall fit, 1-10"},
        "fit_summary": {"type": "string", "description": "2-3 sentences on why this score"},
        "key_alignments": {"type": "array", "items": {"type": "string"}},
        "key_gaps": {"type": "array", "items": {"type": "string"}},
        "unique_match_signals": {"type": "array", "items": {"type": "string"}},
        "hard_blockers": {
            "type": "array", "items": {"type": "string"},
            "description": "Hard blockers present, if any (these cap the score at 4)",
        },
        "interesting_stretch": {
            "type": "boolean",
            "description": "Not a clean match, but transferable experience makes it "
                           "worth applying to anyway",
        },
        "transferable_angle": {
            "type": "string",
            "description": "One sentence on why it transfers (only when "
                           "interesting_stretch is true; else empty)",
        },
        "compensation": {
            "type": "string",
            "enum": ["In range", "Above range", "Below range", "Not listed"],
        },
        "location": {
            "type": "string",
            "enum": ["Compatible", "Potential issue", "Not compatible"],
        },
        "recommendation": {"type": "string", "enum": ["Apply", "Consider", "Pass"]},
    },
    "required": [
        "score", "fit_summary", "key_alignments", "key_gaps",
        "unique_match_signals", "hard_blockers", "interesting_stretch",
        "transferable_angle", "compensation", "location", "recommendation",
    ],
    "additionalProperties": False,
}


def load_profile(config):
    """Read the candidate handbook (and optional addendum) named in config."""
    with open(config["candidate_profile"], "r", encoding="utf-8") as fh:
        handbook = fh.read()
    addendum = ""
    addendum_path = config.get("candidate_addendum")
    if addendum_path and os.path.exists(addendum_path):
        with open(addendum_path, "r", encoding="utf-8") as fh:
            addendum = fh.read()
    return handbook, addendum


def build_candidate_profile(handbook, addendum):
    profile = "CANDIDATE PROFILE - REFERENCE HANDBOOK:\n\n" + handbook
    if addendum:
        profile += ("\n\n=== CANDIDATE PROFILE - ADDENDUM (takes priority on "
                    "conflicts) ===\n\n" + addendum)
    return profile


def build_job_description_text(job, description):
    parts = [
        f"JOB TITLE: {job.get('title', '')}",
        f"COMPANY: {job.get('company', '')}",
        f"LOCATION: {job.get('location', '') or 'Not specified'}",
    ]
    if job.get("salary"):
        parts.append(f"COMPENSATION (from listing): {job['salary']}")
    parts.append(f"SOURCE BOARD: {job.get('board', '')}")
    parts.append("")
    parts.append("JOB DESCRIPTION:")
    parts.append(description or "(no description available)")
    return "\n".join(parts)


def score_one(provider, candidate_profile, job, description, max_tokens=2000, temperature=0):
    """Score a single job via the provider, then clamp and apply the blocker cap."""
    result = provider.score_job(
        scoring_prompt=RUBRIC,
        candidate_profile=candidate_profile,
        job_description=build_job_description_text(job, description),
        schema=SCORE_SCHEMA,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    if "_error" in result:
        return result
    try:
        result["score"] = max(1, min(10, int(result.get("score", 0))))
    except (TypeError, ValueError):
        result["score"] = 0
    if result.get("hard_blockers"):
        result["score"] = min(result["score"], 4)
    return result


def score_jobs(jobs, config, provider):
    """Score every job that has a usable description; reuse cached scores."""
    handbook, addendum = load_profile(config)
    candidate_profile = build_candidate_profile(handbook, addendum)

    scoring = config.get("scoring", {})
    max_tokens = scoring.get("max_tokens", 2000)
    temperature = scoring.get("temperature", 0)
    delay = scoring.get("delay_seconds", 2.0)

    cache_path = config.get("scored_cache_file")
    cache = load_cache(cache_path)

    scorable = [j for j in jobs if not j.get("description_result", {}).get("insufficient")]
    print(f"\nScoring {len(scorable)} job(s) with {provider.model} "
          f"(cached scores reused; {delay}s between calls)...\n")

    for job in scorable:
        jid = job["job_id"]
        if jid in cache:
            job["score_result"] = cache[jid]
            continue
        description = (job.get("description_result") or {}).get("description", "")
        try:
            result = score_one(provider, candidate_profile, job, description,
                               max_tokens=max_tokens, temperature=temperature)
        except Exception as exc:  # noqa: BLE001 - one failure shouldn't kill the run
            result = {"_error": str(exc)}
        job["score_result"] = result
        if "_error" not in result:
            cache[jid] = result
        if delay:
            time.sleep(delay)

    save_cache(cache_path, cache)
    return jobs
