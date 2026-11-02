"""Send one real request to the configured language model."""

import asyncio
import time

from life_agent.core.config import get_settings
from life_agent.core.llm import LLMConfigurationError, LLMRequestError, call_deepseek

TEST_PROMPT = "请简短回复，确认你已收到测试请求。"
MAX_PREVIEW_LENGTH = 200


async def check_llm() -> int:
    settings = get_settings()
    print(f"供应商: {settings.llm_provider}")
    print(f"模型: {settings.llm_model}")

    started_at = time.monotonic()
    try:
        result = await call_deepseek(settings, TEST_PROMPT)
    except (LLMConfigurationError, LLMRequestError) as exc:
        print(f"失败: {exc}")
        return 1

    elapsed_seconds = time.monotonic() - started_at
    preview = result.text[:MAX_PREVIEW_LENGTH]
    if len(result.text) > MAX_PREVIEW_LENGTH:
        preview += "..."
    print("状态: 成功")
    print(f"耗时: {elapsed_seconds:.2f} 秒")
    print(f"回复: {preview}")
    if result.total_tokens is not None:
        print(
            "Token 用量: "
            f"输入 {result.prompt_tokens}，输出 {result.completion_tokens}，"
            f"合计 {result.total_tokens}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(check_llm()))