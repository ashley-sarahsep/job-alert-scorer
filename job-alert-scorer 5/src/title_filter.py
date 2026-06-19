"""Title pre-filter: decide which jobs are worth scoring, by title alone.

Two keyword lists (in config):
  - skip_title_keywords: skip the job if its title contains any of these.
  - keep_title_keywords: but keep (score) it anyway if it also contains one of
    these - so "Director of Implementation" survives while "Director, Data
    Science" is skipped. Keep overrides skip.

Matching is case-insensitive substring matching on the title only. Skipped jobs
are never fetched or scored (saving API cost), but are still listed in the
output so a genuine exception can be reviewed by hand.
"""


def matched_skip(job, skip_keywords, keep_keywords=()):
    """Return the skip keyword that filters this title out, or None.

    Returns the matched keyword (trimmed) so the output can show why a job was
    skipped. A keep keyword anywhere in the title overrides the skip.
    """
    title = (job.get("title") or "").lower()
    if any(k.lower() in title for k in keep_keywords if k):
        return None
    for k in skip_keywords:
        if k and k.lower() in title:
            return k.strip()
    return None


def title_filtered(job, skip_keywords, keep_keywords=()):
    """True if the title should be skipped (not scored)."""
    return matched_skip(job, skip_keywords, keep_keywords) is not None


def skipped_jobs(jobs):
    """Jobs set aside by the title pre-filter, sorted by company then title."""
    skipped = [j for j in jobs if j.get("filter_skipped")]
    return sorted(skipped, key=lambda j: ((j.get("company") or "").lower(),
                                          (j.get("title") or "").lower()))
