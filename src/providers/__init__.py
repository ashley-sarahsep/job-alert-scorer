"""Provider registry. Maps a config provider name to its implementation."""


def get_provider(name, model):
    name = (name or "anthropic").lower()
    if name == "anthropic":
        from providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(model)
    if name == "openai":
        from providers.openai_provider import OpenAIProvider
        return OpenAIProvider(model)
    if name == "google":
        from providers.google_provider import GoogleProvider
        return GoogleProvider(model)
    if name == "groq":
        from providers.groq_provider import GroqProvider
        return GroqProvider(model)
    raise ValueError(f"Unknown scoring provider: {name!r}. "
                     "Choose one of: anthropic, openai, google, groq.")
