"""Deduplicate job postings across alert emails.

Job boards send the same role across multiple alerts. We dedupe first by the
board's job id, then by a normalised (company, title) key to catch the same role
re-posted under a new id or from a second board.
"""

import re


def dedupe_jobs(jobs):
    seen_ids = set()
    seen_keys = set()
    unique = []
    for job in jobs:
        jid = job.get("job_id")
        key = (
            re.sub(r"\s+", " ", (job.get("company") or "").strip().lower()),
            re.sub(r"\s+", " ", (job.get("title") or "").strip().lower()),
        )
        if jid in seen_ids:
            continue
        if key != ("", "") and key in seen_keys:
            continue
        seen_ids.add(jid)
        seen_keys.add(key)
        unique.append(job)
    return unique
