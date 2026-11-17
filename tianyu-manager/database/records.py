"""分析库中的记录。未知字段保持为空，不在这里填入推测值。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class MapRecord:
    """地图资料。宽高、NPC 和连接没有来源时必须留空。"""

    map_id: str
    source: str
    map_name: str | None = None
    map_type: str | None = None
    width: int | None = None
    height: int | None = None
    npc_list: list[str] | None = None
    connection_list: list[str] | None = None
    confidence: float | None = None


@dataclass(slots=True)
class NpcRecord:
    """NPC 资料。坐标没有明确来源时保持为空。"""

    npc_id: str
    source: str
    npc_name: str | None = None
    map_id: str | None = None
    position_x: int | None = None
    position_y: int | None = None
    npc_type: str | None = None
    related_quest: str | None = None
    confidence: float | None = None


@dataclass(slots=True)
class MapConnectionRecord:
    """两条地图之间的连接。只保存调用方已经说明来源的关系。"""

    connection_id: str
    from_map_id: str
    to_map_id: str
    source: str
    confidence: float | None = None
    note: str | None = None


@dataclass(slots=True)
class GameObservation:
    """一次游戏状态观察。除来源和时间外，其余字段都可以为空。"""

    data_source: str
    observation_timestamp: datetime
    player_name: str | None = None
    map_name: str | None = None
    player_position: str | None = None
    hp: str | None = None
    mp: str | None = None
    target_name: str | None = None
    current_quest: str | None = None
    quest_progress: str | None = None
    confidence: float | None = None
    observation_id: int | None = None
