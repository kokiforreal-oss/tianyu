"""从已确认的任务字段整理 NPC。坐标没有单独来源时保持为空。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from analyzer.quest_analyzer import QuestCatalog
from database.records import NpcRecord


@dataclass(slots=True)
class NpcEntry:
    """目录中的 NPC。`npc_id` 只是本目录的稳定编号，不是游戏内部编号。"""

    npc_id: str
    npc_name: str
    quest_ids: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    position_x: int | None = None
    position_y: int | None = None
    map_id: str | None = None

    def to_record(self) -> NpcRecord:
        """转成数据库记录。多名任务提到同一 NPC 时，不挑选其中一个作为唯一关联任务。"""
        related = self.quest_ids[0] if len(self.quest_ids) == 1 else None
        return NpcRecord(
            npc_id=self.npc_id,
            source=" | ".join(self.sources),
            npc_name=self.npc_name,
            map_id=self.map_id,
            position_x=self.position_x,
            position_y=self.position_y,
            related_quest=related,
            confidence=1.0 if self.sources else None,
        )


def build_npc_catalog(quests: QuestCatalog) -> list[NpcEntry]:
    """收集任务页上已确认的起始 NPC 和结束 NPC。

    字段冲突或写明为“无”的名称不会进入目录，避免把不确定文本当成 NPC。
    """
    grouped: dict[str, NpcEntry] = {}
    for quest in quests.canonical_quests():
        for field_name in ("start_npc", "target_npc"):
            if field_name in quest.unconfirmed_fields or field_name in quest.confirmed_absent:
                continue
            name = getattr(quest, field_name)
            if not name:
                continue
            entry = grouped.get(name)
            if entry is None:
                entry = NpcEntry(npc_id=_catalog_id(name), npc_name=name)
                grouped[name] = entry
            if quest.quest_id not in entry.quest_ids:
                entry.quest_ids.append(quest.quest_id)
            if quest.source not in entry.sources:
                entry.sources.append(quest.source)
    return [grouped[name] for name in sorted(grouped)]


def _catalog_id(name: str) -> str:
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]
    return f"npc-{digest}"
