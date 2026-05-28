"""Tests for provider-specific token extraction (I2)."""
import pytest
from src.providers import (
    extract_openai_usage,
    extract_anthropic_usage,
    extract_google_usage,
    extract_deepseek_usage,
    extract_usage,
)


class TestOpenAIExtractor:
    def test_basic_usage(self):
        chunk = b'data: {"usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}\n'
        result = extract_openai_usage(chunk)
        assert result == {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}

    def test_no_usage(self):
        chunk = b'data: {"choices": [{"delta": {"content": "hello"}}]}\n'
        result = extract_openai_usage(chunk)
        assert result == {}

    def test_done_marker(self):
        chunk = b"data: [DONE]\n"
        result = extract_openai_usage(chunk)
        assert result == {}

    def test_empty_chunk(self):
        result = extract_openai_usage(b"")
        assert result == {}

    def test_malformed_json(self):
        chunk = b"data: {not json\n"
        result = extract_openai_usage(chunk)
        assert result == {}

    def test_multiline_with_usage_at_end(self):
        chunks = [
            b'data: {"choices": [{"delta": {"content": "He"}}]}\n',
            b'data: {"choices": [{"delta": {"content": "llo"}}]}\n',
            b'data: {"usage": {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}}\n',
        ]
        for chunk in chunks[:-1]:
            assert extract_openai_usage(chunk) == {}
        result = extract_openai_usage(chunks[-1])
        assert result["input_tokens"] == 200
        assert result["output_tokens"] == 100


class TestAnthropicExtractor:
    def test_basic_usage(self):
        chunk = b'event: content_block_stop\ndata: {"usage": {"input_tokens": 500, "output_tokens": 200}}\n'
        result = extract_anthropic_usage(chunk)
        assert result == {"input_tokens": 500, "output_tokens": 200, "total_tokens": 700}

    def test_no_usage(self):
        chunk = b'event: content_block_delta\ndata: {"delta": {"text": "hi"}}\n'
        result = extract_anthropic_usage(chunk)
        assert result == {}

    def test_empty(self):
        result = extract_anthropic_usage(b"")
        assert result == {}

    def test_only_output_tokens(self):
        chunk = b'data: {"usage": {"output_tokens": 150}}\n'
        result = extract_anthropic_usage(chunk)
        assert result["output_tokens"] == 150
        assert result["input_tokens"] == 0

    def test_malformed(self):
        result = extract_anthropic_usage(b"data: {invalid")
        assert result == {}


class TestGoogleExtractor:
    def test_basic_usage(self):
        chunk = b'data: {"usageMetadata": {"promptTokenCount": 300, "candidatesTokenCount": 150, "totalTokenCount": 450}}\n'
        result = extract_google_usage(chunk)
        assert result == {"input_tokens": 300, "output_tokens": 150, "total_tokens": 450}

    def test_no_usage(self):
        chunk = b'data: {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}\n'
        result = extract_google_usage(chunk)
        assert result == {}

    def test_empty(self):
        result = extract_google_usage(b"")
        assert result == {}

    def test_string_counts(self):
        """Google may return string numbers in usageMetadata."""
        chunk = b'data: {"usageMetadata": {"promptTokenCount": "100", "candidatesTokenCount": "50", "totalTokenCount": "150"}}\n'
        result = extract_google_usage(chunk)
        assert result["input_tokens"] == 100

    def test_malformed(self):
        result = extract_google_usage(b"data: {bad json")
        assert result == {}


class TestDeepseekExtractor:
    """DeepSeek uses OpenAI-compatible format."""
    def test_basic(self):
        chunk = b'data: {"usage": {"prompt_tokens": 80, "completion_tokens": 40, "total_tokens": 120}}\n'
        result = extract_deepseek_usage(chunk)
        assert result == {"input_tokens": 80, "output_tokens": 40, "total_tokens": 120}


class TestDispatcher:
    def test_openai_model(self):
        chunk = b'data: {"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}\n'
        result = extract_usage(chunk, "openai/gpt-4o")
        assert result["input_tokens"] == 10

    def test_anthropic_model(self):
        chunk = b'data: {"usage": {"input_tokens": 20, "output_tokens": 10}}\n'
        result = extract_usage(chunk, "anthropic/claude-sonnet-4")
        assert result["input_tokens"] == 20

    def test_google_model(self):
        chunk = b'data: {"usageMetadata": {"promptTokenCount": 30, "candidatesTokenCount": 15, "totalTokenCount": 45}}\n'
        result = extract_usage(chunk, "google/gemini-2.5-flash")
        assert result["input_tokens"] == 30

    def test_deepseek_model(self):
        chunk = b'data: {"usage": {"prompt_tokens": 40, "completion_tokens": 20, "total_tokens": 60}}\n'
        result = extract_usage(chunk, "deepseek/deepseek-chat")
        assert result["input_tokens"] == 40

    def test_unknown_model_defaults_to_openai(self):
        chunk = b'data: {"usage": {"prompt_tokens": 5, "output_tokens": 3, "total_tokens": 8}}\n'
        result = extract_usage(chunk, "unknown/some-model")
        assert result["input_tokens"] == 5

    def test_empty_model_defaults_to_openai(self):
        chunk = b'data: {"usage": {"prompt_tokens": 7, "output_tokens": 4, "total_tokens": 11}}\n'
        result = extract_usage(chunk, "gpt-4o")  # No provider prefix — falls through to default
        assert result["input_tokens"] == 7
