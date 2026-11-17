"""基于已录入的地图连接做理论路径研究。

这里使用 NetworkX 的 A*。启发函数固定为 0，因为边的长度不一定是平面距离，
不能用坐标去高估代价。计算结果不等于游戏客户端里的实际寻路。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from database.records import MapConnectionRecord


@dataclass(slots=True)
class PlannerNode:
    """路径图中的一个点。坐标可空。"""

    node_id: str
    x: float | None = None
    y: float | None = None


@dataclass(slots=True)
class PlannerEdge:
    """两个点之间的可通行连接，以及调用方给出的长度。"""

    source_id: str
    target_id: str
    length: float = 1.0


@dataclass(slots=True)
class Obstacle:
    """已经标明来源的障碍点。没有来源的障碍不会被接受。"""

    node_id: str
    source: str


@dataclass(slots=True)
class PathPlan:
    """一次理论路径结果。"""

    found: bool
    node_ids: list[str] = field(default_factory=list)
    length: float | None = None
    theoretical_only: bool = True
    messages: list[str] = field(default_factory=list)


class PathPlanner:
    """在已知节点和连接上搜索理论路径。"""

    def __init__(
        self,
        nodes: list[PlannerNode],
        edges: list[PlannerEdge],
        obstacles: list[Obstacle] | None = None,
        data_source: str = "",
    ) -> None:
        """保存图数据。

        参数:
            nodes: 已知节点。
            edges: 已知连接。
            obstacles: 不能经过的节点，每条都要有来源。
            data_source: 这批连接数据的来源说明。

        异常:
            ValueError: 数据来源或障碍来源为空，或连接长度小于 0。
        """
        if not data_source or not data_source.strip():
            raise ValueError("路径数据必须填写来源")
        self.data_source = data_source.strip()
        self.nodes = {node.node_id: node for node in nodes}
        self.edges = list(edges)
        self.obstacles: dict[str, Obstacle] = {}
        for obstacle in obstacles or []:
            if not obstacle.source or not obstacle.source.strip():
                raise ValueError("障碍物数据必须填写来源")
            if obstacle.node_id not in self.nodes:
                raise ValueError(f"障碍物节点不存在: {obstacle.node_id}")
            self.obstacles[obstacle.node_id] = obstacle
        for edge in self.edges:
            if edge.length < 0:
                raise ValueError("连接长度不能为负数")

    @classmethod
    def from_connections(
        cls,
        connections: list[MapConnectionRecord],
        data_source: str,
    ) -> PathPlanner:
        """用数据库中的地图连接建图。没有坐标，长度按 1 计算。"""
        node_ids: set[str] = set()
        edges: list[PlannerEdge] = []
        for connection in connections:
            node_ids.add(connection.from_map_id)
            node_ids.add(connection.to_map_id)
            edges.append(PlannerEdge(connection.from_map_id, connection.to_map_id, 1.0))
        nodes = [PlannerNode(node_id) for node_id in sorted(node_ids)]
        return cls(nodes, edges, data_source=data_source)

    def plan(self, start: str, goal: str) -> PathPlan:
        """搜索从起点到终点的理论路径。

        缺少节点、缺少连接或被障碍挡住时，返回说明，不补造路径。
        """
        messages = [
            "这是根据已录入连接算出的理论路径，不等于游戏内实际寻路。",
            f"数据来源：{self.data_source}",
        ]
        if not self.edges:
            messages.append("缺少地图连接数据，无法计算路径。")
            return PathPlan(False, messages=messages)
        missing = [name for name in (start, goal) if name not in self.nodes]
        if missing:
            messages.append("缺少节点数据：" + "、".join(missing))
            return PathPlan(False, messages=messages)
        if start in self.obstacles or goal in self.obstacles:
            messages.append("起点或终点位于已标记障碍，未计算穿越该障碍的路径。")
            return PathPlan(False, messages=messages)
        if self.obstacles:
            blocked_names = "、".join(sorted(self.obstacles))
            messages.append(f"已排除有来源标记的障碍节点：{blocked_names}")

        graph = nx.Graph()
        graph.add_nodes_from(node_id for node_id in self.nodes if node_id not in self.obstacles)
        ignored: list[str] = []
        for edge in self.edges:
            if edge.source_id not in self.nodes or edge.target_id not in self.nodes:
                ignored.append(f"{edge.source_id}->{edge.target_id}")
                continue
            if edge.source_id in self.obstacles or edge.target_id in self.obstacles:
                continue
            graph.add_edge(edge.source_id, edge.target_id, weight=edge.length)
        if ignored:
            messages.append("已忽略引用未知节点的连接：" + "、".join(ignored))
        if start not in graph or goal not in graph:
            messages.append("起点和终点之间缺少可通行连接。")
            return PathPlan(False, messages=messages)
        try:
            node_ids = nx.astar_path(graph, start, goal, heuristic=lambda _left, _right: 0, weight="weight")
        except nx.NetworkXNoPath:
            messages.append("已知连接无法把起点连到终点。")
            return PathPlan(False, messages=messages)
        length = 0.0
        for left, right in zip(node_ids, node_ids[1:]):
            length += float(graph[left][right]["weight"])
        return PathPlan(True, node_ids=node_ids, length=length, messages=messages)
