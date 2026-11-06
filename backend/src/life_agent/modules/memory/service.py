"""Owner-scoped adapter for the Mem0 OSS preference store.

Mem0/pgvector is the source of truth. The old ``user_preferences`` table is
left untouched for data safety but is deliberately not read or written here.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from life_agent.core.budget import RunBudget
from life_agent.core.config import PROJECT_ROOT, Settings

_SENSITIVE = re.compile(r"(?:password|密码|token|密钥|secret|验证码|身份证|银行卡|支付)", re.IGNORECASE)
_SPACE = re.compile(r"\s+")


class MemoryUnavailableError(RuntimeError):
    """The optional memory dependency or configured backing store failed."""


class MemoryClient(Protocol):
    def add(self, messages: list[dict[str, str]], **kwargs: Any) -> Any: ...
    def search(self, query: str, **kwargs: Any) -> Any: ...
    def get_all(self, **kwargs: Any) -> Any: ...
    def update(self, memory_id: str, **kwargs: Any) -> Any: ...
    def delete(self, memory_id: str) -> Any: ...


@dataclass(frozen=True)
class Preference:
    id: str
    content: str
    metadata: dict[str, Any]


def _clean(value: object, limit: int) -> str:
    return _SPACE.sub(" ", str(value or "").strip())[:limit]


def _safe(category: object, key: object, value: object) -> tuple[str, str, str] | None:
    category = _clean(category, 32).lower()
    key, value = _clean(key, 120), _clean(value, 500)
    if not category or not re.fullmatch(r"[a-z_]{1,32}", category) or not key or not value:
        return None
    if _SENSITIVE.search(f"{key} {value}"):
        return None
    return category, key, value


def _results(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = value.get("results", [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _preference(item: dict[str, Any]) -> Preference | None:
    memory_id, content = item.get("id"), item.get("memory")
    metadata = item.get("metadata") or {}
    if not isinstance(memory_id, str) or not isinstance(content, str) or not isinstance(metadata, dict):
        return None
    return Preference(memory_id, _clean(content, 500), metadata)


class Mem0PreferenceService:
    """Thin, testable Mem0 wrapper; all calls require a server-supplied owner."""

    def __init__(self, client: MemoryClient, *, recall_limit: int = 4) -> None:
        self._client = client
        self._recall_limit = recall_limit

    def _all_for_owner(self, owner_id: uuid.UUID) -> list[Preference]:
        try:
            raw = self._client.get_all(filters={"user_id": str(owner_id)}, top_k=24)
        except Exception as exc:
            raise MemoryUnavailableError("memory list failed") from exc
        return [pref for item in _results(raw) if (pref := _preference(item)) is not None]

    @staticmethod
    def _matching(items: list[Preference], category: str, key: str) -> list[Preference]:
        return [item for item in items if item.metadata.get("memory_category") == category and item.metadata.get("memory_key") == key]

    def apply(self, owner_id: uuid.UUID, source_message_id: uuid.UUID, action: dict[str, object], budget: RunBudget) -> str:
        operation = action.get("memory_action")
        if operation == "list":
            items = self._all_for_owner(owner_id)
            text = "；".join(f"{item.metadata.get('memory_key', '偏好')}：{item.content}" for item in items[:12])
            return "我目前记住的偏好：" + (text or "（暂无）")
        # Forget identifies an existing memory; it must not require a new value.
        if operation == "forget":
            category = _clean(action.get("memory_category"), 32).lower()
            key = _clean(action.get("memory_key"), 120)
            safe = (category, key, "") if category and re.fullmatch(r"[a-z_]{1,32}", category) and key and not _SENSITIVE.search(key) else None
        else:
            safe = _safe(action.get("memory_category"), action.get("memory_key"), action.get("memory_value"))
        if safe is None:
            return "我不能保存或修改这条信息；请只提供普通偏好，不要包含密码、令牌、证件或支付信息。"
        category, key, value = safe
        matches = self._matching(self._all_for_owner(owner_id), category, key)
        if operation == "remember":
            if any(item.metadata.get("source_message_id") == str(source_message_id) for item in matches):
                return f"已记住：{key}：{value}。"
            if matches:
                try:
                    self._client.update(matches[0].id, data=value, metadata={"memory_category": category, "memory_key": key})
                except Exception as exc:
                    raise MemoryUnavailableError("memory update failed") from exc
                return f"已更新：{key}：{value}。"
            # Mem0 fact extraction is an additional DeepSeek request.
            budget.reserve("model")
            try:
                self._client.add(
                    [{"role": "user", "content": f"{key}：{value}"}], user_id=str(owner_id),
                    metadata={"memory_category": category, "memory_key": key, "source_message_id": str(source_message_id), "memory_scope": "explicit_preference"}, infer=True,
                )
            except Exception as exc:
                raise MemoryUnavailableError("memory add failed") from exc
            return f"已记住：{key}：{value}。"
        if len(matches) != 1:
            return "我没有找到唯一可修改或删除的这条偏好；请说明偏好名称。"
        target = matches[0]
        try:
            if operation == "update":
                self._client.update(target.id, data=value, metadata={"memory_category": category, "memory_key": key})
                return f"已更新：{key}：{value}。"
            if operation == "forget":
                self._client.delete(target.id)
                return f"已忘记：{key}。"
        except Exception as exc:
            raise MemoryUnavailableError("memory mutation failed") from exc
        return "我没有识别到明确的记忆操作。"

    def relevant(self, owner_id: uuid.UUID, request: str) -> list[Preference]:
        query = _clean(request, 1000)
        if not query:
            return []
        try:
            raw = self._client.search(query, top_k=self._recall_limit, filters={"user_id": str(owner_id)})
        except Exception as exc:
            raise MemoryUnavailableError("memory search failed") from exc
        return [pref for item in _results(raw) if (pref := _preference(item)) is not None][:self._recall_limit]


def _mem0_config(settings: Settings) -> dict[str, Any]:
    if not settings.mem0_enabled:
        raise MemoryUnavailableError("memory is disabled")
    if settings.llm_api_key is None or not settings.llm_api_key.get_secret_value().strip():
        raise MemoryUnavailableError("DeepSeek configuration is missing")
    history_path = Path(settings.mem0_history_db_path)
    if not history_path.is_absolute():
        history_path = PROJECT_ROOT / history_path
    history_path.parent.mkdir(parents=True, exist_ok=True)
    database_url = settings.database_url.get_secret_value().replace("postgresql+psycopg://", "postgresql://", 1)
    return {
        "llm": {"provider": "deepseek", "config": {"model": settings.llm_model, "api_key": settings.llm_api_key.get_secret_value(), "deepseek_base_url": settings.llm_base_url}},
        "embedder": {"provider": "huggingface", "config": {"model": settings.mem0_embedder_model, "embedding_dims": settings.mem0_embedding_dimensions, "model_kwargs": {"device": "cpu"}}},
        "vector_store": {"provider": "pgvector", "config": {"connection_string": database_url, "collection_name": settings.mem0_collection, "embedding_model_dims": settings.mem0_embedding_dimensions}},
        "history_db_path": str(history_path),
    }


@lru_cache(maxsize=1)
def get_memory_service() -> Mem0PreferenceService:
    """Create one process-local SDK client with explicit persistent configuration."""
    settings = Settings()
    try:
        from mem0 import Memory
        return Mem0PreferenceService(Memory.from_config(_mem0_config(settings)), recall_limit=settings.mem0_recall_limit)
    except MemoryUnavailableError:
        raise
    except Exception as exc:
        raise MemoryUnavailableError("Mem0 initialization failed") from exc
