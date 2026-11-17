"""截图区域和游戏状态测试。使用生成的图像，不读取游戏进程。"""

from __future__ import annotations

from datetime import datetime

import cv2
import numpy as np
import pytest

from analyzer.game_state import GameState
from analyzer.screen_analyzer import ScreenAnalyzer, ScreenRegion


def test_screen_analyzer_crops_region_and_does_not_invent_text(tmp_path) -> None:
    """未提供识别器时只裁剪，文字保持为空。"""
    image = np.zeros((40, 60, 3), dtype=np.uint8)
    image[5:15, 10:20] = (0, 0, 255)
    path = tmp_path / "shot.png"
    cv2.imwrite(str(path), image)

    seen: list[tuple[int, int]] = []

    def reader(crop: np.ndarray) -> tuple[str | None, float | None]:
        seen.append(crop.shape[:2])
        return "鲤鱼村", 0.3

    analyzer = ScreenAnalyzer()
    unread = analyzer.analyze(
        path,
        [ScreenRegion("地图名称", 10, 5, 10, 10)],
        source="测试截图",
    )
    assert unread[0].text is None
    assert unread[0].confidence is None
    assert "未进行文字识别" in unread[0].note

    recognized = analyzer.analyze(
        image,
        [ScreenRegion("地图名称", 10, 5, 10, 10)],
        source="测试截图",
        reader=reader,
    )
    assert seen == [(10, 10)]
    assert recognized[0].text == "鲤鱼村"
    assert recognized[0].confidence == 0.3

    outside = analyzer.analyze(
        image,
        [ScreenRegion("血量", 50, 30, 20, 10), ScreenRegion("魔法", 0, 0, 0, 10)],
        source="测试截图",
    )
    assert outside[0].text is None
    assert outside[0].note == "区域超出截图范围"
    assert outside[1].note == "区域尚未设置"


def test_game_state_keeps_unknown_fields_empty() -> None:
    """只填写来源时，其余状态字段都保持为空。"""
    moment = datetime(2026, 11, 17, 13, 40, 0)
    state = GameState(data_source="手动记录", observation_timestamp=moment, hp="120")
    assert state.unknown_fields() == [
        "player_name",
        "map_name",
        "player_position",
        "mp",
        "target_name",
        "current_quest",
        "quest_progress",
    ]
    restored = GameState.from_observation(state.to_observation())
    assert restored.hp == "120"
    assert restored.map_name is None
    assert restored.data_source == "手动记录"
    with pytest.raises(ValueError):
        GameState(data_source="  ", observation_timestamp=moment)
