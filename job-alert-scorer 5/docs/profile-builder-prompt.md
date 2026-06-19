# Build your candidate profile with a copy-paste prompt

You don't have to write your profile from a blank page. Paste the prompt below
into **Claude, ChatGPT, or any AI assistant**, then paste your resume underneath
it. The assistant will draft your profile in exactly the format this tool
expects, and ask you for anything your resume doesn't make clear (hard blockers,
target roles, compensation, location).

When it's done, save the result as **`candidate_profile.md`** in your config
folder. (For the full picture of what each section does, see the
[profile guide](PROFILE_GUIDE.md); for a blank fill-in version, see
[`config/example/candidate_profile.template.md`](../config/example/candidate_profile.template.md).)

This is the lighter-weight cousin of the [no-code Claude project
template](no-code-claude-template.md): use *this* prompt to **build** your
profile, and the project template to **score jobs** with it.

---

## The prompt (copy everything in this box)

```text
You are helping me build a "candidate profile" for a job-fit scoring tool. I'll
paste my resume below. Turn it into a profile using EXACTLY the section headers
below. Use only what's in my resume or what I tell you - do not invent
experience, metrics, or qualifications. Where you don't have enough to fill a
section - especially Hard Blockers, Target Roles, Compensation, and Location -
ASK me focused questions before finalizing.

Produce the profile in this structure:

## Summary
2-3 sentences: who I am, years of experience, the kind of work I do, and what
I'm looking for next.

## Career Timeline
Reverse chronological. For each role: Company | Title | dates, then 2-4 bullets
on what I owned, the scale I worked at, and outcomes (not just duties).

## Key Strengths
5-8 concrete strengths. Specific beats generic.

## Target Roles (Priority Order)
The roles I want, most-wanted first. Ask me if my resume doesn't make this clear.

## Hard Blockers
Dealbreakers - things that make a role a no. These cap a job's score, so be
precise. Ask me for these; resumes rarely state them.

## Unique Match Signals
The kinds of roles and environments where I do my best work - these lift a job's
score. Ask me if unsure.

## Soft Gaps
Real gaps that are NOT dealbreakers, stated plainly.

## Compensation
Target range, currency, and any notes. Ask me.

## Location and Commute
Where I'm based, remote preference, and any hard constraints. Ask me.

## Education and Certifications
Degrees and certifications; note anything in progress or self-taught.

## Tools and Systems
Grouped by depth: deep proficiency / working knowledge / learning.

When everything is filled in, output the whole profile as clean Markdown I can
save as candidate_profile.md. Then remind me that I can keep an optional
candidate_addendum.md for later updates that override this profile.

My resume:
[PASTE YOUR RESUME HERE]
```
