"""Provider registry. This release ships and tests Anthropic (Claude) only.

OpenAI / Google / Groq implementations live on the 'experimental-providers'
branch (unverified). To add one, drop a `<name>_provider.py` here subclassing
BaseProvider and register it below.
"""


def get_provider(name, model):
    name = (name or "anthropic").lower()
    if name == "anthropic":
        from providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(model)
    raise ValueError(
        f"Provider {name!r} is not bundled in this release - only 'anthropic' is "
        "shipped and tested. OpenAI/Google/Groq are available (untested) on the "
        "'experimental-providers' branch."
    )
