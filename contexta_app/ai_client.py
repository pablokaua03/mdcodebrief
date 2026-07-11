"""AI API client for sending context packs directly to Claude, Gemini, or OpenAI."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path.home() / ".contexta" / "ai_config.json"

ENV_VARS = {
    "claude": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "openai": "OPENAI_API_KEY",
}

DEFAULT_MODELS = {
    "claude": "claude-sonnet-4-20250514",
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o",
}

PROVIDER_LABELS = {
    "claude": "Claude (Anthropic)",
    "gemini": "Gemini (Google)",
    "openai": "ChatGPT / GPT-4 (OpenAI)",
}


@dataclass
class AIConfig:
    provider: str = ""  # "claude", "gemini", "openai"
    api_key: str = ""
    model: str = ""

    @staticmethod
    def load() -> "AIConfig":
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return AIConfig(**{k: v for k, v in data.items() if k in AIConfig.__dataclass_fields__})
        return AIConfig()

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(
                {"provider": self.provider, "api_key": self.api_key, "model": self.model},
                indent=2,
            ),
            encoding="utf-8",
        )


def get_available_providers() -> list[str]:
    """Return provider keys whose SDK is installed."""
    available = []
    try:
        import anthropic  # noqa: F401
        available.append("claude")
    except ImportError:
        pass
    try:
        import google.genai  # noqa: F401
        available.append("gemini")
    except ImportError:
        pass
    try:
        import openai  # noqa: F401
        available.append("openai")
    except ImportError:
        pass
    return available


def resolve_api_key(provider: str, explicit_key: str = "") -> str:
    """Resolve API key: explicit flag > env var > saved config."""
    if explicit_key:
        return explicit_key
    env_var = ENV_VARS.get(provider, "")
    if env_var:
        env_val = os.environ.get(env_var, "")
        if env_val:
            return env_val
    cfg = AIConfig.load()
    if cfg.provider == provider and cfg.api_key:
        return cfg.api_key
    return ""


def send_to_ai(
    context_markdown: str,
    prompt: str,
    provider: str,
    api_key: str,
    model: str = "",
) -> str:
    """Send context + prompt to the chosen AI and return the response text."""
    if not model:
        model = DEFAULT_MODELS.get(provider, "")

    system_msg = (
        "You are a senior software engineer. The user will provide a project context "
        "pack followed by a question or task. Analyze the context and respond helpfully."
    )

    if provider == "claude":
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            system=system_msg,
            messages=[{"role": "user", "content": f"{context_markdown}\n\n---\n\n{prompt}"}],
        )
        return response.content[0].text

    elif provider == "gemini":
        from google import genai

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=f"{system_msg}\n\n{context_markdown}\n\n---\n\n{prompt}",
        )
        return response.text

    elif provider == "openai":
        import openai as oai

        client = oai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"{context_markdown}\n\n---\n\n{prompt}"},
            ],
        )
        return response.choices[0].message.content

    else:
        raise ValueError(f"Unknown provider: {provider}")


def configure_interactive() -> None:
    """Interactive setup: choose provider, enter API key and model, save to config."""
    available = get_available_providers()
    all_providers = list(PROVIDER_LABELS.keys())

    print("AI Configuration for Contexta")
    print("=" * 40)
    print("\nAvailable providers (SDK installed):")
    for p in all_providers:
        installed = p in available
        label = PROVIDER_LABELS[p]
        status = "installed" if installed else "not installed"
        print(f"  {p:10s} - {label} [{status}]")

    print()
    provider = input(f"Choose provider ({', '.join(all_providers)}): ").strip().lower()
    if provider not in all_providers:
        print(f"Unknown provider '{provider}'. Aborting.")
        return

    if provider not in available:
        pkg = {"claude": "anthropic", "gemini": "google-genai", "openai": "openai"}[provider]
        print(f"\nWarning: '{pkg}' is not installed. Install it with: pip install {pkg}")

    api_key = input("API key: ").strip()
    if not api_key:
        print("No API key provided. Aborting.")
        return

    default_model = DEFAULT_MODELS.get(provider, "")
    model = input(f"Model (default: {default_model}): ").strip()
    if not model:
        model = default_model

    cfg = AIConfig(provider=provider, api_key=api_key, model=model)
    cfg.save()
    print(f"\nSaved to {CONFIG_PATH}")
