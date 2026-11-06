"""Trusted persistence and bounded recall for explicit user preferences."""

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from life_agent.db.models import UserPreference

_SENSITIVE = re.compile(r"(?:password|密码|token|密钥|secret|身份证|银行卡|支付)", re.IGNORECASE)
_SPACE = re.compile(r"\s+")
_CATEGORY_TERMS = {
    "diet": ("吃", "餐", "饭", "食", "辣", "过敏", "口味", "饮品"),
    "shopping": ("买", "购物", "商品", "品牌", "颜色", "尺码"),
    "accessibility": ("无障碍", "轮椅", "过敏", "视力", "听力"),
    "communication": ("简短", "语言", "称呼", "回复"),
}


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


def apply_memory_action(
    db: Session, owner_id: uuid.UUID, source_message_id: uuid.UUID, action: dict[str, object]
) -> str:
    """Execute a persisted model proposal; owner and source are always server supplied."""
    operation = action.get("memory_action")
    if operation == "list":
        items = list(db.scalars(select(UserPreference).where(UserPreference.owner_id == owner_id, UserPreference.status == "active").order_by(UserPreference.updated_at.desc()).limit(12)))
        return "我目前记住的偏好：" + ("；".join(f"{item.preference_key}：{item.content}" for item in items) if items else "（暂无）")
    safe = _safe(action.get("memory_category"), action.get("memory_key"), action.get("memory_value"))
    if safe is None:
        return "我不能保存或修改这条信息；请只提供普通偏好，不要包含密码、令牌、证件或支付信息。"
    category, key, value = safe
    item = db.scalar(select(UserPreference).where(UserPreference.owner_id == owner_id, UserPreference.category == category, UserPreference.preference_key == key).with_for_update())
    now = datetime.now(UTC)
    if operation == "remember":
        if item is None:
            item = UserPreference(owner_id=owner_id, category=category, preference_key=key, content=value, source_message_id=source_message_id, status="active")
            db.add(item)
        else:
            item.content, item.status, item.deleted_at, item.updated_at = value, "active", None, now
        db.commit()
        return f"已记住：{key}：{value}。"
    if item is None or item.status != "active":
        return "我没有找到可修改或删除的这条偏好。"
    if operation == "update":
        item.content, item.updated_at = value, now
        db.commit()
        return f"已更新：{key}：{value}。"
    if operation == "forget":
        item.status, item.deleted_at, item.updated_at = "deleted", now, now
        db.commit()
        return f"已忘记：{key}。"
    return "我没有识别到明确的记忆操作。"


def relevant_preferences(db: Session, owner_id: uuid.UUID, request: str, *, limit: int = 4) -> list[UserPreference]:
    """Return a small category-relevant subset, never the complete preference history."""
    text = request.casefold()
    categories = [category for category, terms in _CATEGORY_TERMS.items() if any(term in text for term in terms)]
    if not categories:
        return []
    return list(db.scalars(select(UserPreference).where(UserPreference.owner_id == owner_id, UserPreference.status == "active", UserPreference.category.in_(categories)).order_by(UserPreference.updated_at.desc()).limit(limit)))
