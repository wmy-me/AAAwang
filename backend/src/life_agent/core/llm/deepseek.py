"""DeepSeek text generation through its OpenAI-compatible API."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    NotFoundError,
)

from life_agent.core.budget import RunBudget
from life_agent.core.config import Settings


class LLMConfigurationError(ValueError):
    """Raised when a model call is requested without valid local configuration."""


class LLMRequestError(RuntimeError):
    """Raised with a credential-safe description of a provider failure."""


@dataclass(frozen=True)
class LLMResult:
    """The text and provider-reported token usage from one model call."""

    text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


def _validate_settings(settings: Settings) -> str:
    if settings.llm_provider.casefold() != "deepseek":
        raise LLMConfigurationError(
            f"不支持的 LLM_PROVIDER：{settings.llm_provider}；本轮仅接入 deepseek。"
        )
    if not settings.llm_model.strip():
        raise LLMConfigurationError("缺少必需配置 LLM_MODEL。")
    if not settings.llm_base_url.strip():
        raise LLMConfigurationError("缺少必需配置 LLM_BASE_URL。")
    if settings.llm_timeout_seconds <= 0:
        raise LLMConfigurationError("LLM_TIMEOUT_SECONDS 必须大于 0。")
    if settings.llm_api_key is None or not settings.llm_api_key.get_secret_value().strip():
        raise LLMConfigurationError("缺少必需配置 LLM_API_KEY。")
    return settings.llm_api_key.get_secret_value()


@asynccontextmanager
async def open_deepseek_client(
    settings: Settings,
    client: AsyncOpenAI | None = None,
) -> AsyncIterator[AsyncOpenAI]:
    """Yield a configured client without exposing credentials in errors."""
    api_key = _validate_settings(settings)
    owns_client = client is None
    active_client = client
    try:
        if active_client is None:
            active_client = AsyncOpenAI(
                api_key=api_key,
                base_url=settings.llm_base_url,
                timeout=settings.llm_timeout_seconds,
                max_retries=0,
            )
        yield active_client
    except ImportError as exc:
        raise LLMRequestError("模型客户端初始化失败，请检查已安装的网络传输依赖。") from exc
    finally:
        if owns_client and active_client is not None:
            await active_client.close()


async def create_deepseek_completion(
    settings: Settings,
    client: AsyncOpenAI,
    budget: RunBudget | None = None,
    **kwargs: Any,
) -> Any:
    """Create one completion and map provider failures to safe local errors."""
    if budget is not None:
        budget.reserve("model")
    try:
        return await client.chat.completions.create(
            model=settings.llm_model,
            stream=False,
            extra_body={"thinking": {"type": "disabled"}},
            **kwargs,
        )
    except AuthenticationError as exc:
        raise LLMRequestError("DeepSeek 认证失败，请检查 LLM_API_KEY。") from exc
    except NotFoundError as exc:
        raise LLMRequestError(
            f"DeepSeek 未找到模型 {settings.llm_model}，请检查 LLM_MODEL。"
        ) from exc
    except APITimeoutError as exc:
        raise LLMRequestError(
            f"DeepSeek 请求在 {settings.llm_timeout_seconds:g} 秒后超时。"
        ) from exc
    except APIConnectionError as exc:
        raise LLMRequestError("无法连接 DeepSeek，请检查网络和 LLM_BASE_URL。") from exc
    except APIStatusError as exc:
        raise LLMRequestError(f"DeepSeek 返回 HTTP {exc.status_code}。") from exc


async def call_deepseek(
    settings: Settings,
    prompt: str,
    *,
    client: AsyncOpenAI | None = None,
    budget: RunBudget | None = None,
    max_tokens: int = 128,
    system_prompt: str | None = None,
) -> LLMResult:
    """Send one non-streaming text request with retries disabled."""
    async with open_deepseek_client(settings, client) as active_client:
        response = await create_deepseek_completion(
            settings,
            active_client,
            messages=(
                ([{"role": "system", "content": system_prompt}] if system_prompt else [])
                + [{"role": "user", "content": prompt}]
            ),
            max_tokens=max_tokens,
            budget=budget,
        )

    if not response.choices:
        raise LLMRequestError("DeepSeek 返回空响应：没有候选结果。")
    text = response.choices[0].message.content
    if text is None or not text.strip():
        raise LLMRequestError("DeepSeek 返回空响应：没有文本内容。")

    usage = response.usage
    return LLMResult(
        text=text.strip(),
        prompt_tokens=usage.prompt_tokens if usage else None,
        completion_tokens=usage.completion_tokens if usage else None,
        total_tokens=usage.total_tokens if usage else None,
    )