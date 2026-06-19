"""Parse job listings out of LinkedIn job-alert emails.

LinkedIn alert emails are HTML and pack several jobs into one message. The
format is not documented and changes periodically, so this parser is
deliberately defensive: it extracts what it confidently can, records a warning
when a field looks unreliable, and never raises on a single malformed card.

In the current LinkedIn format, each job is wrapped in an <a href=".../jobs/
view/ID..."> whose visible text breaks into fragments like:

    ["Senior People Partner",
     "Remitly · Austin, Texas, United States",
     "Actively recruiting"]

i.e. title, then "Company · Location", then status/metadata (and sometimes a
salary line such as "$116K-$177K / year"). Older/alternate layouts put the
company line in a sibling element next to the anchor, so when the company isn't
found inside the anchor we fall back to scanning the surrounding card.

Each job is returned as a dict:
    {
        "job_id":   "4429706742",
        "title":    "Senior People Partner",
        "company":  "Remitly",
        "location": "Austin, Texas, United States",
        "salary":   "$116K-$177K / year",   # "" if not listed in the email
        "url":      "https://www.linkedin.com/jobs/view/4429706742/",
        "snippet":  "",                      # description text, if any
        "warnings": [],
        "source":   "<subject> | <date>",
    }

If a field comes through blank or wrong, dump a real email with
`python job_scorer.py --dump-raw 1` and adjust the heuristics here against the
saved HTML.
"""

import re

from bs4 import BeautifulSoup

JOB_VIEW_RE = re.compile(r"/jobs/view/(\d+)")

# Separators LinkedIn uses between company and location.
_SEP_RE = re.compile(r"\s+[·•|—–-]\s+")

# Link/label text that shows up inside job cards but is never a title/company.
_NOISE_EXACT = {
    "view job",
    "view jobs",
    "see all jobs",
    "see more jobs",
    "see all",
    "view all",
    "easy apply",
    "actively recruiting",
    "be an early applicant",
    "promoted",
    "reposted",
    "viewed",
    "unsubscribe",
}

# Metadata fragments to ignore for company/location/snippet purposes.
_META_RE = re.compile(
    r"(school alum|connection|mutual|"
    r"\bapplicant|\bapplied\b|early applicant|"
    r"actively recruiting|easy apply|be an early|promoted|reposted|"
    r"\bago\b|hours? ago|days? ago|weeks? ago)",
    re.IGNORECASE,
)

# Salary / compensation lines, e.g. "$116K-$177K / year", "CA$120,000/yr".
_SALARY_RE = re.compile(
    r"([$€£]\s?[\d,.]+\s?[kK]?)"
    r"|(/\s?(?:yr|year|hr|hour|mo|month))",
    re.IGNORECASE,
)


def _canonical_url(job_id):
    return f"https://www.linkedin.com/jobs/view/{job_id}/"


def _is_noise(text):
    t = text.strip().lower()
    return (not t) or (t in _NOISE_EXACT) or t.startswith("view ")


def _is_meta(text):
    return bool(_META_RE.search(text))


def _looks_like_salary(text):
    return bool(_SALARY_RE.search(text))


def _split_company_location(frag):
    """If ``frag`` looks like 'Company · Location', return (company, location)."""
    if _SEP_RE.search(frag):
        parts = _SEP_RE.split(frag, maxsplit=1)
        company = parts[0].strip()
        location = parts[1].strip() if len(parts) > 1 else ""
        return company, location
    return None


def _fields_from_fragments(frags, skip_first_as_title=True):
    """Pull company/location/salary/snippet from a list of text fragments.

    The first meaningful fragment is the title (when ``skip_first_as_title``);
    the rest are scanned for a 'Company · Location' line, a salary line, and any
    remaining free text (treated as a snippet).
    """
    meaningful = [f.strip() for f in frags if f.strip() and not _is_noise(f)]
    title = ""
    rest = meaningful
    if skip_first_as_title and meaningful:
        title = meaningful[0]
        rest = meaningful[1:]

    company = location = salary = ""
    snippet_parts = []
    for frag in rest:
        if frag == title:
            continue
        if not salary and _looks_like_salary(frag):
            salary = frag
            continue
        if not company:
            split = _split_company_location(frag)
            if split:
                company, location = split
                continue
        if _is_meta(frag):
            continue
        if not company and len(frag) < 60:
            company = frag
            continue
        snippet_parts.append(frag)

    return title, company, location, salary, " ".join(snippet_parts).strip()


def _distinct_job_ids(node):
    ids = set()
    for a in node.find_all("a", href=True):
        m = JOB_VIEW_RE.search(a["href"])
        if m:
            ids.add(m.group(1))
    return ids


def _nearest_card(anchor, job_id):
    """Largest ancestor of ``anchor`` that still refers to only this job.

    Used as a fallback for layouts where the company/location sits in a sibling
    element next to the title anchor rather than inside it. We climb while the
    ancestor mentions only this job's id, so we don't bleed in a neighbour.
    """
    node = anchor
    best = anchor
    for _ in range(10):
        parent = node.parent
        if parent is None or getattr(parent, "name", None) is None:
            break
        if _distinct_job_ids(parent) - {job_id}:
            break
        node = parent
        if getattr(node, "name", None) in ("td", "tr", "table"):
            best = node
    return best


def _richness(record):
    """Heuristic score so we keep the most complete record when a job repeats."""
    return (
        bool(record["title"])
        + bool(record["company"])
        + bool(record["location"])
        + bool(record["salary"])
        + bool(record["snippet"])
    )


def parse_job_alert(html, source_label=""):
    """Return a list of job dicts parsed from one LinkedIn alert email."""
    jobs = {}
    soup = BeautifulSoup(html or "", "html.parser")

    for anchor in soup.find_all("a", href=True):
        match = JOB_VIEW_RE.search(anchor["href"])
        if not match:
            continue
        job_id = match.group(1)

        # First try the anchor's own text (current LinkedIn format).
        frags = list(anchor.stripped_strings)
        title, company, location, salary, snippet = _fields_from_fragments(frags)

        # Fallback for layouts where company/location live beside the anchor.
        if title and not company:
            card = _nearest_card(anchor, job_id)
            card_frags = [f for f in card.stripped_strings if f.strip() != title]
            _, company, location, salary2, snippet2 = _fields_from_fragments(
                card_frags, skip_first_as_title=False
            )
            salary = salary or salary2
            snippet = snippet or snippet2

        warnings = []
        if title and not company:
            warnings.append("company not found")
        if title and not location:
            warnings.append("location not found")

        record = {
            "job_id": job_id,
            "title": title,
            "company": company,
            "location": location,
            "salary": salary,
            "url": _canonical_url(job_id),
            "snippet": snippet,
            "warnings": warnings,
        }

        existing = jobs.get(job_id)
        if existing is None or _richness(record) > _richness(existing):
            jobs[job_id] = record

    result = [j for j in jobs.values() if j["title"]]
    for job in result:
        job["source"] = source_label
    return result
