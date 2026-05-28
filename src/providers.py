"""
ResGov — Provider-specific streaming format extractors.

Each provider uses a different streaming format to report token usage.
This module provides a unified interface to extract usage from all of them.

Supported formats:
- OpenAI: data: {"usage": {"prompt_tokens": N, "completion_tokens": N, "total_tokens": N}}
- Anthropic: event: content_block_stop -> {"usage": {"input_tokens": N, "output_tokens": N}}
- Google: data: {"usageMetadata": {"promptTokenCount": N, "candidatesTokenCount": N, "totalTokenCount": N}}
- Deepseek: OpenAI-compatible (data: format)
"""
from __future__ import annotations

import json
from typing import Optional


def extract_openai_usage(chunk: bytes) -> dict:
    """Extract token usage from OpenAI streaming chunks.

    Format: data: {"usage": {"prompt_tokens": N, "completion_tokens": N, "total_tokens": N}}

    Returns: {"input_tokens": N, "output_tokens": N, "total_tokens": N}
    """
    return _extract_openai_style(chunk)


def extract_deepseek_usage(chunk: bytes) -> dict:
    """DeepSeek uses OpenAI-compatible streaming format."""
    return _extract_openai_style(chunk)


def extract_anthropic_usage(chunk: bytes) -> dict:
    """Extract token usage from Anthropic streaming chunks.

    Format: event: content_block_stop followed by message_delta with usage
    Or: {"type": "message_delta", "usage": {"output_tokens": N}}

    Returns: {"input_tokens": N, "output_tokens": N, "total_tokens": N}
    """
    try:
        text = chunk.decode("utf-8", errors="ignore")
        for line in text.split("\n"):
            line = line.strip()
            # Anthropic event format: "event: content_block_stop" then "data: {...}"
            if line.startswith("data: ") and line != "data: [DONE]":
                data = json.loads(line[6:])
                usage = data.get("usage", {})
                if usage:
                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)
                    if input_tokens or output_tokens:
                        return {
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "total_tokens": input_tokens + output_tokens,
                        }
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    return {}


def extract_google_usage(chunk: bytes) -> dict:
    """Extract token usage from Google (Gemini) streaming chunks.

    Format: data: {"usageMetadata": {"promptTokenCount": N, "candidatesTokenCount": N, "totalTokenCount": N}}

    Returns: {"input_tokens": N, "output_tokens": N, "total_tokens": N}
    """
    try:
        text = chunk.decode("utf-8", errors="ignore")
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("data: ") and line != "data: [DONE]":
                data = json.loads(line[6:])
                usage_meta = data.get("usageMetadata", {})
                if usage_meta:
                    input_tokens = int(usage_meta.get("promptTokenCount", 0))
                    output_tokens = int(usage_meta.get("candidatesTokenCount", 0))
                    total_tokens = int(usage_meta.get("totalTokenCount", input_tokens + output_tokens))
                    if input_tokens or output_tokens:
                        return {
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "total_tokens": total_tokens,
                        }
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        pass
    return {}


def _extract_openai_style(chunk: bytes) -> dict:
    """Shared parser for OpenAI and DeepSeek streaming format."""
    try:
        text = chunk.decode("utf-8", errors="ignore")
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("data: ") and line != "data: [DONE]":
                data = json.loads(line[6:])
                usage = data.get("usage", {})
                if usage:
                    input_tokens = usage.get("prompt_tokens", usage.get("input_tokens", 0))
                    output_tokens = usage.get("completion_tokens", usage.get("output_tokens", 0))
                    total_tokens = usage.get("total_tokens", input_tokens + output_tokens)
                    if input_tokens or output_tokens:
                        return {
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "total_tokens": total_tokens,
                        }
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    return {}


# --- Dispatcher ---

_PROVIDER_EXTRACTORS = {
    "openai": extract_openai_usage,
    "deepseek": extract_deepseek_usage,
    "anthropic": extract_anthropic_usage,
    "google": extract_google_usage,
}

_DEFAULT_EXTRACTOR = extract_openai_usage


def extract_usage(chunk: bytes, model: str) -> dict:
    """Extract token usage from a streaming chunk based on the model provider.

    Args:
        chunk: Raw bytes from the streaming response
        model: Model identifier (e.g., "openai/gpt-4o", "anthropic/claude-sonnet-4")

    Returns:
        dict with keys: input_tokens, output_tokens, total_tokens
        Empty dict {} if no usage data found
    """
    # Determine provider from model prefix
    provider = "openai"  # default
    model_lower = model.lower()
    for prefix in _PROVIDER_EXTRACTORS:
        if model_lower.startswith(prefix):
            provider = prefix
            break

    extractor = _PROVIDER_EXTRACTORS.get(provider, _DEFAULT_EXTRACTOR)
    return extractor(chunk)
