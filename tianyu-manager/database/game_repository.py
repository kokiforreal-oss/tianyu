"""把分析记录写入 MySQL。只保存调用方给出的字段，空值保持为 NULL。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from analyzer.quest_analyzer import QuestCatalog, QuestRecord
from database.records import GameObservation, MapConnectionRecord, MapRecord, NpcRecord

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def sql_statements(script: str) -> list[str]:
    """把建表脚本拆成单条语句，并去掉整行注释。"""
    statements: list[str] = []
    for part in script.split(";"):
        lines = [line for line in part.splitlines() if not line.strip().startswith("--")]
        statement = "\n".join(lines).strip()
        if statement:
            statements.append(statement)
    return statements


class GameRepository:
    """分析库读写。连接对象由调用方提供，便于测试替换。"""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def ensure_schema(self) -> None:
        """创建地图、NPC、任务、连接和观察记录表。"""
        script = _SCHEMA_PATH.read_text(encoding="utf-8")
        cursor = self._connection.cursor()
        try:
            for statement in sql_statements(script):
                cursor.execute(statement)
        finally:
            cursor.close()
        self._connection.commit()

    def upsert_map(self, record: MapRecord) -> None:
        """保存地图。未提供的宽高和清单写入 NULL，不用 0 或空列表代替。"""
        _require_source(record.source, "地图记录必须填写来源")
        if not record.map_id.strip():
            raise ValueError("map_id 不能为空")
        self._execute(
            """
            INSERT INTO maps (
                map_id, map_name, map_type, width, height,
                npc_list, connection_list, source, confidence
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                map_name = VALUES(map_name),
                map_type = VALUES(map_type),
                width = VALUES(width),
                height = VALUES(height),
                npc_list = VALUES(npc_list),
                connection_list = VALUES(connection_list),
                source = VALUES(source),
                confidence = VALUES(confidence)
            """,
            (
                record.map_id,
                record.map_name,
                record.map_type,
                record.width,
                record.height,
                _json_or_none(record.npc_list),
                _json_or_none(record.connection_list),
                record.source,
                record.confidence,
            ),
        )

    def upsert_npc(self, record: NpcRecord) -> None:
        """保存 NPC。没有坐标来源时 position_x 和 position_y 保持 NULL。"""
        _require_source(record.source, "NPC 记录必须填写来源")
        if not record.npc_id.strip():
            raise ValueError("npc_id 不能为空")
        self._execute(
            """
            INSERT INTO npcs (
                npc_id, npc_name, map_id, position_x, position_y,
                npc_type, related_quest, source, confidence
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                npc_name = VALUES(npc_name),
                map_id = VALUES(map_id),
                position_x = VALUES(position_x),
                position_y = VALUES(position_y),
                npc_type = VALUES(npc_type),
                related_quest = VALUES(related_quest),
                source = VALUES(source),
                confidence = VALUES(confidence)
            """,
            (
                record.npc_id,
                record.npc_name,
                record.map_id,
                record.position_x,
                record.position_y,
                record.npc_type,
                record.related_quest,
                record.source,
                record.confidence,
            ),
        )

    def upsert_connection(self, record: MapConnectionRecord) -> None:
        """保存一条已经标明来源的地图连接。"""
        _require_source(record.source, "地图连接必须填写来源")
        self._execute(
            """
            INSERT INTO map_connections (
                connection_id, from_map_id, to_map_id, source, confidence, note
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                from_map_id = VALUES(from_map_id),
                to_map_id = VALUES(to_map_id),
                source = VALUES(source),
                confidence = VALUES(confidence),
                note = VALUES(note)
            """,
            (
                record.connection_id,
                record.from_map_id,
                record.to_map_id,
                record.source,
                record.confidence,
                record.note,
            ),
        )

    def save_observation(self, observation: GameObservation) -> None:
        """保存一次状态观察。玩家、地图、血量等未知项可以全部为空。"""
        _require_source(observation.data_source, "观察记录必须填写数据来源")
        self._execute(
            """
            INSERT INTO game_observations (
                player_name, map_name, player_position, hp, mp,
                target_name, current_quest, quest_progress,
                observation_timestamp, data_source, confidence
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                observation.player_name,
                observation.map_name,
                observation.player_position,
                observation.hp,
                observation.mp,
                observation.target_name,
                observation.current_quest,
                observation.quest_progress,
                observation.observation_timestamp,
                observation.data_source,
                observation.confidence,
            ),
        )

    def save_quest_catalog(self, catalog: QuestCatalog) -> None:
        """保存任务和已确认的步骤。冲突字段不会被写成确定步骤。"""
        for quest in catalog.quests:
            self.upsert_quest(quest)
            self.replace_quest_steps(quest)

    def upsert_quest(self, quest: QuestRecord) -> None:
        """插入或更新一条任务。来源为空时拒绝写入。"""
        _require_source(quest.source, "任务记录必须填写来源")
        self._execute(
            """
            INSERT INTO quests (
                quest_id, quest_name, guide_article_id, min_level, objective,
                start_npc, target_npc, target_map, required_items, reward_text,
                reward_items, completion_condition, prerequisite_name, next_quest_name,
                description, source, confidence, confirmed_absent, unconfirmed_fields,
                conflicts, duplicate_of
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON DUPLICATE KEY UPDATE
                quest_name = VALUES(quest_name),
                guide_article_id = VALUES(guide_article_id),
                min_level = VALUES(min_level),
                objective = VALUES(objective),
                start_npc = VALUES(start_npc),
                target_npc = VALUES(target_npc),
                target_map = VALUES(target_map),
                required_items = VALUES(required_items),
                reward_text = VALUES(reward_text),
                reward_items = VALUES(reward_items),
                completion_condition = VALUES(completion_condition),
                prerequisite_name = VALUES(prerequisite_name),
                next_quest_name = VALUES(next_quest_name),
                description = VALUES(description),
                source = VALUES(source),
                confidence = VALUES(confidence),
                confirmed_absent = VALUES(confirmed_absent),
                unconfirmed_fields = VALUES(unconfirmed_fields),
                conflicts = VALUES(conflicts),
                duplicate_of = VALUES(duplicate_of)
            """,
            _quest_params(quest),
        )

    def replace_quest_steps(self, quest: QuestRecord) -> None:
        """用当前已确认内容替换该任务的步骤。"""
        _require_source(quest.source, "任务步骤必须填写来源")
        self._execute("DELETE FROM quest_steps WHERE quest_id = %s", (quest.quest_id,))
        for order, step in enumerate(_confirmed_steps(quest), start=1):
            self._execute(
                """
                INSERT INTO quest_steps (
                    quest_id, step_order, step_type, content, target_npc,
                    target_map, required_items, source, confidence
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    quest.quest_id,
                    order,
                    step[0],
                    step[1],
                    quest.target_npc if step[0] == "objective" else None,
                    quest.target_map if step[0] == "objective" else None,
                    _json_or_none(quest.required_items) if step[0] == "objective" else None,
                    quest.source,
                    quest.confidence,
                ),
            )

    def _execute(self, sql: str, params: tuple[object, ...] | None = None) -> None:
        cursor = self._connection.cursor()
        try:
            cursor.execute(sql, params)
        finally:
            cursor.close()
        self._connection.commit()


def _quest_params(quest: QuestRecord) -> tuple[object, ...]:
    return (
        quest.quest_id,
        quest.quest_name,
        quest.guide_article_id,
        quest.min_level,
        quest.objective,
        quest.start_npc,
        quest.target_npc,
        quest.target_map,
        _json_or_none(quest.required_items),
        quest.reward_text,
        _json_or_none(quest.reward_items),
        quest.completion_condition,
        quest.prerequisite_name,
        quest.next_quest_name,
        quest.description,
        quest.source,
        quest.confidence,
        json.dumps(quest.confirmed_absent, ensure_ascii=False),
        json.dumps(quest.unconfirmed_fields, ensure_ascii=False),
        json.dumps(quest.conflicts, ensure_ascii=False),
        quest.duplicate_of,
    )


def _confirmed_steps(quest: QuestRecord) -> list[tuple[str, str]]:
    """只输出原文已经确认的步骤，冲突或缺失的关系不写进步骤表。"""
    steps: list[tuple[str, str]] = []
    if quest.prerequisite_name and "prerequisite_name" not in quest.unconfirmed_fields:
        steps.append(("prerequisite", quest.prerequisite_name))
    if quest.objective and "objective" not in quest.unconfirmed_fields:
        steps.append(("objective", quest.objective))
    if quest.completion_condition and "completion_condition" not in quest.unconfirmed_fields:
        steps.append(("completion", quest.completion_condition))
    if quest.next_quest_name and "next_quest_name" not in quest.unconfirmed_fields:
        steps.append(("next", quest.next_quest_name))
    return steps


def _json_or_none(value: list[str] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _require_source(source: str, message: str) -> None:
    if not source or not source.strip():
        raise ValueError(message)
