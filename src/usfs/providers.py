"""
LLM provider abstraction for enrichment and RAG.

Embeddings live in ``embeddings.py`` (fastembed / Voyage); this module covers
only text generation. One ``LLM`` interface with a local (Ollama) and a cloud
(Claude) implementation, selected by config.PROVIDER. Vendor packages are
imported lazily so the local path runs without the cloud extras installed.
"""

from typing import Protocol

import requests

from . import config

class LLM(Protocol):
    """Generates text from a prompt, with an optional system instruction."""

    def complete(self, prompt: str, system: str | None = None) -> str: ...


class OllamaLLM:
    """Local LLM via the Ollama HTTP API."""

    def __init__(self) -> None:
        self.model = config.LOCAL_LLM_MODEL
        self.host = config.OLLAMA_HOST.rstrip("/")

    def complete(self, prompt: str, system: str | None = None) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0},
        }
        if system:
            payload["system"] = system
        resp = requests.post(f"{self.host}/api/generate", json=payload, timeout=300)
        resp.raise_for_status()
        return resp.json()["response"].strip()


class ClaudeLLM:
    """Anthropic Claude (cloud). Used when USFS_PROVIDER=anthropic."""

    def __init__(self) -> None:
        self.model = config.CLAUDE_MODEL
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        return self._client

    def complete(self, prompt: str, system: str | None = None) -> str:
        client = self._ensure_client()
        msg = client.messages.create(
            model=self.model,
            max_tokens=1024,
            temperature=0,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            block.text for block in msg.content if block.type == "text"
        ).strip()

class VerdeLLM:
    """VerdeLLM served through a LiteLLM proxy. Used when USFS_PROVIDER=verde."""

    def __init__(self) -> None:
        self.model = config.VERDE_MODEL
        self.api_key = config.VERDE_API_KEY
        self.api_base = config.VERDE_URL
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            from langchain_litellm import ChatLiteLLM

            self._client = ChatLiteLLM(
                model=f"litellm_proxy/{self.model}",
                api_key=self.api_key,
                api_base=self.api_base,
                temperature=0,
            )
        return self._client

    def complete(self, prompt: str, system: str | None = None) -> str:
        client = self._ensure_client()
        messages = []
        if system:
            messages.append(("system", system))
        messages.append(("user", prompt))
        response = client.invoke(messages)
        return response.content.strip()


def get_llm() -> LLM:
    """Return the LLM for the configured provider."""
    if config.PROVIDER == "local":
        return OllamaLLM()
    if config.PROVIDER == "anthropic":
        return ClaudeLLM()
    if config.PROVIDER == "verde":
        return VerdeLLM()
    raise RuntimeError(f"Unknown USFS_PROVIDER={config.PROVIDER!r}")
