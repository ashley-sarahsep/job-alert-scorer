"""Offline tests for the title pre-filter."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from title_filter import matched_skip, title_filtered, skipped_jobs  # noqa: E402


def test_skip_and_keep():
    skip = ["software engineer", "director", "head of", " vp ", "vp,"]
    keep = ["enablement", "implementation"]

    def j(t):
        return {"title": t}

    # plain skips return the matched keyword
    assert matched_skip(j("Staff Software Engineer"), skip, keep) == "software engineer"
    assert matched_skip(j("Director, Data Science"), skip, keep) == "director"
    assert matched_skip(j("VP, Engineering"), skip, keep) == "vp,"
    # keep-word rescues a senior title in a target area
    assert title_filtered(j("Director of Implementation"), skip, keep) is False
    assert title_filtered(j("Head of Sales Enablement"), skip, keep) is False
    # Chief of Staff is never caught (not in skip list)
    assert title_filtered(j("Chief of Staff"), skip, keep) is False
    assert title_filtered(j("Executive Business Partner"), skip, keep) is False


def test_skipped_jobs_sorted_by_company():
    jobs = [
        {"company": "Zeta", "title": "A", "filter_skipped": True},
        {"company": "Acorn", "title": "B", "filter_skipped": True},
        {"company": "Beta", "title": "C"},  # not skipped
    ]
    assert [j["company"] for j in skipped_jobs(jobs)] == ["Acorn", "Zeta"]


def main():
    test_skip_and_keep()
    test_skipped_jobs_sorted_by_company()
    print("All title_filter tests passed.")


if __name__ == "__main__":
    main()
