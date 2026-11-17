"""分析窗口的离屏测试。不打开真实窗口，也不连接游戏。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from ui.analyzer_window import AnalyzerWindow


@pytest.fixture(scope="module")
def qapp():
    """整个模块共用一个离屏 Qt 应用。"""
    return QApplication.instance() or QApplication([])


def test_analyzer_pages_scan_quests_and_plan(qapp, tmp_path) -> None:
    """七个页面可用：扫描目录、展示任务链，并计算理论路径。"""
    del qapp
    window = AnalyzerWindow()
    assert window.tabs.count() == 7
    titles = [window.tabs.tabText(index) for index in range(window.tabs.count())]
    assert titles == [
        "客户端文件分析",
        "地图资料库",
        "NPC 资料库",
        "任务资料库",
        "路径规划研究",
        "游戏画面分析",
        "游戏状态监控",
    ]

    client = tmp_path / "client"
    client.mkdir()
    (client / "setup.ini").write_text("lang=cn\n", encoding="utf-8")
    window.client_path.setText(str(client))
    window.scan_client()
    assert window.client_table.rowCount() == 1
    assert window.client_table.item(0, 1).text() == "INI"

    assert window.quest_table.rowCount() > 10
    assert "新来乍到1" in window.quest_order.toPlainText()

    window.load_npcs()
    assert window.npc_table.rowCount() > 0
    assert window.npc_table.item(0, 2).text() == "-"

    window.map_id.setText("sketch-1")
    window.map_source.setText("玩家草图")
    window.add_map()
    assert window.map_table.rowCount() == 1
    assert window.map_table.item(0, 2).text() == "-"

    window.edge_input.setPlainText("A B 2\nB C 3")
    window.path_start.setText("A")
    window.path_goal.setText("C")
    window.path_source.setText("手工连接")
    window.plan_path()
    result = window.path_result.toPlainText()
    assert "A -> B -> C" in result
    assert "长度：5" in result
    assert "理论路径" in result

    window.state_fields["hp"].setText("80")
    window.state_fields["data_source"].setText("手动观察")
    window.record_state()
    assert len(window.states) == 1
    assert window.states[0].map_name is None
    assert "未知字段" in window.state_result.toPlainText()
    window.close()
