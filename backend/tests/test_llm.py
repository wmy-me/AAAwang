"""Focused checks for model configuration and response handling."""

import asyncio
from types import SimpleNamespace
from typing import cast

import pytest
from openai import (
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    NotFoundError,
)
from pydantic import SecretStr

import life_agent.core.llm.deepseek as deepseek_module
from life_agent.core.config import Settings
from life_agent.core.llm import (
    LLMConfigurationError,
    LLMRequestError,
    call_deepseek,
)


class FakeCompletions:
    def __init__(self, content: str | None, error: Exception | None = None) -> None:
        self.content = content
        self.error = error

    async def create(self, **_kwargs: object) -> SimpleNamespace:
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))],
            usage=SimpleNamespace(
                prompt_tokens=8,
                completion_tokens=4,
                total_tokens=12,
            ),
        )


class FakeClient:
    def __init__(self, content: str | None, error: Exception | None = None) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(content, error))


def test_missing_api_key_is_reported_only_when_calling() -> None:
    settings = Settings(llm_api_key=None)

    with pytest.raises(LLMConfigurationError, match="LLM_API_KEY"):
        asyncio.run(call_deepseek(settings, "测试"))


def test_non_empty_response_and_usage_are_returned() -> None:
    settings = Settings(llm_api_key=SecretStr("test-key"))
    client = cast(AsyncOpenAI, FakeClient(" 已收到 "))

    result = asyncio.run(call_deepseek(settings, "测试", client=client))

    assert result.text == "已收到"
    assert result.total_tokens == 12


def test_empty_response_is_rejected() -> None:
    settings = Settings(llm_api_key=SecretStr("test-key"))
    client = cast(AsyncOpenAI, FakeClient("  "))

    with pytest.raises(LLMRequestError, match="没有文本内容"):
        asyncio.run(call_deepseek(settings, "测试", client=client))


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (APITimeoutError(request=None), "60 秒后超时"),
        (
            AuthenticationError(
                "sensitive provider response",
                response=SimpleNamespace(status_code=401, request=None, headers={}),
                body=None,
            ),
            "认证失败",
        ),
        (
            NotFoundError(
                "sensitive provider response",
                response=SimpleNamespace(status_code=404, request=None, headers={}),
                body=None,
            ),
            "未找到模型 deepseek-flash",
        ),
    ],
)
def test_provider_failures_are_mapped_to_safe_messages(
    error: Exception, message: str
) -> None:
    settings = Settings(llm_api_key=SecretStr("test-key"))
    client = cast(AsyncOpenAI, FakeClient(None, error))

    with pytest.raises(LLMRequestError, match=message) as exc_info:
        asyncio.run(call_deepseek(settings, "测试", client=client))

    assert "sensitive provider response" not in str(exc_info.value)


def test_provider_http_error_keeps_safe_diagnostic_fields() -> None:
    settings = Settings(llm_api_key=SecretStr("test-key"))
    error = APIStatusError(
        "sensitive provider response",
        response=SimpleNamespace(status_code=400, request=None, headers={}),
        body={
            "error": {
                "type": "invalid_request_error",
                "param": "tools",
                "message": "tools must not be empty",
                "secret": "must not be exposed",
            }
        },
    )
    client = cast(AsyncOpenAI, FakeClient(None, error))

    with pytest.raises(LLMRequestError, match="HTTP 400.*param=tools.*tools must not be empty") as exc_info:
        asyncio.run(call_deepseek(settings, "测试", client=client))

    assert "secret" not in str(exc_info.value)
    assert "sensitive provider response" not in str(exc_info.value)


def test_client_initialization_failure_is_mapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(llm_api_key=SecretStr("test-key"))

    def fail_to_initialize(**_kwargs: object) -> AsyncOpenAI:
        raise ImportError("sensitive local environment detail")

    monkeypatch.setattr(deepseek_module, "AsyncOpenAI", fail_to_initialize)

    with pytest.raises(LLMRequestError, match="网络传输依赖") as exc_info:
        asyncio.run(call_deepseek(settings, "测试"))

    assert "sensitive local environment detail" not in str(exc_info.value)