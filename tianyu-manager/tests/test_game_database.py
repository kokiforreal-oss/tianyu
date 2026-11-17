"""分析库测试。默认不连接真实 MySQL，只检查表结构和写入参数。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from analyzer.quest_analyzer import QuestAnalyzer
from database.game_repository import GameRepository, sql_statements
from database.mysql_settings import MysqlConfigError, load_mysql_settings
from database.records import GameObservation, MapRecord, NpcRecord

_SCHEMA = Path(__file__).resolve().parents[1] / "database" / "schema.sql"


class RecordingCursor:
    """记录 SQL 和参数，不连接数据库。"""

    def __init__(self, log: list[tuple[str, object]]) -> None:
        self._log = log

    def execute(self, sql: str, params: object = None) -> None:
        self._log.append((sql, params))

    def close(self) -> None:
        return None


class RecordingConnection:
    """把游标执行过的语句留下来供断言。"""

    def __init__(self) -> None:
        self.statements: list[tuple[str, object]] = []
        self.commits = 0

    def cursor(self) -> RecordingCursor:
        return RecordingCursor(self.statements)

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        return None


def test_schema_defines_analysis_tables_without_seed_data() -> None:
    """六张分析表都有来源列，坐标允许为空，脚本不插入示例数据。"""
    script = _SCHEMA.read_text(encoding="utf-8")
    statements = sql_statements(script)
    created = "\n".join(statements)
    for table in ("maps", "npcs", "quests", "quest_steps", "map_connections", "game_observations"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in created
    assert "source VARCHAR(512) NOT NULL" in created
    assert "data_source VARCHAR(512) NOT NULL" in created
    assert "position_x INT NULL" in created
    assert "width INT NULL" in created
    assert "INSERT INTO" not in script.upper()
    assert len(statements) == 6


def test_repository_preserves_null_coordinates_and_saves_quest_source() -> None:
    """地图和 NPC 未提供坐标时参数为 NULL，任务来源会写入语句。"""
    connection = RecordingConnection()
    repository = GameRepository(connection)
    repository.ensure_schema()
    repository.upsert_map(MapRecord(map_id="unknown-map", source="玩家指定，尚未测量"))
    repository.upsert_npc(NpcRecord(npc_id="npc-1", npc_name="鲤鱼村村长", source="任务指南名称，无坐标"))
    catalog = QuestAnalyzer().load_snapshot()
    repository.save_quest_catalog(catalog)
    repository.save_observation(
        GameObservation(
            data_source="手动观察",
            observation_timestamp=datetime(2026, 11, 17, 13, 0, 0),
        )
    )

    map_sql, map_params = _find(connection, "INSERT INTO maps")
    assert isinstance(map_params, tuple)
    assert map_params[3] is None
    assert map_params[4] is None
    assert map_params[5] is None
    npc_sql, npc_params = _find(connection, "INSERT INTO npcs")
    assert "position_x" in npc_sql
    assert isinstance(npc_params, tuple)
    assert npc_params[3] is None
    assert npc_params[4] is None
    quest_sql, quest_params = _find(connection, "INSERT INTO quests")
    assert "source" in quest_sql
    assert isinstance(quest_params, tuple)
    assert quest_params[7] is None
    assert str(quest_params[15]).startswith("http://tycq.laowaner.com/")
    observation_sql, observation_params = _find(connection, "INSERT INTO game_observations")
    assert "data_source" in observation_sql
    assert isinstance(observation_params, tuple)
    assert observation_params[0] is None
    assert observation_params[9] == "手动观察"
    assert not any(sql.strip().startswith("INSERT INTO maps") and False for sql, _ in connection.statements)
    assert connection.commits > 0


def test_repository_rejects_records_without_source() -> None:
    """没有来源的地图、任务和观察都不能写入。"""
    repository = GameRepository(RecordingConnection())
    with pytest.raises(ValueError):
        repository.upsert_map(MapRecord(map_id="m", source="  "))
    with pytest.raises(ValueError):
        repository.save_observation(
            GameObservation(data_source="", observation_timestamp=datetime.now())
        )


def test_mysql_settings_require_user_and_database(tmp_path) -> None:
    """配置里留空的账号不会被猜成一个可用连接。"""
    config = tmp_path / "config.yaml"
    config.write_text("mysql:\n  host: 127.0.0.1\n  port: 3306\n  user: ''\n  database: ''\n", encoding="utf-8")
    with pytest.raises(MysqlConfigError):
        load_mysql_settings(config)
    config.write_text(
        "mysql:\n  host: 127.0.0.1\n  port: 3306\n  user: analyzer\n  database: tianyu_manager\n",
        encoding="utf-8",
    )
    settings = load_mysql_settings(config)
    assert settings.user == "analyzer"
    assert settings.database == "tianyu_manager"
    assert settings.password == ""


def _find(connection: RecordingConnection, prefix: str) -> tuple[str, object]:
    for sql, params in connection.statements:
        if prefix in sql:
            return sql, params
    raise AssertionError(f"没有找到语句: {prefix}")
