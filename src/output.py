"""Turn scored jobs into a ranked summary - markdown, CSV, and email.

Jobs are grouped by score into Strong Fits (>= highlight threshold), Worth a
Shot (transferable stretches), Worth Considering (5-6), and Passes (1-4),
highest first. The "apply link" prefers the company careers-page URL found in
the fetch step, falling back to the original board link. The dusty-rose email
also lists anything the title filter skipped.
"""

import csv
import html
import os

from title_filter import skipped_jobs


def apply_link(job):
    """Best link to actually apply: the careers page if we found one, else the
    original board URL."""
    dr = job.get("description_result") or {}
    if dr.get("source") in ("greenhouse", "lever", "ashby", "web_search") and dr.get("source_url"):
        return dr["source_url"]
    return job.get("url", "")


def _scored(jobs):
    return [j for j in jobs if j.get("score_result") and "_error" not in j["score_result"]]


def group_jobs(jobs, min_highlight=7):
    """Return (strong, stretch, consider, passes), each sorted by score desc.

    - strong:   score >= min_highlight (clean strong matches)
    - stretch:  below that, but flagged interesting_stretch with no hard blocker
                (transferable roles worth a shot) - surfaced out of the lower buckets
    - consider: remaining 5-6 scores not flagged as a stretch
    - passes:   everything else
    """
    scored = _scored(jobs)
    scored.sort(key=lambda j: j["score_result"]["score"], reverse=True)
    strong, stretch, consider, passes = [], [], [], []
    for j in scored:
        r = j["score_result"]
        score = r["score"]
        if score >= min_highlight:
            strong.append(j)
        elif r.get("interesting_stretch") and not r.get("hard_blockers"):
            stretch.append(j)
        elif score >= 5:
            consider.append(j)
        else:
            passes.append(j)
    return strong, stretch, consider, passes


def ats_keywords(r):
    """The ats_keywords dict if it has content, else None.

    Only surfaced for jobs scoring >= 7 (the model leaves the lists empty below
    that), so a low score or a provider that omits the field renders nothing.
    """
    a = r.get("ats_keywords") or {}
    if r.get("score", 0) >= 7 and any(
            a.get(k) for k in ("already_covered", "add_to_resume", "mirror_phrasing")):
        return a
    return None


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #

def _md_job(job):
    r = job["score_result"]
    lines = [
        f"### {job.get('title','')} - {job.get('company','')} (Score: {r['score']}/10)",
        f"**Recommendation:** {r['recommendation']}  ",
        f"**Compensation:** {r['compensation']}"
        f"{(' (' + job['salary'] + ')') if job.get('salary') else ''}  ",
        f"**Location:** {r['location']}  ",
        "",
        r["fit_summary"],
        "",
    ]
    if r.get("transferable_angle"):
        lines += [f"**Why it's worth a shot:** {r['transferable_angle']}", ""]
    if r.get("key_alignments"):
        lines.append("**Key alignments:**")
        lines += [f"- {a}" for a in r["key_alignments"]]
        lines.append("")
    if r.get("unique_match_signals"):
        lines.append("**Unique match signals:**")
        lines += [f"- {s}" for s in r["unique_match_signals"]]
        lines.append("")
    if r.get("transferability_notes"):
        lines += [f"**Transferability:** {r['transferability_notes']}", ""]
    if r.get("key_gaps"):
        lines.append("**Gaps to address:**")
        lines += [f"- {g}" for g in r["key_gaps"]]
        lines.append("")
    if r.get("hard_blockers"):
        lines.append("**Hard blockers:** " + "; ".join(r["hard_blockers"]))
        lines.append("")
    a = ats_keywords(r)
    if a:
        lines.append("**ATS keywords** (to tailor your resume if you apply):")
        if a.get("already_covered"):
            lines.append("- ✓ Already in your profile: " + ", ".join(a["already_covered"]))
        if a.get("add_to_resume"):
            lines.append("- ⊕ Add to your resume: " + ", ".join(a["add_to_resume"]))
        if a.get("mirror_phrasing"):
            lines.append("- ✎ Mirror this phrasing: "
                         + "; ".join(f'"{p}"' for p in a["mirror_phrasing"]))
        lines.append("")
    lines.append(f"**Apply:** {apply_link(job)}")
    lines.append("")
    return "\n".join(lines)


def render_markdown(jobs, run_date, min_highlight=7):
    strong, stretch, consider, passes = group_jobs(jobs, min_highlight)
    out = [f"# Job Alert Summary - {run_date}", ""]
    out.append(f"{len(strong)} strong fit(s), {len(stretch)} worth a shot, "
               f"{len(consider)} worth considering, {len(passes)} pass(es).")
    out.append("")

    out.append(f"## Strong Fits ({min_highlight}+)\n")
    out += [_md_job(j) for j in strong] or ["_None this run._\n"]

    out.append("## Worth a Shot - Transferable Stretches\n")
    out += [_md_job(j) for j in stretch] or ["_None this run._\n"]

    out.append("## Worth Considering (5-6)\n")
    out += [_md_job(j) for j in consider] or ["_None this run._\n"]

    out.append("## Passes (1-4)\n")
    if passes:
        for j in passes:
            r = j["score_result"]
            out.append(f"- **{j.get('company','')}** - {j.get('title','')} - "
                       f"{r['score']}/10 - {r['fit_summary']}")
    else:
        out.append("_None this run._")
    out.append("")

    skipped = skipped_jobs(jobs)
    if skipped:
        out.append(f"## Skipped by Title Filter ({len(skipped)} jobs)\n")
        for j in skipped:
            kw = j.get("filter_skip_match")
            tag = f' (matched skip: "{kw}")' if kw else ""
            out.append(f"- {j.get('title','')}, {j.get('company','')}{tag}")
        out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #

CSV_COLUMNS = [
    "Date found", "Company", "Job title", "Score", "Recommendation",
    "Worth a shot", "Compensation", "Location compatibility", "Fit summary",
    "Full assessment", "Source URL", "Status",
]


def _full_assessment(r):
    parts = []
    if r.get("transferable_angle"):
        parts.append("Worth a shot: " + r["transferable_angle"])
    if r.get("key_alignments"):
        parts.append("Alignments: " + "; ".join(r["key_alignments"]))
    if r.get("key_gaps"):
        parts.append("Gaps: " + "; ".join(r["key_gaps"]))
    if r.get("unique_match_signals"):
        parts.append("Signals: " + "; ".join(r["unique_match_signals"]))
    if r.get("transferability_notes"):
        parts.append("Transferability: " + r["transferability_notes"])
    if r.get("hard_blockers"):
        parts.append("Hard blockers: " + "; ".join(r["hard_blockers"]))
    a = ats_keywords(r)
    if a:
        if a.get("add_to_resume"):
            parts.append("ATS add: " + "; ".join(a["add_to_resume"]))
        if a.get("mirror_phrasing"):
            parts.append("ATS phrasing: " + "; ".join(a["mirror_phrasing"]))
    return " | ".join(parts)


def write_csv(jobs, path, run_date):
    strong, stretch, consider, passes = group_jobs(jobs)
    ordered = strong + stretch + consider + passes
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for job in ordered:
            r = job["score_result"]
            writer.writerow({
                "Date found": run_date,
                "Company": job.get("company", ""),
                "Job title": job.get("title", ""),
                "Score": r["score"],
                "Recommendation": r["recommendation"],
                "Worth a shot": "yes" if r.get("interesting_stretch") else "",
                "Compensation": r["compensation"]
                + (f" ({job['salary']})" if job.get("salary") else ""),
                "Location compatibility": r["location"],
                "Fit summary": r["fit_summary"],
                "Full assessment": _full_assessment(r),
                "Source URL": apply_link(job),
                "Status": "new",
            })


# --------------------------------------------------------------------------- #
# Email (HTML + plain text) -- dusty rose palette
# --------------------------------------------------------------------------- #

ROSE_DEEP = "#8b4a4a"     # strong accent / Apply
ROSE_MID = "#b57070"      # secondary accent / Consider
ROSE_SOFT = "#cf9a9a"     # light accent
ROSE_MUTED = "#b9a3a3"    # passes / muted
TEXT = "#3f2e2e"          # warm near-black
TEXT_MUTED = "#8a6f6f"    # muted rose-grey
BORDER = "#e6cccc"        # card border
CARD_BG = "#faf3f3"       # card background
BLOCKER = "#9a3b3b"       # hard blockers (slightly redder)


def _rec_colour(rec):
    return {"Apply": ROSE_DEEP, "Consider": ROSE_MID, "Pass": ROSE_MUTED}.get(rec, ROSE_MUTED)


def _html_job(job):
    r = job["score_result"]
    e = html.escape
    link = apply_link(job)
    comp = e(r["compensation"]) + (f" ({e(job['salary'])})" if job.get("salary") else "")
    parts = [
        f'<div style="margin:0 0 22px 0;padding:14px 16px;border:1px solid {BORDER};'
        f'border-radius:8px;background:{CARD_BG};">',
        f'<div style="font-size:16px;font-weight:600;color:{TEXT};">{e(job.get("title",""))} '
        f'&middot; {e(job.get("company",""))} '
        f'<span style="color:{_rec_colour(r["recommendation"])};">'
        f'[{r["score"]}/10 &middot; {e(r["recommendation"])}]</span></div>',
        f'<div style="color:{TEXT_MUTED};font-size:13px;margin:4px 0 8px;">'
        f'Compensation: {comp} &nbsp;|&nbsp; Location: {e(r["location"])} '
        f'&nbsp;|&nbsp; {e(job.get("board",""))}</div>',
        f'<div style="margin:8px 0;color:{TEXT};">{e(r["fit_summary"])}</div>',
    ]
    if r.get("transferable_angle"):
        parts.append(f'<div style="margin:8px 0;padding:8px 10px;background:#f3e3e3;'
                     f'border-left:3px solid {ROSE_MID};font-size:13px;color:{TEXT};">'
                     f'<b>Worth a shot:</b> {e(r["transferable_angle"])}</div>')
    if r.get("key_alignments"):
        items = "".join(f"<li>{e(a)}</li>" for a in r["key_alignments"])
        parts.append(f'<div style="font-size:13px;color:{TEXT};"><b>Alignments:</b>'
                     f'<ul style="margin:4px 0;">{items}</ul></div>')
    if r.get("unique_match_signals"):
        items = "".join(f"<li>{e(s)}</li>" for s in r["unique_match_signals"])
        parts.append(f'<div style="font-size:13px;color:{TEXT};"><b>Signals:</b>'
                     f'<ul style="margin:4px 0;">{items}</ul></div>')
    if r.get("transferability_notes"):
        parts.append(f'<div style="margin:8px 0;padding:8px 10px;background:#f6ecec;'
                     f'border-left:3px solid {ROSE_SOFT};font-size:13px;color:{TEXT};">'
                     f'<b>Transferability:</b> {e(r["transferability_notes"])}</div>')
    if r.get("key_gaps"):
        items = "".join(f"<li>{e(g)}</li>" for g in r["key_gaps"])
        parts.append(f'<div style="font-size:13px;color:{TEXT_MUTED};"><b>Gaps:</b>'
                     f'<ul style="margin:4px 0;">{items}</ul></div>')
    if r.get("hard_blockers"):
        parts.append(f'<div style="font-size:13px;color:{BLOCKER};"><b>Hard blockers:</b> '
                     f'{e("; ".join(r["hard_blockers"]))}</div>')
    a = ats_keywords(r)
    if a:
        rows = []
        if a.get("already_covered"):
            rows.append('<div style="margin-top:3px;"><b>✓ Already in your profile:</b> '
                        f'{e(", ".join(a["already_covered"]))}</div>')
        if a.get("add_to_resume"):
            rows.append('<div style="margin-top:3px;"><b>⊕ Add to your resume:</b> '
                        f'{e(", ".join(a["add_to_resume"]))}</div>')
        if a.get("mirror_phrasing"):
            phrases = "; ".join(f'“{p}”' for p in a["mirror_phrasing"])
            rows.append('<div style="margin-top:3px;"><b>✎ Mirror this phrasing:</b> '
                        f'{e(phrases)}</div>')
        parts.append('<div style="margin:8px 0;padding:8px 10px;background:#eef3ef;'
                     f'border-left:3px solid #6e928c;font-size:13px;color:{TEXT};">'
                     f'<b>ATS keywords</b>{"".join(rows)}</div>')
    if link:
        parts.append(f'<div style="margin-top:10px;"><a href="{e(link)}" '
                     f'style="background:{ROSE_DEEP};color:#fff;padding:7px 14px;border-radius:6px;'
                     f'text-decoration:none;font-size:13px;">Apply &rarr;</a></div>')
    parts.append("</div>")
    return "".join(parts)


def render_email(jobs, run_date, min_highlight=7):
    """Return (subject, html_body, text_body)."""
    strong, stretch, consider, passes = group_jobs(jobs, min_highlight)
    subject = (f"Job Alert Summary - {run_date} - {len(strong)} strong fit"
               f"{'s' if len(strong) != 1 else ''}"
               f"{f', {len(stretch)} worth a shot' if stretch else ''}")

    h = [f'<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;'
         f'max-width:680px;margin:0 auto;color:{TEXT};background:#fdf8f8;padding:20px;">',
         f'<h2 style="margin:0 0 4px;color:{ROSE_DEEP};">Job Alert Summary</h2>',
         f'<div style="color:{TEXT_MUTED};margin-bottom:16px;">{run_date} &middot; '
         f'{len(strong)} strong, {len(stretch)} worth a shot, '
         f'{len(consider)} worth considering, {len(passes)} passes</div>']

    h.append(f'<h3 style="border-bottom:2px solid {ROSE_DEEP};padding-bottom:4px;color:{TEXT};">'
             f'Strong Fits ({min_highlight}+)</h3>')
    h += [_html_job(j) for j in strong] or [f'<p style="color:{TEXT_MUTED};">None this run.</p>']

    h.append(f'<h3 style="border-bottom:2px solid {ROSE_MID};padding-bottom:4px;color:{TEXT};">'
             f'Worth a Shot - Transferable Stretches</h3>')
    h += [_html_job(j) for j in stretch] or [f'<p style="color:{TEXT_MUTED};">None this run.</p>']

    h.append(f'<h3 style="border-bottom:2px solid {ROSE_SOFT};padding-bottom:4px;color:{TEXT};">'
             f'Worth Considering (5-6)</h3>')
    h += [_html_job(j) for j in consider] or [f'<p style="color:{TEXT_MUTED};">None this run.</p>']

    h.append(f'<h3 style="border-bottom:2px solid {ROSE_MUTED};padding-bottom:4px;color:{TEXT};">'
             f'Passes (1-4)</h3>')
    if passes:
        rows = "".join(
            f'<li>{html.escape(j.get("company",""))} - {html.escape(j.get("title",""))} '
            f'({j["score_result"]["score"]}/10)</li>' for j in passes)
        h.append(f'<ul style="color:{TEXT_MUTED};font-size:13px;">{rows}</ul>')
    else:
        h.append(f'<p style="color:{TEXT_MUTED};">None this run.</p>')

    skipped = skipped_jobs(jobs)
    if skipped:
        h.append(f'<h3 style="border-bottom:1px solid {BORDER};padding-bottom:4px;'
                 f'color:{TEXT_MUTED};">Skipped by Title Filter ({len(skipped)} jobs)</h3>')
        items = []
        for j in skipped:
            kw = j.get("filter_skip_match")
            tag = (f' <span style="color:{ROSE_MUTED};">(matched skip: "{html.escape(kw)}")'
                   f'</span>') if kw else ""
            items.append(f'<li>{html.escape(j.get("title",""))}, '
                         f'{html.escape(j.get("company",""))}{tag}</li>')
        h.append(f'<ul style="color:{TEXT_MUTED};font-size:12px;">{"".join(items)}</ul>')
        h.append(f'<div style="color:{TEXT_MUTED};font-size:11px;">'
                 f'Not scored (saves cost). Edit skip_title_keywords / '
                 f'keep_title_keywords in your config to adjust.</div>')
    h.append('</div>')

    return subject, "".join(h), render_text(jobs, run_date, min_highlight)


def render_text(jobs, run_date, min_highlight=7):
    strong, stretch, consider, passes = group_jobs(jobs, min_highlight)
    out = [f"Job Alert Summary - {run_date}",
           f"{len(strong)} strong, {len(stretch)} worth a shot, "
           f"{len(consider)} worth considering, {len(passes)} passes", ""]
    sections = (("STRONG FITS", strong),
                ("WORTH A SHOT - TRANSFERABLE STRETCHES", stretch),
                ("WORTH CONSIDERING", consider))
    for header, group in sections:
        out.append(f"== {header} ==")
        if not group:
            out.append("  (none)")
        for j in group:
            r = j["score_result"]
            out.append(f"[{r['score']}/10] {r['recommendation']}: {j.get('title','')} - "
                       f"{j.get('company','')}")
            out.append(f"   {r['fit_summary']}")
            if r.get("transferable_angle"):
                out.append(f"   Worth a shot: {r['transferable_angle']}")
            if r.get("transferability_notes"):
                out.append(f"   Transferability: {r['transferability_notes']}")
            out.append(f"   Comp: {r['compensation']} | Location: {r['location']}")
            a = ats_keywords(r)
            if a:
                if a.get("already_covered"):
                    out.append("   ATS already covered: " + ", ".join(a["already_covered"]))
                if a.get("add_to_resume"):
                    out.append("   ATS add to resume: " + ", ".join(a["add_to_resume"]))
                if a.get("mirror_phrasing"):
                    out.append("   ATS mirror phrasing: " + "; ".join(a["mirror_phrasing"]))
            out.append(f"   Apply: {apply_link(j)}")
            out.append("")
    out.append("== PASSES ==")
    for j in passes:
        r = j["score_result"]
        out.append(f"  {r['score']}/10 {j.get('company','')} - {j.get('title','')}")
    skipped = skipped_jobs(jobs)
    if skipped:
        out.append("")
        out.append(f"== SKIPPED BY TITLE FILTER ({len(skipped)} jobs) ==")
        for j in skipped:
            kw = j.get("filter_skip_match")
            tag = f' (matched skip: "{kw}")' if kw else ""
            out.append(f"  {j.get('title','')}, {j.get('company','')}{tag}")
    return "\n".join(out)


def write_outputs(jobs, out_dir, run_date, min_highlight=7):
    """Write markdown + CSV to out_dir, returning the two file paths."""
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, f"job_summary_{run_date}.md")
    csv_path = os.path.join(out_dir, f"job_summary_{run_date}.csv")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(jobs, run_date, min_highlight))
    write_csv(jobs, csv_path, run_date)
    return md_path, csv_path
