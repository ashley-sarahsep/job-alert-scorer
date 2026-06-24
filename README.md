# Job Alert Scorer

Read job-alert emails from Gmail, fetch the full job descriptions, score each
one for fit against your candidate profile using an AI model, and get a ranked
summary by email (and as CSV / markdown files). It's a **triage tool** - it
helps you decide what to apply to; it does not write applications.

It separates the **public tool** (this repo) from your **private profile and
credentials** (a separate folder you point it at), so nothing personal lives in
the code.

> **New here?** The [illustrated getting-started guide](https://ashley-sarahsep.github.io/job-alert-scorer/)
> walks through the whole flow in plain language. Prefer not to install anything?
> There are [no-code versions](docs/claude-project-companion.md) you can run inside
> Claude or ChatGPT.

---

## What it does

```
Gmail alerts  ->  extract jobs  ->  title pre-filter  ->  fetch full description
              ->  score fit (AI)  ->  ranked email + CSV + markdown
```

- Reads alert emails from **LinkedIn** and **Indeed** (configurable senders),
  plus a best-effort **generic** parser for any other board.
- **Title pre-filter** skips obvious non-fits (e.g. software engineering or
  director-level roles) before they cost anything to score - but still lists
  them so you can catch exceptions.
- Fetches the **full job description** from the company's careers page
  (Greenhouse / Lever / Ashby public APIs), with an optional AI web-search
  fallback and the email snippet as a last resort.
- **Scores each job 1-10** with reasoning, key alignments/gaps, unique match
  signals, hard blockers, compensation and location flags, and an
  Apply/Consider/Pass recommendation - via your choice of AI provider.
- Outputs a **ranked email** (grouped Strong Fits / Worth a Shot / Worth
  Considering / Passes) plus CSV and markdown files.

---

## What you'll need

- **Python 3.10+** on your computer.
- A **Gmail account** with at least one job-alert subscription (LinkedIn and/or
  Indeed).
- An **Anthropic API key** for scoring - a few cents to a couple of dollars a
  month; set a spend limit in your provider console.
- **Your candidate profile** - a markdown file about your experience and targets.
  Start from the [profile template](config/example/candidate_profile.template.md)
  and the [profile guide](docs/profile-guide.md); a complete fictional sample
  ships in `config/example/`.
- About **30 minutes** for first-time setup (most of it the one-time Gmail step).

Prefer not to install anything? Use a
[no-code Claude option](docs/claude-project-companion.md) instead (see below).

---

## Quick start

```bash
# 1. Clone and install
git clone https://github.com/ashley-sarahsep/job-alert-scorer.git
cd job-alert-scorer
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp config/config.example.yaml config/config.yaml
cp .env.example config/.env            # then add your provider API key
#   edit config/config.yaml to point at your candidate profile files
#   (the bundled example/ profile is a fictional candidate, "Sarah Ashley")

# 3. Add your Gmail credentials.json (see "Setting up Gmail API" below)
#    next to your config.yaml, then run:
python src/main.py --score --email
```

Run it pointing at a **private** config folder instead (recommended - keeps your
profile and keys out of the repo):

```bash
python src/main.py --config ~/my-job-scorer-config/config.yaml --score --email
# or: export JOB_SCORER_CONFIG=~/my-job-scorer-config/config.yaml
```

The config loader looks for `--config`, then `JOB_SCORER_CONFIG`, then
`config/config.yaml`. All paths inside the config are resolved **relative to the
config file**, so your profile, credentials, and caches can all live in that one
private folder.

Common commands:

| Command | What it does |
|---|---|
| `python src/main.py --score --email` | New alerts since last run, scored + emailed |
| `python src/main.py --all --score --email` | Re-check recent alerts (ignore last-run) |
| `python src/main.py --since 7d --score` | Last 7 days, score, write files (no email) |
| `python src/main.py --since 7d` | Just list jobs found (no scoring, no cost) |
| `... --score --email --web-search` | Also web-search careers pages the ATS lookup misses |

---

## Setting up Gmail API

This is the fiddliest part; you do it once (~10 min). The goal is a
`credentials.json` file you place next to your `config.yaml`.

1. Go to <https://console.cloud.google.com/> and **create a project**.
2. Search **"Gmail API"** and click **Enable**.
3. Configure the **OAuth consent screen** (a.k.a. Google Auth Platform):
   choose **External**, fill in an app name and your email, and **add your own
   Google account as a Test user**.
4. Go to **Credentials -> Create Credentials -> OAuth client ID ->
   Application type: Desktop app**, create it, and **Download JSON**.
5. Rename the file to **`credentials.json`** and put it next to your
   `config.yaml`.
6. The first run opens a browser to authorise read + send access (click through
   the "unverified app" warning - it's your own app). A `token.json` is saved so
   future runs are non-interactive.

On a headless machine, use `python src/remote_auth.py --config <path> url` /
`exchange "<url>"` to authorise without a local browser.

The Gmail scopes requested are **read** (to read alerts) and **send** (to email
you the summary). The tool never deletes or modifies your mail.

---

## Creating your candidate profile

Your profile is one or two markdown files:

- **`candidate_profile.md`** - the source of truth: your experience, strengths,
  gaps, target roles, compensation, and location.
- **`candidate_addendum.md`** (optional) - updated targeting and scoring notes.
  **The addendum takes priority over the handbook where they conflict.**

The bundled `config/example/` folder contains a complete fictional example
("Sarah Ashley") you can copy and adapt. Good things to include: target roles in
priority order, hard blockers (things that make a role a no), unique match
signals (things that make a role especially worth it), compensation target, and
location/commute constraints. Both files are sent to the model as the candidate
profile when scoring.

**Start from the template, not a blank page.** Copy
[`candidate_profile.template.md`](config/example/candidate_profile.template.md)
(and the optional
[`candidate_addendum.template.md`](config/example/candidate_addendum.template.md))
and fill in the bracketed prompts. The
**[profile guide](docs/profile-guide.md)** explains what each section is for and
how it drives scoring: hard blockers cap the score at 4, unique signals lift it,
and soft gaps are noted rather than penalised. Don't want a blank page? Paste
your resume plus our [ready-made profile-builder prompt](docs/profile-builder-prompt.md)
into Claude or ChatGPT and it drafts the profile in this format for you to
refine.

---

## No-code options (nothing to install)

Don't want to run the Python tool at all? Two Claude/ChatGPT options use the same
profile format:

- **[Job Search Companion](docs/claude-project-companion.md)** - the fuller
  experience. A Claude project that helps you *build and refine your profile*
  (including spotting transferable skills you might undersell) and then scores
  jobs with transferability analysis. Best if you're starting from scratch.
- **[Scoring template](docs/claude-scoring-template.md)** - lightweight. Paste a
  job description, get a score. Best once your profile is written.

There's also a one-off **[profile-builder prompt](docs/profile-builder-prompt.md)**
that drafts your profile from your resume in any AI assistant.

---

## Configuring the title filter

The title pre-filter decides which jobs are worth scoring, by **title alone**,
before any AI cost. Two lists in `config.yaml`:

- **`skip_title_keywords`** - skip a job if its title contains any of these.
- **`keep_title_keywords`** - but keep (score) it if it also contains one of
  these. **Keep overrides skip.**

So with `director` in skip and `implementation` in keep, *"Director of
Implementation"* is scored while *"Director, Data Science"* is skipped. Matching
is case-insensitive substring matching, so prefer specific multi-word phrases
(`software engineer`, not `engineer`). Skipped jobs are still listed at the
bottom of the output (with the keyword that caught them), so you can spot a
genuine exception and add a keep keyword.

---

## Other job boards

LinkedIn and Indeed have precise, dedicated parsers. For any other board, add a
source with **`parser: generic`** - a best-effort parser that reads job links
from the alert email and, if it finds none and `ANTHROPIC_API_KEY` is set, falls
back to asking the model to extract the postings. It only needs to recover the
title and company; the tool fetches the full description from the careers page
and scores that.

```yaml
sources:
  - name: Glassdoor
    query: "from:noreply@glassdoor.com"
    parser: generic
```

Treat generic results as best-effort and sanity-check the first few runs. For a
board you use a lot, a dedicated parser is more reliable - see
[`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## AI provider

This release uses **Anthropic (Claude)**. Set the model in `config.yaml` and put
your key in `.env`:

| Provider | `provider` | Example model | Key (env) |
|---|---|---|---|
| Anthropic | `anthropic` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |

Scoring sits behind a small provider interface, so other providers can be added.
Experimental **OpenAI / Google / Groq** implementations (unverified) live on the
`experimental-providers` branch - see **[docs/PROVIDERS.md](docs/PROVIDERS.md)**
for the per-provider review and red flags.

## Cost management

- **The title filter is the biggest saver** - it drops obvious non-fits before
  scoring.
- **Scoring is cached** (`scored_cache.json`) by job id, so you only pay for
  genuinely new jobs, not repeats across runs.
- With Anthropic, the rubric + profile sit in the **cached** part of the prompt,
  so each job after the first is billed at cache-read rates - roughly
  **$0.01-0.02 per new job** on `claude-sonnet-4-6`. A daily run is typically a
  few cents to a couple of dollars; set a **monthly spend limit** in your
  provider's console as a safety net.
- The optional `--web-search` fallback adds cost only for jobs whose careers
  page the free lookup misses.

---

## Running on a schedule (optional)

**You don't have to schedule anything.** The normal way to use the tool is to run
the one command by hand whenever you want to check for new roles - that's it.
Scheduling is purely for people who'd like it to run automatically in the
background; skip this section otherwise.

The tool is a single command, so any scheduler works. Run it once by hand first
(to do the one-time Gmail browser auth), then automate it.

**macOS / Linux (cron)** - daily at 8am:

    0 8 * * * cd /path/to/job-alert-scorer && /path/to/.venv/bin/python src/main.py --config ~/my-job-scorer-config/config.yaml --score --email

Edit your crontab with `crontab -e`, using absolute paths to both the project and
the virtualenv's Python.

**Windows (Task Scheduler)** - create a Basic Task with a daily trigger whose
action runs `python.exe` with arguments
`src\main.py --config <path>\config.yaml --score --email`, and "Start in" set to
the project folder.

The `last_run` timestamp means each run only scores genuinely new alerts, and
scoring is cached, so scheduled runs stay cheap.

---

## How scoring works

Each job's description, your candidate profile, and a scoring **rubric** are sent
to the model, which returns a structured assessment (enforced by a JSON schema):
a 1-10 score, a fit summary, key alignments and gaps, unique match signals, any
hard blockers (which cap the score at 4), transferability notes (where your
experience maps to a role through capability translation rather than a keyword
match), a compensation and location flag, a "worth a shot" transferable-stretch
flag, and an Apply/Consider/Pass recommendation. The rubric lives in
`src/scorer.py` and is generic - the per-candidate specifics (targets, blockers,
comp, location, signals) all come from your profile files, so you tune behaviour
by editing your profile, not the code.

---

## Your data & privacy

- Your **emails are read on your computer** via the Gmail API - there is no
  server of ours in the loop.
- To score a job, its **description and your candidate profile are sent to the AI
  provider you choose** (e.g. Anthropic). That's the only data that leaves your
  machine, and only for scoring.
- Your profile, credentials, tokens, caches, and results live in your local
  config folder and are **excluded from git** by `.gitignore`. Keep your profile
  and `credentials.json` in a private folder (via `--config`), not in the repo.

---

## Project layout

```
src/
  main.py            CLI entry point and pipeline
  config_loader.py   YAML config + path resolution + .env
  gmail_reader.py    Gmail OAuth + message retrieval
  linkedin_parser.py / indeed_parser.py   Per-board alert parsers
  generic_parser.py  Best-effort parser for any other board (+ AI fallback)
  deduplication.py   Job dedup
  title_filter.py    Title pre-filter
  job_fetcher.py     Careers-page (ATS) fetch + web-search fallback
  scorer.py          Rubric, schema, profile assembly, scoring orchestration
  providers/         AI provider abstraction (anthropic/openai/google/groq)
  output.py          CSV / markdown / email rendering
  remote_auth.py     Headless Gmail OAuth helper
config/
  config.example.yaml
  example/           Fictional "Sarah Ashley" profile + addendum + blank templates
docs/
  profile-guide.md             How to write your candidate profile
  building-a-strong-profile.md Deep guide: describe your experience at the capability level
  profile-builder-prompt.md    Copy-paste prompt to draft your profile from a resume
  claude-project-companion.md  No-code Claude project: build a profile + score jobs
  claude-scoring-template.md   No-code Claude project: scoring only
  profile-guide-visual.html    Visual profile guide (GitHub Pages)
  anthropic-setup.html         Step-by-step Anthropic API setup (GitHub Pages)
  terminal-basics.html         Terminal primer for non-developers (GitHub Pages)
  PROVIDERS.md                 AI provider notes + review
  index.html                   Illustrated getting-started page (GitHub Pages)
tests/               Offline tests (no network or API keys needed)
```

---

## Guides and Resources

**Getting started:** [Getting Started page](https://ashley-sarahsep.github.io/job-alert-scorer/) - setup walkthrough with a "show me simply" / "I'm technical" toggle.

**Building your profile:**
- [Visual guide](https://ashley-sarahsep.github.io/job-alert-scorer/profile-guide-visual.html) - the same concepts, shown instead of told
- [Deep guide](docs/building-a-strong-profile.md) - how to think about your experience at the capability level
- [Profile template](config/example/candidate_profile.template.md) - fill-in-the-blank template
- [Profile reference](docs/profile-guide.md) - quick reference on what each section does

**No-code option (no terminal, no Python):**
- [Companion project](docs/claude-project-companion.md) - paste into a Claude.ai project for interactive profile building and job scoring
- [Scoring template](docs/claude-scoring-template.md) - lighter version, just paste a job and get a score

**Setup help:**
- [Anthropic API setup](https://ashley-sarahsep.github.io/job-alert-scorer/anthropic-setup.html) - step-by-step guide for getting your API key
- [Using the terminal](https://ashley-sarahsep.github.io/job-alert-scorer/terminal-basics.html) - a 2-minute primer for non-developers, with a copy-paste cheat sheet for running the tool

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full guide. Quick pointers:

- **Add an alert parser:** LinkedIn and Indeed ship today
  (`src/linkedin_parser.py`, `src/indeed_parser.py`); other boards (Wellfound,
  Glassdoor, ...) just need a parser modelled on those.
- **Add an AI provider:** create `src/providers/<name>_provider.py` with a class
  that subclasses `BaseProvider` and implements `score_job(...)` returning the
  schema dict, then register it in `src/providers/__init__.py`. (OpenAI, Google,
  and Groq already exist, unverified, on the `experimental-providers` branch.)
- **Run the tests:** `for t in tests/test_*.py; do python "$t"; done` - they're
  all offline (no network, no API keys).
- Please keep personal data out of the repo; the `.gitignore` already excludes
  configs, profiles, credentials, and results.

MIT licensed - see `LICENSE`.
