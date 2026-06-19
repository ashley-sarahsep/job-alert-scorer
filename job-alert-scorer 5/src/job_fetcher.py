"""Step 2: retrieve full job descriptions.

LinkedIn (and to a lesser extent Indeed) don't give us the full posting in the
alert email, and LinkedIn blocks automated access to job pages. The workaround,
per the architecture, is to find the role on the company's own careers page.

Most growth-stage companies host their careers page on a handful of applicant
tracking systems (ATS) that expose free, public JSON APIs. We derive a likely
"slug" from the company name, query those APIs, and match the alert's job title
against the postings we get back. This needs no API key and returns clean,
complete descriptions.

Lookup order for each job:
  1. Greenhouse, Lever, Ashby public board APIs (by company slug).
  2. If none match and a Claude client is supplied, use Claude with server-side
     web search to find the posting on a careers page slug-guessing didn't reach
     (find_via_search). This is opt-in via the CLI's --web-search flag.
  3. Otherwise fall back to the snippet from the alert email, flagged partial.
  4. If there's no usable snippet either, flag as insufficient information.

Network note: this talks to external hosts (boards-api.greenhouse.io,
api.lever.co, api.ashbyhq.com). It works on a normal machine; in a restricted
egress environment those hosts must be allowlisted.
"""

import difflib
import html
import json
import os
import re
import time

import requests
from bs4 import BeautifulSoup

# Company-name suffixes to drop when building a slug.
_SUFFIXES = {
    "inc", "inc.", "llc", "ltd", "ltd.", "limited", "corp", "corp.",
    "corporation", "co", "co.", "company", "gmbh", "plc", "ag", "sa", "srl",
    "the",
}

DEFAULT_TIMEOUT = 15
DEFAULT_DELAY = 2.0  # polite pause between network calls


# --------------------------------------------------------------------------- #
# Company name -> slug candidates
# --------------------------------------------------------------------------- #

def normalize_company(name):
    """Lowercase a company name and strip ®/™, punctuation, and legal suffixes."""
    name = (name or "").lower()
    name = name.replace("®", " ").replace("™", " ").replace("&", " and ")
    name = re.sub(r"[^a-z0-9\s-]", " ", name)
    words = [w for w in re.split(r"[\s-]+", name) if w and w not in _SUFFIXES]
    return words


def slug_candidates(name):
    """Return ordered, de-duplicated slug guesses for a company name.

    "Capital One"  -> ["capitalone", "capital-one", "capital"]
    "Klara Inc."   -> ["klara"]
    """
    words = normalize_company(name)
    if not words:
        return []
    cands = ["".join(words)]
    if len(words) > 1:
        cands.append("-".join(words))
        cands.append(words[0])
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


# --------------------------------------------------------------------------- #
# HTML / text helpers
# --------------------------------------------------------------------------- #

def html_to_text(value):
    """Convert an HTML (or HTML-escaped) description to readable plain text."""
    if not value:
        return ""
    text = html.unescape(value)
    soup = BeautifulSoup(text, "html.parser")
    out = soup.get_text("\n", strip=True)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def normalize_title(title):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (title or "").lower())).strip()


def title_score(target, candidate):
    """Similarity in [0, 1] between two job titles."""
    a, b = normalize_title(target), normalize_title(candidate)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    return difflib.SequenceMatcher(None, a, b).ratio()


def best_match(postings, target_title, threshold=0.6):
    """Pick the posting whose title best matches ``target_title``.

    ``postings`` is a list of dicts with at least a "title" key. Returns
    (posting, score) or (None, best_score) if nothing clears ``threshold``.
    """
    best, best_score = None, 0.0
    for p in postings:
        s = title_score(target_title, p.get("title", ""))
        if s > best_score:
            best, best_score = p, s
    if best is not None and best_score >= threshold:
        return best, best_score
    return None, best_score


# --------------------------------------------------------------------------- #
# ATS board fetchers -- each returns a list of normalized postings, or None if
# the board doesn't exist for that slug.
# --------------------------------------------------------------------------- #

def _get_json(session, url):
    resp = session.get(url, timeout=DEFAULT_TIMEOUT,
                       headers={"User-Agent": "Mozilla/5.0 job-alert-scorer"})
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def fetch_greenhouse(session, slug):
    data = _get_json(
        session, f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    )
    if not data or "jobs" not in data:
        return None
    out = []
    for j in data["jobs"]:
        out.append({
            "title": j.get("title", ""),
            "location": (j.get("location") or {}).get("name", ""),
            "description": html_to_text(j.get("content", "")),
            "url": j.get("absolute_url", ""),
            "ats": "greenhouse",
        })
    return out


def fetch_lever(session, slug):
    data = _get_json(session, f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if not isinstance(data, list):
        return None
    out = []
    for j in data:
        desc = j.get("descriptionPlain") or html_to_text(j.get("description", ""))
        out.append({
            "title": j.get("text", ""),
            "location": (j.get("categories") or {}).get("location", ""),
            "description": desc,
            "url": j.get("hostedUrl", ""),
            "ats": "lever",
        })
    return out


def fetch_ashby(session, slug):
    data = _get_json(
        session, f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
    )
    if not data or "jobs" not in data:
        return None
    out = []
    for j in data["jobs"]:
        desc = j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", ""))
        out.append({
            "title": j.get("title", ""),
            "location": j.get("location", ""),
            "description": desc,
            "url": j.get("jobUrl") or j.get("applyUrl", ""),
            "ats": "ashby",
        })
    return out


ATS_FETCHERS = (fetch_greenhouse, fetch_lever, fetch_ashby)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

_SEARCH_PROMPT = """Find the official job posting for this role and return its \
full description.

Role: {title}
Company: {company}

Instructions:
- Use web search to find the posting on the company's OWN careers page or its \
applicant tracking system (Greenhouse, Lever, Ashby, Workable, etc.).
- Do NOT use LinkedIn, Indeed, or job aggregators as the source.
- If you find it, fetch the page and extract the full job description text \
(responsibilities, requirements, about the role). Do not summarise.
- Respond in EXACTLY this format and nothing else:

FOUND: yes
SOURCE_URL: <the careers-page URL>
DESCRIPTION:
<the full job description text>

- If you cannot find an official posting, respond with exactly:
FOUND: no
"""

# Server-side web tools. Claude runs the searches/fetches on Anthropic's
# infrastructure, so this works even where direct egress to careers sites is
# blocked, as long as api.anthropic.com is reachable.
_WEB_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search"},
    {"type": "web_fetch_20260209", "name": "web_fetch"},
]


def _parse_search_response(text):
    if re.search(r"FOUND:\s*no", text, re.IGNORECASE) and not re.search(
        r"FOUND:\s*yes", text, re.IGNORECASE
    ):
        return None
    url_match = re.search(r"SOURCE_URL:\s*(\S+)", text, re.IGNORECASE)
    desc_match = re.search(r"DESCRIPTION:\s*(.+)", text, re.IGNORECASE | re.DOTALL)
    description = desc_match.group(1).strip() if desc_match else ""
    if not description:
        return None
    return {
        "description": description,
        "source": "web_search",
        "source_url": url_match.group(1).strip() if url_match else "",
        "match_score": 0.0,
        "partial": False,
        "insufficient": False,
    }


def find_via_search(job, client, model, max_tokens=4000, max_turns=6):
    """Use Claude with server-side web search to find a careers-page description.

    Returns a description dict (same shape as fetch_description's result) or None
    if no official posting was found. Network errors are surfaced to the caller.
    """
    prompt = _SEARCH_PROMPT.format(title=job.get("title", ""), company=job.get("company", ""))
    messages = [{"role": "user", "content": prompt}]

    response = None
    for _ in range(max_turns):
        response = client.messages.create(
            model=model, max_tokens=max_tokens, messages=messages, tools=_WEB_TOOLS
        )
        # Server-tool loop hit its iteration cap; re-send to let it continue.
        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue
        break

    if response is None:
        return None
    text = "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    )
    return _parse_search_response(text)


def fetch_description(job, session=None, board_cache=None, delay=DEFAULT_DELAY,
                      fetchers=ATS_FETCHERS, client=None, model=None):
    """Resolve the fullest available description for one job.

    Returns a dict:
        {
          "description": "...",          # plain text (may be the email snippet)
          "source": "greenhouse"|"lever"|"ashby"|"email_snippet"|"none",
          "source_url": "...",
          "match_score": 0.0-1.0,        # title-match confidence (ATS hits only)
          "partial": bool,               # True when only a snippet was available
          "insufficient": bool,          # True when nothing usable was found
        }

    ``board_cache`` (a dict) memoizes (ats, slug) -> postings within a run so we
    don't re-hit the same board for every job at the same company.
    """
    session = session or requests.Session()
    board_cache = board_cache if board_cache is not None else {}
    company = job.get("company", "")
    title = job.get("title", "")

    for fetcher in fetchers:
        ats = fetcher.__name__.replace("fetch_", "")
        for slug in slug_candidates(company):
            cache_key = (ats, slug)
            if cache_key in board_cache:
                postings = board_cache[cache_key]
            else:
                try:
                    postings = fetcher(session, slug)
                except (requests.RequestException, ValueError, json.JSONDecodeError):
                    postings = None
                board_cache[cache_key] = postings
                if delay:
                    time.sleep(delay)
            if not postings:
                continue
            match, score = best_match(postings, title)
            if match:
                return {
                    "description": match["description"],
                    "source": ats,
                    "source_url": match.get("url", ""),
                    "match_score": round(score, 3),
                    "partial": not bool(match["description"]),
                    "insufficient": False,
                }

    # Fallback 2: ask Claude (with server-side web search) to find the posting
    # on a careers page that slug-guessing didn't reach.
    if client is not None and model:
        try:
            result = find_via_search(job, client, model)
        except Exception as exc:  # noqa: BLE001 - don't let one job kill the run
            result = None
            print(f"  ! web search failed for {job.get('title','')!r}: {exc}")
        if result:
            return result

    # Fallback 3: the snippet that came in the alert email.
    snippet = (job.get("snippet") or "").strip()
    if snippet:
        return {
            "description": snippet,
            "source": "email_snippet",
            "source_url": job.get("url", ""),
            "match_score": 0.0,
            "partial": True,
            "insufficient": False,
        }

    return {
        "description": "",
        "source": "none",
        "source_url": job.get("url", ""),
        "match_score": 0.0,
        "partial": True,
        "insufficient": True,
    }


# --------------------------------------------------------------------------- #
# Persistent cache (across runs) keyed by job_id
# --------------------------------------------------------------------------- #

def load_cache(path):
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_cache(path, cache):
    if not path:
        return
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh)
