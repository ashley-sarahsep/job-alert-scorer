"""Offline tests for linkedin_parser, run without Gmail or network access.

    python tests/test_parser.py

Covers the two layouts seen in real LinkedIn alert emails:
  1. Anchor-internal: title / "Company · Location" / status all inside one <a>
     (the current format), including a salary line.
  2. Sibling layout: company/location in elements next to the title anchor
     (older/alternate format), exercised via the card fallback.
Also checks deduplication of the same job repeated across cards.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from linkedin_parser import parse_job_alert  # noqa: E402
from indeed_parser import parse_job_alert as parse_indeed  # noqa: E402
from deduplication import dedupe_jobs  # noqa: E402

# 1. Current LinkedIn format: everything inside the job-view anchor.
ANCHOR_INTERNAL = """
<html><body>
<a href="https://www.linkedin.com/comm/jobs/view/4429706742?trk=eml-x">
  <table><tr><td>
    <span>Senior People Partner</span>
    <span>Remitly · Austin, Texas, United States</span>
    <span>Actively recruiting</span>
  </td></tr></table>
</a>
<a href="https://www.linkedin.com/comm/jobs/view/4379272114?trk=eml-x">
  <table><tr><td>
    <span>Customer Activation | Partnerships</span>
    <span>Ramp · Greater Boston Area, United States (Remote)</span>
    <span>$116K-$177K / year</span>
    <span>Actively recruiting</span>
  </td></tr></table>
</a>
</body></html>
"""

# 2. Older sibling layout: company/location sit beside the title anchor.
SIBLING_LAYOUT = """
<html><body>
<table><tr><td>
  <a href="https://www.linkedin.com/comm/jobs/view/3812345678/?trk=eml-x">Implementation Manager</a>
  <div>Acme Cloud Inc · Remote (US)</div>
  <div>Actively recruiting</div>
  <a href="https://www.linkedin.com/comm/jobs/view/3812345678/?trk=eml-btn">View job</a>
</td></tr></table>
<table><tr><td>
  <a href="https://www.linkedin.com/comm/jobs/view/3812345678/?trk=eml-dupe">Implementation Manager</a>
  <div>Acme Cloud Inc · Remote (US)</div>
</td></tr></table>
</body></html>
"""


def _by_id(jobs):
    return {j["job_id"]: j for j in jobs}


def test_anchor_internal():
    jobs = _by_id(dedupe_jobs(parse_job_alert(ANCHOR_INTERNAL, "test")))
    assert len(jobs) == 2, jobs

    a = jobs["4429706742"]
    assert a["title"] == "Senior People Partner", a
    assert a["company"] == "Remitly", a
    assert a["location"] == "Austin, Texas, United States", a
    assert a["salary"] == "", a
    assert a["warnings"] == [], a

    b = jobs["4379272114"]
    assert b["title"] == "Customer Activation | Partnerships", b  # '|' in title preserved
    assert b["company"] == "Ramp", b
    assert b["location"] == "Greater Boston Area, United States (Remote)", b
    assert b["salary"] == "$116K-$177K / year", b


def test_sibling_layout_and_dedup():
    jobs = dedupe_jobs(parse_job_alert(SIBLING_LAYOUT, "test"))
    assert len(jobs) == 1, jobs  # same job repeated -> one record
    j = jobs[0]
    assert j["title"] == "Implementation Manager", j
    assert j["company"] == "Acme Cloud Inc", j
    assert j["location"] == "Remote (US)", j
    assert j["url"] == "https://www.linkedin.com/jobs/view/3812345678/", j


# 3. Indeed: an organic (jk) card and a sponsored (pagead) card. Text is read
#    in document order, so fields follow the title.
INDEED_ALERT = """
<html><body>
<table><tr><td>
  <a href="https://ca.indeed.com/rc/clk/dl?jk=8113cad67ff68807&from=ja">Senior Recruiter - Business Analytics</a>
  <span>Capital One</span>
  <span>3.9</span>
  <span>Austin, TX</span>
  <span>This will include sourcing diverse candidate pipelines…</span>
  <span>7 days ago</span>
</td></tr>
<tr><td>
  <a href="https://ca.indeed.com/pagead/clk/dl?mo=r&ad=ABCdef123456">Chief of Staff Klara Inc. Remote</a>
  <a href="https://ca.indeed.com/pagead/clk/dl?mo=r&ad=ABCdef123456">Chief of Staff</a>
  <span>Klara Inc.</span>
  <span>Remote</span>
  <span>$65,581-$101,626 a year</span>
  <span>Run point on cross-team initiatives…</span>
  <span>10 days ago</span>
  <a href="https://ca.indeed.com/jobs?q=x">View all jobs</a>
</td></tr></table>
</body></html>
"""


def test_indeed_organic_and_sponsored():
    jobs = _by_id(parse_indeed(INDEED_ALERT, "test"))
    assert len(jobs) == 2, jobs

    organic = jobs["8113cad67ff68807"]
    assert organic["title"] == "Senior Recruiter - Business Analytics", organic
    assert organic["company"] == "Capital One", organic
    assert organic["location"] == "Austin, TX", organic
    assert organic["posted"] == "7 days ago", organic
    assert organic["salary"] == "", organic
    assert organic["warnings"] == [], organic
    assert organic["url"] == "https://ca.indeed.com/viewjob?jk=8113cad67ff68807", organic

    # Sponsored card: shortest link text is the clean title; id is synthesised.
    sponsored = next(j for k, j in jobs.items() if k.startswith("ad-"))
    assert sponsored["title"] == "Chief of Staff", sponsored
    assert sponsored["company"] == "Klara Inc.", sponsored
    assert sponsored["location"] == "Remote", sponsored
    assert sponsored["salary"] == "$65,581-$101,626 a year", sponsored
    assert "View all jobs" not in sponsored["snippet"], sponsored  # footer not bled in


def main():
    test_anchor_internal()
    test_sibling_layout_and_dedup()
    test_indeed_organic_and_sponsored()
    print("All parser tests passed.")


if __name__ == "__main__":
    main()
