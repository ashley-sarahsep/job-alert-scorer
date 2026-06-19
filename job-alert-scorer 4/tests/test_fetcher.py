"""Offline tests for job_fetcher, run without network access.

    python tests/test_fetcher.py

A FakeSession returns canned ATS responses keyed by URL, so the full lookup
logic (slug guessing, ATS response parsing, title matching, snippet fallback)
is exercised exactly as it would be against the live APIs.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import job_fetcher as jf  # noqa: E402


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400 and self.status_code != 404:
            raise jf.requests.HTTPError(f"status {self.status_code}")


class FakeSession:
    """Maps URL -> (status, payload). Unknown URLs return 404."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        for fragment, (status, payload) in self.routes.items():
            if fragment in url:
                return FakeResponse(status, payload)
        return FakeResponse(404, None)


# --- slug generation ---------------------------------------------------------

def test_slug_candidates():
    assert jf.slug_candidates("Capital One") == ["capitalone", "capital-one", "capital"]
    assert jf.slug_candidates("Klara Inc.") == ["klara"]
    assert jf.slug_candidates("Oyster®") == ["oyster"]
    assert jf.slug_candidates("") == []


# --- title matching ----------------------------------------------------------

def test_title_matching():
    postings = [
        {"title": "Staff Software Engineer", "description": "x"},
        {"title": "Senior People Partner, Americas", "description": "y"},
    ]
    match, score = jf.best_match(postings, "Senior People Partner")
    assert match["title"] == "Senior People Partner, Americas", (match, score)
    assert score >= 0.9, score

    match, score = jf.best_match(postings, "Director of Sales")
    assert match is None, (match, score)


def test_html_to_text():
    txt = jf.html_to_text("&lt;p&gt;Own onboarding.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Do X&lt;/li&gt;&lt;/ul&gt;")
    assert "Own onboarding." in txt
    assert "Do X" in txt
    assert "<" not in txt


# --- end-to-end lookup with fake ATS responses -------------------------------

def test_greenhouse_hit():
    routes = {
        "boards-api.greenhouse.io/v1/boards/acmecloud/jobs": (200, {
            "jobs": [
                {"title": "Implementation Manager",
                 "location": {"name": "Remote - Canada"},
                 "content": "&lt;p&gt;Own enterprise onboarding end to end.&lt;/p&gt;",
                 "absolute_url": "https://boards.greenhouse.io/acmecloud/jobs/123"},
            ]
        }),
    }
    session = FakeSession(routes)
    job = {"company": "Acme Cloud Inc", "title": "Implementation Manager", "snippet": "s", "url": "u"}
    res = jf.fetch_description(job, session=session, delay=0)
    assert res["source"] == "greenhouse", res
    assert res["partial"] is False, res
    assert "enterprise onboarding" in res["description"], res
    assert res["source_url"].endswith("/123"), res


def test_lever_hit_after_greenhouse_miss():
    routes = {
        # greenhouse: board exists but no matching title
        "boards-api.greenhouse.io/v1/boards/globex/jobs": (200, {"jobs": [
            {"title": "Office Manager", "location": {"name": "NYC"},
             "content": "x", "absolute_url": "g"}]}),
        "api.lever.co/v0/postings/globex": (200, [
            {"text": "Executive Business Partner",
             "categories": {"location": "Toronto"},
             "descriptionPlain": "Support the CEO and run the office of the CEO.",
             "hostedUrl": "https://jobs.lever.co/globex/abc"},
        ]),
    }
    session = FakeSession(routes)
    job = {"company": "Globex", "title": "Executive Business Partner", "snippet": "s", "url": "u"}
    res = jf.fetch_description(job, session=session, delay=0)
    assert res["source"] == "lever", res
    assert "office of the CEO" in res["description"], res


def test_snippet_fallback_when_no_board():
    session = FakeSession({})  # every board 404s
    job = {"company": "Tiny Startup", "title": "Chief of Staff",
           "snippet": "Run point on cross-team initiatives.", "url": "u"}
    res = jf.fetch_description(job, session=session, delay=0)
    assert res["source"] == "email_snippet", res
    assert res["partial"] is True, res
    assert res["insufficient"] is False, res
    assert "cross-team" in res["description"], res


def test_insufficient_when_no_board_and_no_snippet():
    session = FakeSession({})
    job = {"company": "Ghost Co", "title": "Phantom Role", "snippet": "", "url": "u"}
    res = jf.fetch_description(job, session=session, delay=0)
    assert res["source"] == "none", res
    assert res["insufficient"] is True, res


# --- web-search fallback (Claude) ----------------------------------------------

class FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeMessage:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [FakeBlock(text)]
        self.stop_reason = stop_reason


class FakeMessages:
    def __init__(self, reply):
        self._reply = reply
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return FakeMessage(self._reply)


class FakeClient:
    def __init__(self, reply):
        self.messages = FakeMessages(reply)


def test_web_search_used_when_ats_misses():
    session = FakeSession({})  # no ATS board
    reply = (
        "FOUND: yes\n"
        "SOURCE_URL: https://jobs.lever.co/acme/eng-mgr\n"
        "DESCRIPTION:\n"
        "Lead the implementation team and own enterprise onboarding."
    )
    client = FakeClient(reply)
    job = {"company": "Acme", "title": "Implementation Manager", "snippet": "s", "url": "u"}
    res = jf.fetch_description(job, session=session, delay=0, client=client, model="claude-sonnet-4-6")
    assert res["source"] == "web_search", res
    assert res["source_url"].endswith("/eng-mgr"), res
    assert "enterprise onboarding" in res["description"], res
    assert res["partial"] is False, res


def test_web_search_not_found_falls_through_to_snippet():
    session = FakeSession({})
    client = FakeClient("FOUND: no")
    job = {"company": "Ghost", "title": "Phantom", "snippet": "snippet text", "url": "u"}
    res = jf.fetch_description(job, session=session, delay=0, client=client, model="m")
    assert res["source"] == "email_snippet", res
    assert "snippet text" in res["description"], res


def test_web_search_parse_no():
    assert jf._parse_search_response("FOUND: no") is None
    assert jf._parse_search_response("FOUND: yes\nSOURCE_URL: x\nDESCRIPTION:\n  ") is None


def test_board_cache_avoids_refetch():
    routes = {"boards-api.greenhouse.io/v1/boards/acme/jobs": (200, {"jobs": []})}
    session = FakeSession(routes)
    cache = {}
    job = {"company": "Acme", "title": "X", "snippet": "s", "url": "u"}
    jf.fetch_description(job, session=session, board_cache=cache, delay=0)
    calls_after_first = len(session.calls)
    jf.fetch_description(job, session=session, board_cache=cache, delay=0)
    # Second call should hit the cache, not re-request the same boards.
    assert len(session.calls) == calls_after_first, session.calls


def main():
    test_slug_candidates()
    test_title_matching()
    test_html_to_text()
    test_greenhouse_hit()
    test_lever_hit_after_greenhouse_miss()
    test_snippet_fallback_when_no_board()
    test_insufficient_when_no_board_and_no_snippet()
    test_web_search_used_when_ats_misses()
    test_web_search_not_found_falls_through_to_snippet()
    test_web_search_parse_no()
    test_board_cache_avoids_refetch()
    print("All fetcher tests passed.")


if __name__ == "__main__":
    main()
