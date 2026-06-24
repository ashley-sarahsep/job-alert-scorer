"""Offline tests for output.py (ranked summary formatting)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import output  # noqa: E402


def job(jid, title, company, score, rec, board="LinkedIn", salary="",
        ats_url=None, board_url="https://linkedin.com/jobs/view/1",
        stretch=False, angle="", hard_blockers=None, ats=None):
    dr = {"source": "email_snippet", "source_url": board_url}
    if ats_url:
        dr = {"source": "greenhouse", "source_url": ats_url}
    return {
        "job_id": jid, "title": title, "company": company, "board": board,
        "salary": salary, "url": board_url, "description_result": dr,
        "score_result": {
            "score": score, "recommendation": rec,
            "fit_summary": f"Summary for {title}.",
            "key_alignments": ["alignment a"], "key_gaps": ["gap b"],
            "unique_match_signals": ["signal c"], "hard_blockers": hard_blockers or [],
            "interesting_stretch": stretch, "transferable_angle": angle,
            "compensation": "In range", "location": "Compatible",
            "ats_keywords": ats or {"already_covered": [], "add_to_resume": [],
                                    "mirror_phrasing": []},
        },
    }


JOBS = [
    job("1", "Implementation Manager", "Globex", 9, "Apply",
        ats_url="https://boards.greenhouse.io/globex/jobs/9"),
    job("2", "Customer Success Manager", "Acme", 6, "Consider", salary="$120K"),
    job("5", "Field Ops Lead", "FranchiseCo", 5, "Consider", stretch=True,
        angle="Distributed-workforce platform work maps directly."),
    job("3", "Backend Engineer", "DevCo", 2, "Pass"),
    {"job_id": "4", "title": "Broken", "company": "X",
     "score_result": {"_error": "refusal"}},  # errored: excluded everywhere
]


def test_grouping_and_ordering():
    strong, stretch, consider, passes = output.group_jobs(JOBS, min_highlight=7)
    assert [j["job_id"] for j in strong] == ["1"], strong
    assert [j["job_id"] for j in stretch] == ["5"], stretch
    assert [j["job_id"] for j in consider] == ["2"], consider
    assert [j["job_id"] for j in passes] == ["3"], passes


def test_apply_link_prefers_careers_page():
    assert output.apply_link(JOBS[0]).endswith("/jobs/9")
    assert output.apply_link(JOBS[1]) == "https://linkedin.com/jobs/view/1"


def test_markdown_and_email_have_stretch_section():
    md = output.render_markdown(JOBS, "2026-06-18", min_highlight=7)
    assert "## Worth a Shot - Transferable Stretches" in md
    assert "Distributed-workforce platform work maps directly." in md

    subject, html_body, text_body = output.render_email(JOBS, "2026-06-18", 7)
    assert "Worth a Shot" in html_body
    assert "1 strong fit, 1 worth a shot" in subject
    assert "WORTH A SHOT" in text_body


def test_csv_rows():
    import csv
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "out.csv")
        output.write_csv(JOBS, path, "2026-06-18")
        with open(path, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    assert len(rows) == 4  # errored job excluded
    assert rows[0]["Company"] == "Globex"
    assert rows[0]["Score"] == "9"
    stretch_row = next(r for r in rows if r["Company"] == "FranchiseCo")
    assert stretch_row["Worth a shot"] == "yes"


def test_skipped_summary_shows_matched_keyword_sorted_by_company():
    jobs = list(JOBS) + [
        {"job_id": "s1", "title": "Senior Software Engineer", "company": "Zeta",
         "filter_skipped": True, "filter_skip_match": "software engineer"},
        {"job_id": "s2", "title": "Director, Data Science", "company": "Acorn",
         "filter_skipped": True, "filter_skip_match": "director"},
    ]
    subject, html_body, text_body = output.render_email(jobs, "2026-06-18", 7)
    assert "Skipped by Title Filter (2 jobs)" in html_body
    assert 'matched skip: "software engineer"' in html_body
    assert "SKIPPED BY TITLE FILTER (2 jobs)" in text_body
    assert html_body.index("Acorn") < html_body.index("Zeta")  # sorted by company


def test_html_escaping():
    j = job("9", "Manager <script>", "A & B Co", 8, "Apply")
    _, html_body, _ = output.render_email([j], "2026-06-18")
    assert "<script>" not in html_body
    assert "&lt;script&gt;" in html_body
    assert "A &amp; B Co" in html_body


def test_ats_keywords_only_for_strong_fits():
    ats = {"already_covered": ["onboarding", "HubSpot"],
           "add_to_resume": ["change management", "stakeholder mapping"],
           "mirror_phrasing": ["drive adoption across the organization"]}
    strong = job("a1", "Onboarding Lead", "Globex", 8, "Apply", ats=ats)
    weak = job("a2", "Ops Coordinator", "Acme", 6, "Consider", ats=ats)

    # The helper gates on score >= 7, regardless of populated keywords.
    assert output.ats_keywords(strong["score_result"]) == ats
    assert output.ats_keywords(weak["score_result"]) is None

    md = output.render_markdown([strong, weak], "2026-06-18", min_highlight=7)
    assert "ATS keywords" in md
    assert "change management" in md
    assert "drive adoption across the organization" in md

    _, html_body, text_body = output.render_email([strong, weak], "2026-06-18", 7)
    assert "ATS keywords" in html_body
    assert "stakeholder mapping" in html_body
    assert "ATS add to resume" in text_body

    # A 6/10 job must never show an ATS block even if keywords are present.
    assert "ATS keywords" not in output.render_markdown([weak], "2026-06-18", 7)


def main():
    test_grouping_and_ordering()
    test_apply_link_prefers_careers_page()
    test_markdown_and_email_have_stretch_section()
    test_csv_rows()
    test_skipped_summary_shows_matched_keyword_sorted_by_company()
    test_html_escaping()
    test_ats_keywords_only_for_strong_fits()
    print("All output tests passed.")


if __name__ == "__main__":
    main()
