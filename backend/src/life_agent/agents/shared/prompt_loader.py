"""Load trusted, versioned prompt assets from the agent package."""

from pathlib import Path


class PromptAssetError(RuntimeError):
    """Raised when a trusted prompt asset cannot be loaded."""


def load_prompt(path: str) -> str:
    asset = Path(__file__).parent / path
    try:
        content = asset.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise PromptAssetError(f"无法加载提示资产: {asset}") from exc
    if not content:
        raise PromptAssetError(f"提示资产为空: {asset}")
    return content
