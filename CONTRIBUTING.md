# Contributing

Thanks for your interest in improving Job Alert Scorer. This is a small,
practical tool - contributions that keep it simple and well-documented are very
welcome.

## Getting set up

```bash
git clone https://github.com/ashley-sarahsep/job-alert-scorer.git
cd job-alert-scorer
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Run the tests (all offline - no network, no API keys needed):

```bash
for t in tests/test_*.py; do python "$t"; done
```

## Good first contributions

- **A new alert-email parser.** Out of the box the tool parses **LinkedIn** and
  **Indeed** alerts (`src/linkedin_parser.py`, `src/indeed_parser.py`), and any
  other board can be read with the best-effort **`generic`** parser
  (`src/generic_parser.py`). A *dedicated* parser for a popular board (Wellfound,
  Glassdoor, ZipRecruiter, ...) is more reliable than the generic one - model a
  new one on the existing parsers, register it in `PARSERS` in `src/main.py`, and
  wire it up in the config's `sources` list with a `parser:` name.

- **A new AI provider.** Create `src/providers/<name>_provider.py` with a class
  that subclasses `BaseProvider` and implements `score_job(...)` returning the
  schema dict, then register it in `src/providers/__init__.py`. The Anthropic
  provider is the reference implementation. Note: OpenAI, Google, and Groq
  providers already exist on the **`experimental-providers`** branch but are
  unverified - testing and hardening those is a great contribution. See
  [`docs/PROVIDERS.md`](docs/PROVIDERS.md).

## Ground rules

- **Keep personal data out of the repo.** The `.gitignore` already excludes
  configs, profiles, credentials, tokens, caches, and results. Never commit a
  real candidate profile or `credentials.json`.
- Keep changes focused and add or update an offline test where it makes sense.
- Match the style of the surrounding code.

MIT licensed - see [`LICENSE`](LICENSE).
