"""地图资料目录。没有测量来源的宽高和连接不会被自动补上。"""

from __future__ import annotations

from dataclasses import dataclass, field

from database.records import MapRecord


@dataclass(slots=True)
class MapCatalog:
    """只保存调用方明确提供的地图记录。"""

    maps: dict[str, MapRecord] = field(default_factory=dict)

    def add(self, record: MapRecord) -> None:
        """加入一张地图。来源为空时拒绝，宽高可以继续为空。"""
        if not record.source or not record.source.strip():
            raise ValueError("地图记录必须填写来源")
        if not record.map_id.strip():
            raise ValueError("map_id 不能为空")
        self.maps[record.map_id] = record

    def missing_geometry(self) -> list[str]:
        """列出还没有宽高数据的地图。"""
        return [
            record.map_id
            for record in self.maps.values()
            if record.width is None or record.height is None
        ]

    def guide_gap_note(self) -> str:
        """说明官方任务页为什么不能直接变成地图底图。"""
        return "官方任务指南没有提供地图编号、宽度、高度和连接，这些字段保持为空。"
