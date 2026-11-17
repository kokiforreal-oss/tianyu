"""游戏数据分析窗口。进程管理界面仍不在这里实现。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analyzer.client_analyzer import ClientAnalyzer, ClientInventory
from analyzer.game_state import GameState
from analyzer.map_catalog import MapCatalog
from analyzer.npc_catalog import NpcEntry, build_npc_catalog
from analyzer.path_planner import Obstacle, PathPlanner, PlannerEdge, PlannerNode
from analyzer.quest_analyzer import QuestAnalyzer, QuestCatalog
from analyzer.screen_analyzer import ScreenAnalyzer, ScreenRegion
from database.records import MapRecord

_STYLE = """
QMainWindow, QWidget { background: #1e1f22; color: #e6e6e6; }
QLineEdit, QPlainTextEdit, QTableWidget {
    background: #2b2d31; color: #e6e6e6; border: 1px solid #3c3f45;
}
QPushButton { background: #3c4048; color: #f2f2f2; padding: 6px 10px; border: none; }
QHeaderView::section { background: #32343a; color: #f2f2f2; padding: 4px; }
QTabBar::tab { background: #2b2d31; color: #cccccc; padding: 8px 12px; }
QTabBar::tab:selected { background: #3d6b8a; color: white; }
QLabel#hint { color: #b8c0cc; }
"""


class AnalyzerWindow(QMainWindow):
    """七个分析页面。所有结果都保留来源，缺少的数据会直接写出来。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Tianyu Manager - 游戏数据分析")
        self.resize(1100, 720)
        self.setStyleSheet(_STYLE)
        self.quest_analyzer = QuestAnalyzer()
        self.quest_catalog: QuestCatalog | None = None
        self.map_catalog = MapCatalog()
        self.npc_entries: list[NpcEntry] = []
        self.client_inventory: ClientInventory | None = None
        self.states: list[GameState] = []

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_client_page(), "客户端文件分析")
        self.tabs.addTab(self._build_map_page(), "地图资料库")
        self.tabs.addTab(self._build_npc_page(), "NPC 资料库")
        self.tabs.addTab(self._build_quest_page(), "任务资料库")
        self.tabs.addTab(self._build_path_page(), "路径规划研究")
        self.tabs.addTab(self._build_screen_page(), "游戏画面分析")
        self.tabs.addTab(self._build_state_page(), "游戏状态监控")
        self.setCentralWidget(self.tabs)
        self.status = QLabel("分析模块已就绪。进程管理界面尚未接入。")
        self.status.setObjectName("hint")
        self.statusBar().addWidget(self.status)
        self.load_quests()

    def _build_client_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.client_path = QLineEdit()
        self.client_path.setPlaceholderText("选择游戏客户端目录")
        browse = QPushButton("浏览")
        browse.clicked.connect(self.browse_client)
        scan = QPushButton("扫描")
        scan.clicked.connect(self.scan_client)
        export = QPushButton("导出 JSON")
        export.clicked.connect(self.export_client)
        row.addWidget(self.client_path)
        row.addWidget(browse)
        row.addWidget(scan)
        row.addWidget(export)
        layout.addLayout(row)
        self.client_table = _table(["相对路径", "类别", "大小", "修改时间", "配置文件", "仅元信息"])
        layout.addWidget(self.client_table)
        return page

    def _build_map_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.map_note = QLabel(self.map_catalog.guide_gap_note())
        self.map_note.setObjectName("hint")
        self.map_note.setWordWrap(True)
        layout.addWidget(self.map_note)
        form = QFormLayout()
        self.map_id = QLineEdit()
        self.map_name = QLineEdit()
        self.map_width = QLineEdit()
        self.map_height = QLineEdit()
        self.map_source = QLineEdit()
        self.map_width.setPlaceholderText("未知则留空")
        self.map_height.setPlaceholderText("未知则留空")
        form.addRow("地图编号", self.map_id)
        form.addRow("地图名称", self.map_name)
        form.addRow("宽度", self.map_width)
        form.addRow("高度", self.map_height)
        form.addRow("来源", self.map_source)
        layout.addLayout(form)
        add = QPushButton("添加地图")
        add.clicked.connect(self.add_map)
        layout.addWidget(add)
        self.map_table = _table(["地图编号", "名称", "宽度", "高度", "来源", "可信度"])
        layout.addWidget(self.map_table)
        return page

    def _build_npc_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel("只提取任务指南里已经确认的 NPC 名称。坐标留空。")
        hint.setObjectName("hint")
        layout.addWidget(hint)
        button = QPushButton("从任务指南提取")
        button.clicked.connect(self.load_npcs)
        layout.addWidget(button)
        self.npc_table = _table(["目录编号", "名称", "坐标", "关联任务数", "来源"])
        layout.addWidget(self.npc_table)
        return page

    def _build_quest_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        button = QPushButton("重新加载官方任务快照")
        button.clicked.connect(self.load_quests)
        layout.addWidget(button)
        self.quest_table = _table(["编号", "名称", "等级", "前续", "后续", "目标地图", "来源"])
        layout.addWidget(self.quest_table, 2)
        self.quest_order = QPlainTextEdit()
        self.quest_order.setReadOnly(True)
        layout.addWidget(self.quest_order, 1)
        return page

    def _build_path_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel("每行一条连接：起点 终点 长度。长度可省略。这只是理论路径。")
        hint.setObjectName("hint")
        layout.addWidget(hint)
        self.edge_input = QPlainTextEdit()
        self.edge_input.setPlaceholderText("map-a map-b 2")
        layout.addWidget(self.edge_input)
        form = QFormLayout()
        self.path_start = QLineEdit()
        self.path_goal = QLineEdit()
        self.path_obstacles = QLineEdit()
        self.path_source = QLineEdit()
        self.path_obstacles.setPlaceholderText("障碍节点，用空格分隔，可留空")
        form.addRow("起点", self.path_start)
        form.addRow("终点", self.path_goal)
        form.addRow("障碍", self.path_obstacles)
        form.addRow("数据来源", self.path_source)
        layout.addLayout(form)
        button = QPushButton("计算理论路径")
        button.clicked.connect(self.plan_path)
        layout.addWidget(button)
        self.path_result = QPlainTextEdit()
        self.path_result.setReadOnly(True)
        layout.addWidget(self.path_result)
        return page

    def _build_screen_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel("区域坐标需要按自己的游戏窗口校准。默认不预置坐标，也不识别文字。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        self.screen_path = QLineEdit()
        browse = QPushButton("选择截图")
        browse.clicked.connect(self.browse_screenshot)
        analyze = QPushButton("分析区域")
        analyze.clicked.connect(self.analyze_screen)
        row.addWidget(self.screen_path)
        row.addWidget(browse)
        row.addWidget(analyze)
        layout.addLayout(row)
        self.region_table = _table(["区域", "X", "Y", "宽度", "高度"])
        for name in ("地图名称", "血量", "魔法", "任务文字", "NPC 名称"):
            _append_row(self.region_table, [name, "0", "0", "0", "0"])
        self.region_table.setEditTriggers(QTableWidget.EditTrigger.AllEditTriggers)
        layout.addWidget(self.region_table)
        self.screen_result = QPlainTextEdit()
        self.screen_result.setReadOnly(True)
        layout.addWidget(self.screen_result)
        return page

    def _build_state_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.state_fields = {
            "player_name": QLineEdit(),
            "map_name": QLineEdit(),
            "player_position": QLineEdit(),
            "hp": QLineEdit(),
            "mp": QLineEdit(),
            "target_name": QLineEdit(),
            "current_quest": QLineEdit(),
            "quest_progress": QLineEdit(),
            "data_source": QLineEdit(),
        }
        labels = {
            "player_name": "角色名",
            "map_name": "地图",
            "player_position": "坐标",
            "hp": "血量",
            "mp": "魔法",
            "target_name": "目标",
            "current_quest": "当前任务",
            "quest_progress": "任务进度",
            "data_source": "数据来源",
        }
        for key, label in labels.items():
            form.addRow(label, self.state_fields[key])
        layout.addLayout(form)
        button = QPushButton("记录观察")
        button.clicked.connect(self.record_state)
        layout.addWidget(button)
        self.state_result = QPlainTextEdit()
        self.state_result.setReadOnly(True)
        layout.addWidget(self.state_result)
        return page

    def browse_client(self) -> None:
        """选择客户端目录。"""
        selected = QFileDialog.getExistingDirectory(self, "选择客户端目录")
        if selected:
            self.client_path.setText(selected)

    def scan_client(self) -> None:
        """扫描客户端目录并刷新表格。"""
        raw_path = self.client_path.text().strip()
        if not raw_path:
            self.status.setText("请先填写客户端目录。")
            return
        try:
            self.client_inventory = ClientAnalyzer().scan(raw_path)
        except NotADirectoryError as exc:
            self.status.setText(str(exc))
            return
        self.client_table.setRowCount(0)
        for item in self.client_inventory.files:
            _append_row(
                self.client_table,
                [
                    item.relative_path,
                    item.category,
                    str(item.size_bytes),
                    item.modified_time,
                    "是" if item.is_config else "否",
                    "是" if item.metadata_only else "否",
                ],
            )
        self.status.setText(f"已扫描 {len(self.client_inventory.files)} 个文件。")

    def export_client(self) -> None:
        """把最近一次扫描导出为 JSON。"""
        if self.client_inventory is None:
            self.status.setText("还没有扫描结果。")
            return
        selected, _ = QFileDialog.getSaveFileName(self, "导出资源清单", "client-inventory.json", "JSON (*.json)")
        if not selected:
            return
        self.client_inventory.write_json(Path(selected))
        self.status.setText(f"已导出 {selected}")

    def add_map(self) -> None:
        """添加一张用户提供了来源的地图。空白宽高保持为未知。"""
        try:
            record = MapRecord(
                map_id=self.map_id.text().strip(),
                map_name=self.map_name.text().strip() or None,
                width=_optional_int(self.map_width.text()),
                height=_optional_int(self.map_height.text()),
                source=self.map_source.text().strip(),
                confidence=1.0 if self.map_source.text().strip() else None,
            )
            self.map_catalog.add(record)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self._refresh_maps()
        self.status.setText(f"已添加地图 {record.map_id}。缺少宽高的地图：{len(self.map_catalog.missing_geometry())}。")

    def load_npcs(self) -> None:
        """从已加载的任务快照提取 NPC。"""
        if self.quest_catalog is None:
            self.load_quests()
        if self.quest_catalog is None:
            return
        self.npc_entries = build_npc_catalog(self.quest_catalog)
        self.npc_table.setRowCount(0)
        for entry in self.npc_entries:
            _append_row(
                self.npc_table,
                [
                    entry.npc_id,
                    entry.npc_name,
                    "-",
                    str(len(entry.quest_ids)),
                    entry.sources[0] if entry.sources else "",
                ],
            )
        self.status.setText(f"已提取 {len(self.npc_entries)} 个 NPC，坐标均未填写。")

    def load_quests(self) -> None:
        """加载官方任务快照，并展示可以确认的顺序。"""
        try:
            self.quest_catalog = self.quest_analyzer.load_snapshot()
        except OSError as exc:
            self.status.setText(f"无法读取任务快照: {exc}")
            return
        self.quest_table.setRowCount(0)
        for quest in self.quest_catalog.canonical_quests():
            _append_row(
                self.quest_table,
                [
                    quest.quest_id,
                    quest.quest_name,
                    "-" if quest.min_level is None else str(quest.min_level),
                    quest.prerequisite_name or ("无" if "prerequisite_name" in quest.confirmed_absent else "未确认"),
                    quest.next_quest_name or ("无" if "next_quest_name" in quest.confirmed_absent else "未确认"),
                    quest.target_map or "未提供",
                    quest.source,
                ],
            )
        report = self.quest_catalog.execution_report()
        lines = ["已确认的任务链："]
        for chain in report.chains:
            names = []
            for quest_id in chain:
                quest = self.quest_catalog.get(quest_id)
                names.append(quest.quest_name if quest else quest_id)
            lines.append(" -> ".join(names))
        if report.conflicts:
            lines.append("")
            lines.append("前后写法冲突，未采用：")
            lines.extend(report.conflicts)
        if report.unresolved_references:
            lines.append("")
            lines.append("指南提到但无法定位的任务：")
            lines.extend(report.unresolved_references)
        lines.append("")
        lines.extend(report.missing_data_notes)
        self.quest_order.setPlainText("\n".join(lines))
        self.status.setText(f"已加载 {len(self.quest_catalog.canonical_quests())} 条任务。")

    def plan_path(self) -> None:
        """根据文本框中的连接计算理论路径。"""
        try:
            edges = _parse_edges(self.edge_input.toPlainText())
            node_ids = {edge.source_id for edge in edges} | {edge.target_id for edge in edges}
            nodes = [PlannerNode(node_id) for node_id in sorted(node_ids)]
            obstacles = [
                Obstacle(node_id, source=self.path_source.text().strip() or "路径页障碍输入")
                for node_id in self.path_obstacles.text().split()
                if node_id
            ]
            planner = PathPlanner(nodes, edges, obstacles, data_source=self.path_source.text())
            plan = planner.plan(self.path_start.text().strip(), self.path_goal.text().strip())
        except ValueError as exc:
            self.path_result.setPlainText(str(exc))
            self.status.setText(str(exc))
            return
        lines = list(plan.messages)
        if plan.found:
            lines.append("路径：" + " -> ".join(plan.node_ids))
            lines.append(f"长度：{plan.length:g}")
        else:
            lines.append("没有得到路径。")
        self.path_result.setPlainText("\n".join(lines))
        self.status.setText("路径计算完成。" if plan.found else "路径数据不足。")

    def browse_screenshot(self) -> None:
        """选择一张游戏截图。"""
        selected, _ = QFileDialog.getOpenFileName(self, "选择截图", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if selected:
            self.screen_path.setText(selected)

    def analyze_screen(self) -> None:
        """按表格中的区域裁剪截图。"""
        raw_path = self.screen_path.text().strip()
        if not raw_path:
            self.status.setText("请先选择截图。")
            return
        regions: list[ScreenRegion] = []
        for row in range(self.region_table.rowCount()):
            name = self.region_table.item(row, 0).text()
            try:
                x, y, width, height = (_cell_int(self.region_table, row, column) for column in range(1, 5))
            except ValueError:
                self.status.setText(f"{name} 的区域坐标不是整数。")
                return
            regions.append(ScreenRegion(name, x, y, width, height))
        try:
            observations = ScreenAnalyzer().analyze(raw_path, regions, source=raw_path)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        lines = [f"{item.name}：{item.note}" + (f"；文字={item.text}" if item.text else "") for item in observations]
        self.screen_result.setPlainText("\n".join(lines))
        self.status.setText("画面区域已分析。未配置文字识别时不会猜测内容。")

    def record_state(self) -> None:
        """把当前表单记成一条观察。空白字段保持未知。"""
        values = {key: field.text().strip() for key, field in self.state_fields.items()}
        try:
            state = GameState(
                data_source=values.pop("data_source"),
                observation_timestamp=datetime.now(),
                player_name=values["player_name"] or None,
                map_name=values["map_name"] or None,
                player_position=values["player_position"] or None,
                hp=values["hp"] or None,
                mp=values["mp"] or None,
                target_name=values["target_name"] or None,
                current_quest=values["current_quest"] or None,
                quest_progress=values["quest_progress"] or None,
            )
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.states.append(state)
        unknown = "、".join(state.unknown_fields()) or "无"
        self.state_result.setPlainText(
            json.dumps(
                {
                    "data_source": state.data_source,
                    "hp": state.hp,
                    "map_name": state.map_name,
                    "unknown_fields": state.unknown_fields(),
                    "saved_to_mysql": False,
                },
                ensure_ascii=False,
                indent=2,
            )
            + f"\n尚未写入 MySQL。未知字段：{unknown}"
        )
        self.status.setText(f"已记录观察 {len(self.states)} 条。数据库写入需要先配置 MySQL。")

    def _refresh_maps(self) -> None:
        self.map_table.setRowCount(0)
        for record in self.map_catalog.maps.values():
            _append_row(
                self.map_table,
                [
                    record.map_id,
                    record.map_name or "",
                    "-" if record.width is None else str(record.width),
                    "-" if record.height is None else str(record.height),
                    record.source,
                    "-" if record.confidence is None else str(record.confidence),
                ],
            )


def run() -> int:
    """打开分析窗口。"""
    app = QApplication.instance() or QApplication([])
    window = AnalyzerWindow()
    window.show()
    return app.exec()


def _table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.horizontalHeader().setStretchLastSection(True)
    return table


def _append_row(table: QTableWidget, values: list[str]) -> None:
    row = table.rowCount()
    table.insertRow(row)
    for column, value in enumerate(values):
        table.setItem(row, column, QTableWidgetItem(value))


def _optional_int(text: str) -> int | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except ValueError as exc:
        raise ValueError(f"宽高必须是整数或留空: {text}") from exc


def _parse_edges(text: str) -> list[PlannerEdge]:
    edges: list[PlannerEdge] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) not in (2, 3):
            raise ValueError(f"第 {line_number} 行连接格式应为：起点 终点 长度")
        length = 1.0 if len(parts) == 2 else float(parts[2])
        edges.append(PlannerEdge(parts[0], parts[1], length))
    return edges


def _cell_int(table: QTableWidget, row: int, column: int) -> int:
    item = table.item(row, column)
    if item is None or not item.text().strip():
        return 0
    return int(item.text().strip())
