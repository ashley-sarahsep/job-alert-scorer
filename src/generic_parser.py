"""A best-effort generic parser for job-alert emails from boards we don't have a
dedicated parser for (anything other than LinkedIn and Indeed).

Every board formats its alert emails differently, so this parser is deliberately
heuristic. It first tries to read job links and the text around them straight
from the HTML. If that finds nothing and an AI extractor is supplied, it falls
back to asking the model to pull the postings out of the email text.

It only needs to recover a title and company (and a link if there is one) - the
rest of the pipeline fetches the full description from the company's careers page
and scores that. Treat the results as best-effort and sanity-check the first few
runs; for a board you rely on, a dedicated parser (see CONTRIBUTING) is better.

Returns the same job-dict shape as the LinkedIn / Indeed parsers, and always
gives each job a unique, non-empty job_id so dedupe keeps distinct roles.
"""

import hashlib
import json
import re

from bs4 import BeautifulSoup

# href fragments that usually mean "this link is a job posting".
_JOB_URL_HINTS = (
    "/job", "/jobs/", "viewjob", "jk=", "currentjobid", "/postings/",
    "greenhouse.io", "lever.co", "ashbyhq", "smartrecruiters", "workable",
    "/careers", "/apply", "/job-detail",
)

# Anchor text that is navigation/CTA, not a job title. Matched at the START with
# word boundaries, so a real title like "Operations Manager" isn't caught by the
# word "manage".
_SKIP_RE = re.compile(
    r"^\s*(view|see|apply|manage|update|unsubscribe|settings|learn more|"
    r"read more|sign in|sign up|log in|log out|go to|browse)\b", re.I)


def _clean(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def _job_id(url, title, company):
    """Stable, unique id: the numeric id in the URL if present, else a hash."""
    m = re.search(r"(\d{6,})", url or "")
    if m:
        return m.group(1)
    basis = f"{(url or '').strip().lower()}|{title.lower()}|{company.lower()}"
    return "g" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def _looks_like_job_link(href):
    h = (href or "").lower()
    return bool(h) and any(hint in h for hint in _JOB_URL_HINTS)


def _is_skip_text(text):
    return bool(_SKIP_RE.match(text or ""))


def _split_company_location(text):
    """"Company - Location" lines use a few different separators."""
    for sep in (" · ", " • ", " — ", " | ", " - "):
        if sep in text:
            a, b = text.split(sep, 1)
            return _clean(a), _clean(b)
    return _clean(text), ""


def _heuristic_extract(body, source_label):
    soup = BeautifulSoup(body, "html.parser")
    jobs, seen = [], set()
    for a in soup.find_all("a", href=True):
        title = _clean(a.get_text())
        if not title or len(title) > 120 or _is_skip_text(title):
            continue
        if not _looks_like_job_link(a["href"]):
            continue
        # Company / location usually sit just after the title in the job's card.
        company, location = "", ""
        card = a.find_parent(["td", "li", "div", "table", "p"]) or a.parent
        if card is not None:
            frags = [f for f in (_clean(s) for s in card.stripped_strings)
                     if f and f != title]
            if frags:
                company, location = _split_company_location(frags[0])
        url = a["href"].split("?")[0] if a["href"].startswith("http") else a["href"]
        jid = _job_id(url, title, company)
        if jid in seen:
            continue
        seen.add(jid)
        jobs.append({
            "job_id": jid, "title": title, "company": company,
            "location": location, "salary": "", "url": url, "snippet": "",
            "warnings": ["generic heuristic parse - verify fields"],
            "source": source_label,
        })
    return jobs


_AI_PROMPT = (
    "You are extracting job postings from a job-alert email. From the email text "
    "below, return ONLY a JSON array of objects, one per distinct job posting, "
    "each with the keys: title, company, location, url. Use an empty string for "
    "any field you cannot find. Ignore navigation, footers, ads, and "
    "'unsubscribe' links - include only real job listings. Output nothing except "
    "the JSON array.\n\nEMAIL:\n"
)


def ai_extract(body, source_label, client, model):
    """Fallback: ask an Anthropic client to extract postings from the email text.

    `client` is an anthropic.Anthropic instance (see anthropic_client.get_client);
    `model` is the model name. Returns the same job-dict shape as the heuristic.
    """
    text = BeautifulSoup(body, "html.parser").get_text("\n")
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()[:20000]
    resp = client.messages.create(
        model=model, max_tokens=2000,
        messages=[{"role": "user", "content": _AI_PROMPT + text}],
    )
    raw = "".join(getattr(b, "text", "") for b in resp.content
                  if getattr(b, "type", "") == "text")
    match = re.search(r"\[.*\]", raw, re.S)
    if not match:
        return []
    try:
        items = json.loads(match.group(0))
    except (json.JSONDecodeError, TypeError):
        return []
    jobs, seen = [], set()
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        title = _clean(it.get("title"))
        if not title:
            continue
        company = _clean(it.get("company"))
        url = _clean(it.get("url"))
        jid = _job_id(url, title, company)
        if jid in seen:
            continue
        seen.add(jid)
        jobs.append({
            "job_id": jid, "title": title, "company": company,
            "location": _clean(it.get("location")), "salary": "", "url": url,
            "snippet": "", "warnings": ["generic AI parse"],
            "source": source_label,
        })
    return jobs


def parse_job_alert(body, source_label="", ai_extractor=None):
    """Heuristic first; fall back to ai_extractor(body, source_label) if empty.

    ai_extractor is an optional callable (built by the caller so this module
    stays provider-agnostic). If it's absent or errors, we return whatever the
    heuristic found (possibly nothing).
    """
    jobs = _heuristic_extract(body, source_label)
    if jobs or ai_extractor is None:
        return jobs
    try:
        return ai_extractor(body, source_label) or []
    except Exception:  # noqa: BLE001 - never let a parse failure crash the run
        return []
