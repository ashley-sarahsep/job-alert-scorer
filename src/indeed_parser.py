"""Parse job listings out of Indeed job-alert emails.

Targets Indeed's saved-search alert emails (sender donotreply@jobalert.indeed.com).
Indeed uses several layouts in these emails:

  - Standard organic results: links to /rc/clk/dl?jk=<jobkey>
  - Sponsored results: links to /pagead/clk/dl?ad=<token> (no visible job key)
  - Single-job and multi-job ("<Title> at <Company> and N more ...") variants

Rather than rely on the (inconsistent) HTML nesting, we read the email's text
in document order: locate each job's title link, then collect the text
fragments that follow it up to the next job. A job card lays out as:

    "Senior Recruiter - Business Analytics"        # title
    "Capital One"                                  # company
    "3.9"                                          # rating (optional)
    "Austin, TX"                                   # location
    "$65,581-$101,626 a year"                      # salary (optional)
    "This will include creating compelling…"        # snippet
    "7 days ago"                                    # posted age

Indeed's "jobs similar to you" emails (donotreply@match.indeed.com) use opaque
cts.indeed.com redirect links with no stable job id and are not handled here.

Returned dicts match the LinkedIn parser's shape (job_id, title, company,
location, salary, url, snippet, posted, warnings, source).
"""

import hashlib
import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

JK_RE = re.compile(r"[?&]jk=([0-9A-Za-z]+)")
RATING_RE = re.compile(r"^\d(?:\.\d)?$")
POSTED_RE = re.compile(
    r"(just posted|today|^posted$|\d+\+?\s*(?:hour|hours|day|days|week|weeks|month|months)\s+ago)",
    re.IGNORECASE,
)
SALARY_RE = re.compile(
    r"([$€£]\s?[\d,.]+)"
    r"|(\b(?:a|an|per)\s+(?:year|month|week|hour)\b)"
    r"|(/\s?(?:yr|year|hr|hour|mo|month))",
    re.IGNORECASE,
)

# Exact fragments that are never a company/location/snippet.
_NOISE = {
    "view job",
    "view jobs",
    "view jobs:",
    "view all",
    "view all jobs",
    "easily apply",
    "easy apply",
    "apply now",
    "save",
    "new",
    "-",
    "since yesterday",
    "for last 7 days",
    "unsubscribe",
}

# Fragments that mark the end of the job list (footer / alert chrome). When we
# hit one of these while collecting a job's fields, we stop.
_STOP = (
    "view all jobs",
    "view jobs",
    "edit this job alert",
    "manage job alerts",
    "these job ads match",
    "refined by",
    "unsubscribe",
    "indeed terms",
    "help centre",
    "privacy policy",
)

# Work-arrangement words plus a ", XX" state/province code (checked separately)
# cover location lines region-neutrally.
_LOCATION_HINTS = ("remote", "hybrid", "on-site", "onsite", "anywhere")


def _is_noise(text):
    t = text.strip().lower()
    return (not t) or (t in _NOISE) or t.startswith("view ")


def _is_stop(text):
    t = text.lower()
    return any(t.startswith(s) for s in _STOP)


def _looks_like_salary(text):
    return bool(SALARY_RE.search(text))


def _is_posted(text):
    return bool(POSTED_RE.search(text))


def _looks_like_location(text):
    t = text.lower()
    if any(h in t for h in _LOCATION_HINTS):
        return True
    return bool(re.search(r",\s*[A-Z]{2}\b", text))


def _anchor_key(href):
    """Return a stable grouping key for a job-link anchor, or None if not a job.

    Organic links carry ?jk=<jobkey>; sponsored links carry ?ad=<token>. Both
    forms can appear twice per job (image + title link), so we group by key.
    """
    m = JK_RE.search(href)
    if m:
        return ("jk", m.group(1))
    if "/pagead/clk" in href:
        ad = parse_qs(urlparse(href).query).get("ad", [""])[0]
        return ("ad", ad[:24] or href[:60])
    return None


def _canonical_url(key, href):
    kind, value = key
    if kind == "jk":
        return f"https://ca.indeed.com/viewjob?jk={value}"
    return href  # sponsored: keep the tracking redirect (resolves to the job)


def parse_job_alert(html, source_label=""):
    """Return a list of job dicts parsed from one Indeed alert email."""
    soup = BeautifulSoup(html or "", "html.parser")

    # Ordered, de-duplicated list of job anchors: (key, clean_title, url).
    anchors = []
    for a in soup.find_all("a", href=True):
        key = _anchor_key(a["href"])
        if key is None:
            continue
        text = a.get_text(" ", strip=True)
        anchors.append((key, text, a["href"]))

    # Group anchors by key; the clean title is the shortest non-empty text
    # (sponsored cards have a long "Title Company Location $..." blob link plus
    # a short title-only link).
    by_key = {}
    order = []
    for key, text, href in anchors:
        if key not in by_key:
            by_key[key] = {"titles": [], "href": href}
            order.append(key)
        if text:
            by_key[key]["titles"].append(text)

    jobs_meta = []
    for key in order:
        titles = [t for t in by_key[key]["titles"] if t]
        if not titles:
            continue
        clean_title = min(titles, key=len)
        jobs_meta.append((key, clean_title, _canonical_url(key, by_key[key]["href"])))

    if not jobs_meta:
        return []

    # Walk the email's text in order and slice the fragments belonging to each
    # job (from its title up to the next job's title).
    frags = [f.strip() for f in soup.stripped_strings if f.strip()]
    title_positions = []
    cursor = 0
    for _key, clean_title, _url in jobs_meta:
        pos = next((i for i in range(cursor, len(frags)) if frags[i] == clean_title), None)
        title_positions.append(pos)
        if pos is not None:
            cursor = pos + 1

    jobs = {}
    for idx, (key, clean_title, url) in enumerate(jobs_meta):
        pos = title_positions[idx]
        if pos is None:
            continue
        # End slice at the next located title, capped so a trailing job doesn't
        # swallow the footer.
        next_pos = next((p for p in title_positions[idx + 1:] if p is not None), None)
        end = min(next_pos if next_pos is not None else len(frags), pos + 9)
        record = _classify(clean_title, frags[pos + 1:end], key, url)

        if record["job_id"] not in jobs:
            jobs[record["job_id"]] = record

    result = list(jobs.values())
    for job in result:
        job["source"] = source_label
    return result


def _classify(title, slice_frags, key, url):
    company = location = salary = posted = ""
    snippet_parts = []
    for frag in slice_frags:
        if _is_stop(frag):
            break
        if frag == title or _is_noise(frag) or RATING_RE.match(frag):
            continue
        if not salary and _looks_like_salary(frag):
            salary = frag
            continue
        if not posted and _is_posted(frag):
            posted = frag
            continue
        if not company:
            company = frag
            continue
        if not location and _looks_like_location(frag):
            location = frag
            continue
        snippet_parts.append(frag)

    # If no company was shown, a location can land in the company slot; fix it.
    if company and not location and _looks_like_location(company):
        company, location = "", company

    kind, value = key
    if kind == "jk":
        job_id = value
    else:
        # Sponsored: no stable job key, so derive one from company+title for
        # cross-email dedup.
        digest = hashlib.sha1(f"{company}|{title}".encode("utf-8")).hexdigest()[:12]
        job_id = f"ad-{digest}"

    warnings = []
    if not company:
        warnings.append("company not found")
    if not location:
        warnings.append("location not found")

    return {
        "job_id": job_id,
        "title": title,
        "company": company,
        "location": location,
        "salary": salary,
        "url": url,
        "snippet": " ".join(snippet_parts).strip(),
        "posted": posted,
        "warnings": warnings,
    }
