"""Anthropic API client helper, shared by the web-search fallback (Step 2) and
fit scoring (Step 3).

The API key is read from the ANTHROPIC_API_KEY environment variable, never
hard-coded. Import is done lazily so the rest of the tool (Gmail reading, ATS
fetching) works without the anthropic package installed.
"""

import os


def get_client():
    """Return an authenticated anthropic.Anthropic client.

    Raises a clear RuntimeError if the package or API key is missing.
    """
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError(
            "The 'anthropic' package is required for web search / scoring. "
            "Install it with: pip install anthropic"
        ) from exc

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Export your Anthropic API key, e.g.\n"
            "  export ANTHROPIC_API_KEY=sk-ant-..."
        )

    return anthropic.Anthropic()
