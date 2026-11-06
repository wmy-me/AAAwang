"""Bounded, trusted guidance-asset registry for Agent roles."""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from life_agent.agents.shared.prompt_loader import PromptAssetError


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    version: str
    scope: str
    triggers: tuple[str, ...]
    guidance: str
    source: str


_SKILL_ROOT = Path(__file__).parent
_REGISTERED: dict[str, SkillDefinition] = {}


def register_skill(skill: SkillDefinition) -> None:
    if not skill.name or not skill.version or not skill.guidance.strip():
        raise ValueError("Skill 必须包含名称、版本和指导内容。")
    _REGISTERED[skill.name] = skill


def _parse_skill(path: Path) -> SkillDefinition:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise PromptAssetError(f"无法加载 Skill: {path}") from exc
    metadata: dict[str, str] = {}
    body: list[str] = []
    in_metadata = False
    for line in lines:
        if line.strip() == "---" and not in_metadata:
            in_metadata = True
            continue
        if line.strip() == "---" and in_metadata:
            in_metadata = False
            continue
        if in_metadata and ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip()
        elif not in_metadata:
            body.append(line)
    triggers = tuple(
        item.strip() for item in metadata.get("triggers", "").split(",") if item.strip()
    )
    skill = SkillDefinition(
        name=metadata.get("name", path.stem),
        version=metadata.get("version", "unversioned"),
        scope=metadata.get("scope", ""),
        triggers=triggers,
        guidance="\n".join(body).strip(),
        source=str(path),
    )
    register_skill(skill)
    return skill


def available_skills() -> tuple[SkillDefinition, ...]:
    for path in sorted(_SKILL_ROOT.glob("*.md")):
        if path.stem not in _REGISTERED:
            _parse_skill(path)
    return tuple(_REGISTERED.values())


def shopping_guidance() -> str:
    """Load the single reusable procurement guide without keyword selection."""
    path = _SKILL_ROOT / "shopping_guidance.md"
    skill = _REGISTERED.get("shopping_guidance") or _parse_skill(path)
    return f"通用采购指导：{skill.name} v{skill.version}\n{skill.guidance}"


def select_skill(
    text: str, *, allowed_names: Iterable[str] | None = None
) -> SkillDefinition | None:
    allowed = set(allowed_names) if allowed_names is not None else None
    matches = [
        skill
        for skill in available_skills()
        if (allowed is None or skill.name in allowed)
        and any(trigger in text for trigger in skill.triggers)
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def skill_context(text: str, *, allowed_names: Iterable[str] | None = None) -> str:
    selected = select_skill(text, allowed_names=allowed_names)
    if selected is None:
        return "未选择场景 Skill。"
    return f"场景 Skill：{selected.name} v{selected.version}\n{selected.guidance}"
