"""Offline tests for the best-effort generic parser."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from generic_parser import parse_job_alert  # noqa: E402

# Each job in its own card (how real alert emails are usually laid out).
GENERIC_EMAIL = """
<html><body>
  <table><tr><td>
    <a href="https://jobs.example.com/viewjob?jk=12345678">Operations Manager</a>
    <div>Globex Corp &middot; Remote (US)</div>
  </td></tr></table>
  <table><tr><td>
    <a href="https://boards.greenhouse.io/acme/jobs/99887766">Implementation Lead</a>
    <div>Acme Cloud &middot; Austin, TX</div>
  </td></tr></table>
  <a href="https://example.com/unsubscribe">Unsubscribe</a>
  <a href="https://example.com/about">About us</a>
</body></html>
"""


def test_heuristic_extracts_jobs():
    jobs = parse_job_alert(GENERIC_EMAIL, source_label="test")
    by_title = {j["title"]: j for j in jobs}
    assert "Operations Manager" in by_title, jobs
    assert "Implementation Lead" in by_title, jobs
    # navigation / unsubscribe links are ignored
    assert "Unsubscribe" not in by_title and "About us" not in by_title, jobs
    # company captured from the "Company · Location" line
    assert by_title["Operations Manager"]["company"] == "Globex Corp", jobs
    assert by_title["Implementation Lead"]["company"] == "Acme Cloud", jobs
    # numeric ids pulled from the URLs; all unique and non-empty
    ids = [j["job_id"] for j in jobs]
    assert all(ids) and len(ids) == len(set(ids)), ids


def test_ai_fallback_used_when_heuristic_finds_nothing():
    no_links = "<html><body><p>You have 2 new jobs. Log in to view them.</p></body></html>"
    calls = []

    def fake_ai(body, label):
        calls.append(label)
        return [{"job_id": "x1", "title": "Role", "company": "Co", "location": "",
                 "salary": "", "url": "", "snippet": "", "warnings": [], "source": label}]

    jobs = parse_job_alert(no_links, source_label="t", ai_extractor=fake_ai)
    assert calls == ["t"], calls
    assert jobs and jobs[0]["title"] == "Role", jobs


def test_no_links_and_no_ai_returns_empty():
    assert parse_job_alert("<html><body>nothing here</body></html>", source_label="t") == []


if __name__ == "__main__":
    test_heuristic_extracts_jobs()
    test_ai_fallback_used_when_heuristic_finds_nothing()
    test_no_links_and_no_ai_returns_empty()
    print("All generic parser tests passed.")
