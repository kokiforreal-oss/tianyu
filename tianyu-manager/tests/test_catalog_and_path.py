"""NPC、地图和理论路径测试。"""

from __future__ import annotations

import pytest

from analyzer.map_catalog import MapCatalog
from analyzer.npc_catalog import build_npc_catalog
from analyzer.path_planner import Obstacle, PathPlanner, PlannerEdge, PlannerNode
from analyzer.quest_analyzer import QuestAnalyzer
from database.records import MapConnectionRecord, MapRecord


def test_npc_catalog_uses_confirmed_names_without_coordinates() -> None:
    """任务页写明的 NPC 可以建档，坐标保持为空。"""
    catalog = build_npc_catalog(QuestAnalyzer().load_snapshot())
    by_name = {item.npc_name: item for item in catalog}
    mayor = by_name["鲤鱼村村长"]
    assert mayor.position_x is None
    assert mayor.position_y is None
    assert mayor.map_id is None
    assert mayor.sources
    assert "guide-73" in mayor.quest_ids or "guide-74" in mayor.quest_ids
    assert all(item.position_x is None and item.position_y is None for item in catalog)


def test_map_catalog_rejects_missing_source_and_keeps_null_size() -> None:
    """地图没有来源不能入库，也没有默认宽高。"""
    catalog = MapCatalog()
    with pytest.raises(ValueError):
        catalog.add(MapRecord(map_id="village", source=""))
    catalog.add(MapRecord(map_id="village", map_name="未测量区域", source="玩家草图"))
    assert catalog.maps["village"].width is None
    assert catalog.missing_geometry() == ["village"]
    assert "没有提供" in catalog.guide_gap_note()


def test_path_planner_reports_length_and_missing_links() -> None:
    """有连接时给出理论路径和长度；缺数据或障碍时明确说明。"""
    planner = PathPlanner(
        [PlannerNode("A"), PlannerNode("B"), PlannerNode("C"), PlannerNode("D")],
        [PlannerEdge("A", "B", 2), PlannerEdge("B", "C", 3), PlannerEdge("A", "D", 9)],
        data_source="测试用连接",
    )
    plan = planner.plan("A", "C")
    assert plan.found is True
    assert plan.node_ids == ["A", "B", "C"]
    assert plan.length == 5
    assert plan.theoretical_only is True
    assert any("不等于游戏内实际寻路" in message for message in plan.messages)

    blocked = PathPlanner(
        [PlannerNode("A"), PlannerNode("B"), PlannerNode("C")],
        [PlannerEdge("A", "B", 1), PlannerEdge("B", "C", 1)],
        [Obstacle("B", source="玩家标注的障碍")],
        data_source="测试用连接",
    )
    blocked_plan = blocked.plan("A", "C")
    assert blocked_plan.found is False
    assert blocked_plan.node_ids == []
    assert any("缺少可通行连接" in message or "障碍" in message for message in blocked_plan.messages)

    empty = PathPlanner([], [], data_source="空数据库")
    empty_plan = empty.plan("A", "B")
    assert empty_plan.found is False
    assert any("缺少地图连接数据" in message for message in empty_plan.messages)

    missing = planner.plan("A", "不存在")
    assert missing.found is False
    assert any("缺少节点数据" in message for message in missing.messages)


def test_path_planner_can_read_saved_connections() -> None:
    """数据库里的连接可以建图，没有连接引用的地图不会被编出来。"""
    planner = PathPlanner.from_connections(
        [
            MapConnectionRecord("c1", "map-a", "map-b", source="手工录入"),
            MapConnectionRecord("c2", "map-b", "map-c", source="手工录入"),
        ],
        data_source="map_connections 表",
    )
    plan = planner.plan("map-a", "map-c")
    assert plan.node_ids == ["map-a", "map-b", "map-c"]
    assert plan.length == 2
