#!/usr/bin/env python3
"""Job Alert Scorer - command-line entry point.

Reads job-alert emails from Gmail, fetches the full job descriptions, scores
each job for fit against a candidate profile (via a configurable AI provider),
and writes / emails a ranked summary.

Config is loaded from --config, then the JOB_SCORER_CONFIG env var, then the
bundled config/config.yaml. All personal files (profile, credentials, caches)
are referenced from the config and resolved relative to it, so you can keep them
in a private folder and run:

    python src/main.py --config ~/my-job-scorer-config/config.yaml --score --email
"""

import argparse
import datetime
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_loader import load_config  # noqa: E402
from gmail_reader import (  # noqa: E402
    get_html_body, get_header, get_message, get_profile_email, get_service,
    search_message_ids, send_email,
)
from linkedin_parser import parse_job_alert as parse_linkedin  # noqa: E402
from indeed_parser import parse_job_alert as parse_indeed  # noqa: E402
from job_fetcher import fetch_description, load_cache, save_cache  # noqa: E402
from deduplication import dedupe_jobs  # noqa: E402
from title_filter import matched_skip  # noqa: E402
from scorer import score_jobs  # noqa: E402
from providers import get_provider  # noqa: E402
import output  # noqa: E402

PARSERS = {"linkedin": parse_linkedin, "indeed": parse_indeed}


def parse_since(value):
    if value is None:
        return None
    value = value.strip().lower()
    match = re.fullmatch(r"(\d+)([dhm])", value)
    if match:
        amount = int(match.group(1))
        unit_seconds = {"d": 86400, "h": 3600, "m": 60}[match.group(2)]
        return int(time.time()) - amount * unit_seconds
    if value.isdigit():
        return int(value)
    raise ValueError(f"Could not understand --since value: {value!r}")


def load_last_run(path):
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh).get("last_run_epoch")
        except (json.JSONDecodeError, OSError):
            return None
    return None


def save_last_run(path, epoch):
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"last_run_epoch": int(epoch)}, fh)


def build_query(base_query, after_epoch):
    return f"{base_query} after:{int(after_epoch)}" if after_epoch else base_query


def get_sources(config):
    if config.get("sources"):
        return config["sources"]
    raise ValueError("config must define a 'sources' list (name/query/parser).")


def dump_raw_emails(service, msg_ids, out_dir, prefix):
    os.makedirs(out_dir, exist_ok=True)
    for i, msg_id in enumerate(msg_ids, start=1):
        message = get_message(service, msg_id)
        body, kind = get_html_body(message)
        subject = get_header(message, "Subject")
        ext = "html" if kind == "html" else "txt"
        path = os.path.join(out_dir, f"{prefix}_alert_{i:02d}.{ext}")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        print(f"  saved {path}  ({kind}, subject: {subject!r})")


def enrich_with_descriptions(jobs, config, limit=None, use_web_search=False):
    """Attach a full (or partial) job description to each job, with a disk cache."""
    import requests

    cache = load_cache(config.get("fetch_cache_file"))
    session = requests.Session()
    board_cache = {}
    delay = config.get("fetch_delay_seconds", 2.0)

    client = None
    model = None
    if use_web_search:
        from anthropic_client import get_client
        client = get_client()
        scoring = config.get("scoring", {})
        model = (scoring.get("model") if scoring.get("provider", "anthropic") == "anthropic"
                 else "claude-sonnet-4-6")

    targets = jobs[:limit] if limit else jobs
    counts = {"full": 0, "partial": 0, "insufficient": 0, "cached": 0}
    print(f"\nFetching descriptions for {len(targets)} job(s) "
          f"(delay {delay}s between calls; cached results reused)...\n")
    for i, job in enumerate(targets, start=1):
        jid = job["job_id"]
        if jid in cache:
            result = cache[jid]
            counts["cached"] += 1
        else:
            result = fetch_description(job, session=session, board_cache=board_cache,
                                       delay=delay, client=client, model=model)
            cache[jid] = result
        job["description_result"] = result
        if result["insufficient"]:
            counts["insufficient"] += 1
            tag = "INSUFFICIENT"
        elif result["partial"]:
            counts["partial"] += 1
            tag = f"partial ({result['source']})"
        else:
            counts["full"] += 1
            tag = f"FULL via {result['source']} (match {result['match_score']})"
        print(f"  {i:>3}/{len(targets)}  {tag:32}  {job['title'][:42]} @ {job.get('company','')}")

    save_cache(config.get("fetch_cache_file"), cache)
    print(f"\nFetch summary: {counts['full']} full, {counts['partial']} partial "
          f"(snippet only), {counts['insufficient']} insufficient "
          f"({counts['cached']} served from cache).")
    return jobs


def print_ranked(jobs, min_highlight=7):
    scored = [j for j in jobs if j.get("score_result") and "_error" not in j["score_result"]]
    errored = [j for j in jobs if j.get("score_result", {}).get("_error")]
    scored.sort(key=lambda j: j["score_result"]["score"], reverse=True)

    print(f"\n{'='*70}\nRANKED RESULTS ({len(scored)} scored)\n{'='*70}")
    for job in scored:
        r = job["score_result"]
        tag = " *" if r["score"] >= min_highlight else ""
        if r.get("interesting_stretch") and not r.get("hard_blockers") and r["score"] < min_highlight:
            tag = " ~ worth a shot"
        print(f"\n[{r['score']}/10] {r['recommendation']:8} {job['title']} - "
              f"{job.get('company','')} [{job.get('board','')}]{tag}")
        print(f"   {r['fit_summary']}")
        if r.get("transferable_angle"):
            print(f"   Worth a shot: {r['transferable_angle']}")
        print(f"   Compensation: {r['compensation']} | Location: {r['location']}")
        if r.get("hard_blockers"):
            print(f"   Hard blockers: {', '.join(r['hard_blockers'])}")
        print(f"   {job.get('url','')}")

    if errored:
        print(f"\n{len(errored)} job(s) could not be scored:")
        for job in errored:
            print(f"   ! {job['title']} - {job.get('company','')}: {job['score_result']['_error']}")


def print_jobs(jobs):
    if not jobs:
        print("\nNo jobs extracted.")
        return
    print(f"\nExtracted {len(jobs)} unique job(s):\n")
    for i, job in enumerate(jobs, start=1):
        board = job.get("board", "")
        print(f"{i:>2}. {job.get('title') or '(no title)'}  [{board}]" if board
              else f"{i:>2}. {job.get('title') or '(no title)'}")
        print(f"    Company:  {job.get('company') or '(unknown)'}")
        print(f"    Location: {job.get('location') or '(unknown)'}")
        if job.get("salary"):
            print(f"    Salary:   {job['salary']}")
        print(f"    URL:      {job.get('url')}")


def build_parser():
    p = argparse.ArgumentParser(description="Job Alert Scorer")
    p.add_argument("--config", metavar="PATH",
                   help="Path to config.yaml (else JOB_SCORER_CONFIG, else config/config.yaml).")
    p.add_argument("--all", action="store_true", help="Ignore last-run; read recent alerts.")
    p.add_argument("--since", metavar="WINDOW", help="Only alerts newer than e.g. 7d, 36h, 120m.")
    p.add_argument("--limit", type=int, default=None, help="Max alert emails to read.")
    p.add_argument("--dump-raw", type=int, metavar="N", default=0,
                   help="Save N raw alert emails for parser tuning and exit.")
    p.add_argument("--no-update", action="store_true", help="Don't advance the last-run timestamp.")
    p.add_argument("--source", metavar="NAME", help="Only process the named source.")
    p.add_argument("--fetch", action="store_true", help="Retrieve full job descriptions.")
    p.add_argument("--limit-fetch", type=int, metavar="N", default=None,
                   help="With --fetch, only fetch the first N descriptions.")
    p.add_argument("--web-search", action="store_true",
                   help="With --fetch, use Claude web search for careers pages the ATS lookup "
                        "misses (needs ANTHROPIC_API_KEY; adds cost).")
    p.add_argument("--score", action="store_true",
                   help="Score each job for fit (implies fetch; needs the provider's API key).")
    p.add_argument("--email", action="store_true", help="Email the ranked summary to yourself.")
    p.add_argument("--no-files", action="store_true", help="With --score, don't write CSV/markdown.")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    try:
        config = load_config(args.config)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        sources = get_sources(config)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.source:
        sources = [s for s in sources if s["name"].lower() == args.source.lower()]
        if not sources:
            print(f"ERROR: no source named {args.source!r} in config.", file=sys.stderr)
            return 1

    try:
        service = get_service(config["credentials_file"], config["token_file"])
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.since:
        after_epoch = parse_since(args.since)
    elif args.all or args.dump_raw:
        after_epoch = None
    else:
        after_epoch = load_last_run(config.get("last_run_file"))

    max_emails = args.limit or config.get("max_jobs_per_run", 50)
    run_started = int(time.time())
    all_jobs = []

    for source in sources:
        parse_fn = PARSERS.get(source.get("parser"))
        if parse_fn is None:
            print(f"  ! unknown parser {source.get('parser')!r} for {source['name']!r}; skipping.")
            continue
        query = build_query(source["query"], after_epoch)
        print(f"\n[{source['name']}] query: {query!r}")
        msg_ids = search_message_ids(service, query, max_results=max_emails)
        print(f"[{source['name']}] matched {len(msg_ids)} alert email(s).")

        if args.dump_raw:
            n = min(args.dump_raw, len(msg_ids))
            if n:
                print(f"  dumping {n} raw email(s) to ./raw_emails/:")
                dump_raw_emails(service, msg_ids[:n],
                                os.path.join(os.getcwd(), "raw_emails"),
                                prefix=source["name"].lower())
            continue

        source_jobs = []
        for msg_id in msg_ids:
            message = get_message(service, msg_id)
            subject = get_header(message, "Subject")
            date = get_header(message, "Date")
            body, kind = get_html_body(message)
            if kind == "none" or not body:
                print(f"  ! skipped email (no readable body): {subject!r}")
                continue
            jobs = parse_fn(body, source_label=f"{subject} | {date}")
            if not jobs:
                print(f"  ! no jobs parsed from: {subject!r}")
            for job in jobs:
                job["board"] = source["name"]
            source_jobs.extend(jobs)
        print(f"[{source['name']}] parsed {len(source_jobs)} job listing(s).")
        all_jobs.extend(source_jobs)

    if args.dump_raw:
        return 0

    unique_jobs = dedupe_jobs(all_jobs)
    print(f"\nParsed {len(all_jobs)} job listing(s) total, {len(unique_jobs)} after dedupe.")
    print_jobs(unique_jobs)

    # Title pre-filter (scoring runs only).
    if args.score:
        skip_kw = config.get("skip_title_keywords", [])
        keep_kw = config.get("keep_title_keywords", [])
        for job in unique_jobs:
            match = matched_skip(job, skip_kw, keep_kw)
            job["filter_skipped"] = match is not None
            job["filter_skip_match"] = match
        skipped = [j for j in unique_jobs if j["filter_skipped"]]
        if skipped:
            print(f"\nSkipping {len(skipped)} job(s) by title filter (saves scoring cost):")
            for j in skipped:
                print(f"   - {j.get('title','')} @ {j.get('company','')} "
                      f"(matched: \"{j.get('filter_skip_match')}\")")
    to_process = [j for j in unique_jobs if not j.get("filter_skipped")]

    if args.fetch or args.score:
        enrich_with_descriptions(to_process, config, limit=args.limit_fetch,
                                 use_web_search=args.web_search)

    if args.score:
        min_highlight = config.get("min_score_to_highlight", 7)
        scoring = config.get("scoring", {})
        try:
            provider = get_provider(scoring.get("provider", "anthropic"), scoring.get("model"))
        except (ValueError, RuntimeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        score_jobs(to_process, config, provider)
        print_ranked(to_process, min_highlight=min_highlight)

        run_date = datetime.date.today().isoformat()
        if not args.no_files:
            md_path, csv_path = output.write_outputs(
                unique_jobs, config.get("output_directory", "./results"), run_date, min_highlight)
            print(f"\nWrote:\n  {md_path}\n  {csv_path}")
        if args.email:
            subject, html_body, text_body = output.render_email(unique_jobs, run_date, min_highlight)
            to_addr = config.get("email_to") or get_profile_email(service)
            send_email(service, to_addr, subject, html_body, text_body)
            print(f"\nEmailed summary to {to_addr}.")
    elif args.fetch:
        print("\nDescriptions fetched. Add --score to score fit.")
    else:
        print("\nRead only. Use --fetch for descriptions, --score to score fit.")

    if not args.no_update and not args.since and not args.all and not args.dump_raw:
        save_last_run(config.get("last_run_file"), run_started)
        print(f"\nUpdated last-run timestamp to {run_started}.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
