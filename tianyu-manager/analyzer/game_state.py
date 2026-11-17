"""统一的游戏状态观察。每个字段都可以为空，并保留来源和可信度。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from database.records import GameObservation


@dataclass(slots=True)
class GameState:
    """某一次观察到的游戏状态。未知项保持 None。"""

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

    def __post_init__(self) -> None:
        """拒绝没有来源的状态，避免无法核对的记录进入资料库。"""
        if not self.data_source or not self.data_source.strip():
            raise ValueError("游戏状态必须填写数据来源")
        self.data_source = self.data_source.strip()

    def unknown_fields(self) -> list[str]:
        """返回这次观察里仍然为空的字段名。"""
        names = (
            "player_name",
            "map_name",
            "player_position",
            "hp",
            "mp",
            "target_name",
            "current_quest",
            "quest_progress",
        )
        return [name for name in names if getattr(self, name) in (None, "")]

    def to_observation(self) -> GameObservation:
        """转换成可以写入 game_observations 表的记录。"""
        return GameObservation(
            data_source=self.data_source,
            observation_timestamp=self.observation_timestamp,
            player_name=self.player_name,
            map_name=self.map_name,
            player_position=self.player_position,
            hp=self.hp,
            mp=self.mp,
            target_name=self.target_name,
            current_quest=self.current_quest,
            quest_progress=self.quest_progress,
            confidence=self.confidence,
        )

    @classmethod
    def from_observation(cls, observation: GameObservation) -> GameState:
        """从数据库记录恢复。不会补上记录里没有的玩家或坐标。"""
        return cls(
            data_source=observation.data_source,
            observation_timestamp=observation.observation_timestamp,
            player_name=observation.player_name,
            map_name=observation.map_name,
            player_position=observation.player_position,
            hp=observation.hp,
            mp=observation.mp,
            target_name=observation.target_name,
            current_quest=observation.current_quest,
            quest_progress=observation.quest_progress,
            confidence=observation.confidence,
        )
