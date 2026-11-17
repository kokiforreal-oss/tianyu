"""从官方公开任务指南导入任务，并整理可以确认的先后关系。

同一字段若出现多个不同原文，不会挑选其中一个当成已确认信息。
指南页面没有单独给出的目标地图、所需物品和完成条件保持为空。
"""

from __future__ import annotations

import html
import json
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_LABELS = (
    "任务目的",
    "任务等级",
    "任务奖励",
    "起始NPC",
    "结束NPC",
    "任务前续",
    "任务后续",
    "任务描述",
)
_LABEL_RE = re.compile("(" + "|".join(_LABELS) + ")：")
_NONE_TOKENS = {"无", "暂无", "没有"}
_TITLE_SUFFIX = "-天羽传奇官网"
_FIELD_BY_LABEL = {
    "任务目的": "objective",
    "任务等级": "min_level",
    "任务奖励": "reward_text",
    "起始NPC": "start_npc",
    "结束NPC": "target_npc",
    "任务前续": "prerequisite_name",
    "任务后续": "next_quest_name",
    "任务描述": "description",
}
_ALWAYS_UNCONFIRMED = ("target_map", "required_items", "completion_condition")
_OFFICIAL_SNAPSHOT = Path(__file__).resolve().parent / "data" / "tycq_official_story_quests.json"


def official_quest_url(article_id: int) -> str:
    """返回天羽传奇官网资料站上一篇任务指南的地址。"""
    return (
        "http://tycq.laowaner.com/zlz/shownews.php"
        f"?extid=1&id={article_id}&lang=cn&subid=1&tid=10"
    )


@dataclass(slots=True)
class QuestRecord:
    """一条任务资料。空字段表示指南没有提供，或原文互相冲突。"""

    quest_id: str
    quest_name: str
    source: str
    guide_article_id: int | None = None
    min_level: int | None = None
    objective: str | None = None
    start_npc: str | None = None
    target_npc: str | None = None
    target_map: str | None = None
    required_items: list[str] | None = None
    reward_text: str | None = None
    reward_items: list[str] | None = None
    completion_condition: str | None = None
    prerequisite_name: str | None = None
    next_quest_name: str | None = None
    description: str | None = None
    confidence: float | None = None
    confirmed_absent: list[str] = field(default_factory=list)
    unconfirmed_fields: list[str] = field(default_factory=list)
    conflicts: dict[str, list[str]] = field(default_factory=dict)
    duplicate_of: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """序列化成 JSON 可保存的字典。"""
        return {
            "quest_id": self.quest_id,
            "quest_name": self.quest_name,
            "guide_article_id": self.guide_article_id,
            "min_level": self.min_level,
            "objective": self.objective,
            "start_npc": self.start_npc,
            "target_npc": self.target_npc,
            "target_map": self.target_map,
            "required_items": self.required_items,
            "reward_text": self.reward_text,
            "reward_items": self.reward_items,
            "completion_condition": self.completion_condition,
            "prerequisite_name": self.prerequisite_name,
            "next_quest_name": self.next_quest_name,
            "description": self.description,
            "source": self.source,
            "confidence": self.confidence,
            "confirmed_absent": list(self.confirmed_absent),
            "unconfirmed_fields": list(self.unconfirmed_fields),
            "conflicts": {key: list(value) for key, value in self.conflicts.items()},
            "duplicate_of": self.duplicate_of,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QuestRecord:
        """从字典恢复任务。缺少的列表按空集合处理，缺少的值保持为空。"""
        return cls(
            quest_id=str(data["quest_id"]),
            quest_name=str(data["quest_name"]),
            source=str(data["source"]),
            guide_article_id=data.get("guide_article_id"),
            min_level=data.get("min_level"),
            objective=data.get("objective"),
            start_npc=data.get("start_npc"),
            target_npc=data.get("target_npc"),
            target_map=data.get("target_map"),
            required_items=data.get("required_items"),
            reward_text=data.get("reward_text"),
            reward_items=data.get("reward_items"),
            completion_condition=data.get("completion_condition"),
            prerequisite_name=data.get("prerequisite_name"),
            next_quest_name=data.get("next_quest_name"),
            description=data.get("description"),
            confidence=data.get("confidence"),
            confirmed_absent=list(data.get("confirmed_absent") or []),
            unconfirmed_fields=list(data.get("unconfirmed_fields") or []),
            conflicts={key: list(value) for key, value in (data.get("conflicts") or {}).items()},
            duplicate_of=data.get("duplicate_of"),
        )


@dataclass(slots=True)
class PageParseResult:
    """一篇指南页面的解析结果。无法确认是单条任务时不生成记录。"""

    article_id: int
    url: str
    quest: QuestRecord | None
    excluded_reason: str | None = None


@dataclass(slots=True)
class QuestOrderReport:
    """任务先后关系的整理结果。理论顺序只基于指南写明且不冲突的链接。"""

    ordered_ids: list[str]
    chains: list[list[str]]
    unresolved_references: list[str]
    conflicts: list[str]
    missing_data_notes: list[str]
    cycle_ids: list[str]


class QuestCatalog:
    """一组带有来源的任务，以及它们之间能够确认的顺序。"""

    def __init__(self, quests: list[QuestRecord], dataset_source: str) -> None:
        self.quests = list(quests)
        self.dataset_source = dataset_source
        self.excluded_pages: list[dict[str, str]] = []
        self._mark_duplicates()

    def get(self, quest_id: str) -> QuestRecord | None:
        """按任务标识查找。找不到时返回 None。"""
        for quest in self.quests:
            if quest.quest_id == quest_id:
                return quest
        return None

    def canonical_quests(self) -> list[QuestRecord]:
        """返回参与顺序计算的任务。重复发布的页面不重复进入顺序。"""
        return [quest for quest in self.quests if quest.duplicate_of is None]

    def execution_report(self) -> QuestOrderReport:
        """根据前后任务名称生成顺序。

        只有两边写法一致，或只有一边写了而另一边没有相反说法时，才建立链接。
        两边写法冲突时只记录冲突，不猜测哪一边才是实际顺序。
        """
        canonical = self.canonical_quests()
        by_name: dict[str, list[QuestRecord]] = defaultdict(list)
        for quest in canonical:
            by_name[quest.quest_name].append(quest)

        def resolve_name(name: str) -> tuple[QuestRecord | None, str]:
            matches = by_name.get(name, [])
            if len(matches) == 1:
                return matches[0], "unique"
            if not matches:
                return None, "missing"
            return None, "ambiguous"

        conflicts: list[str] = []
        unresolved: list[str] = []
        agreed: set[tuple[str, str]] = set()
        one_sided: set[tuple[str, str]] = set()

        for quest in canonical:
            self._consider_link(
                quest,
                quest.next_quest_name,
                "next_quest_name",
                forward=True,
                resolve_name=resolve_name,
                conflicts=conflicts,
                unresolved=unresolved,
                agreed=agreed,
                one_sided=one_sided,
            )
            self._consider_link(
                quest,
                quest.prerequisite_name,
                "prerequisite_name",
                forward=False,
                resolve_name=resolve_name,
                conflicts=conflicts,
                unresolved=unresolved,
                agreed=agreed,
                one_sided=one_sided,
            )

        edges = agreed | one_sided
        ordered_ids, cycle_ids = _topological_order(canonical, edges)
        chains = _linear_chains(canonical, edges)
        notes = [
            "目标地图、所需物品和单独的完成条件只在指南写明时填写；当前官方故事任务页没有这些独立字段。",
            "任务描述里出现的坐标只保留在描述原文中，不会写入地图坐标。",
        ]
        if cycle_ids:
            notes.append("部分任务的前后关系形成环，这些任务的顺序未确认。")
        return QuestOrderReport(
            ordered_ids=ordered_ids,
            chains=chains,
            unresolved_references=_unique(unresolved),
            conflicts=_unique(conflicts),
            missing_data_notes=notes,
            cycle_ids=cycle_ids,
        )

    def ordered_names(self) -> list[str]:
        """按已确认的依赖关系返回任务名称。"""
        report = self.execution_report()
        names: list[str] = []
        for quest_id in report.ordered_ids:
            quest = self.get(quest_id)
            if quest is not None:
                names.append(quest.quest_name)
        return names

    def apply_manual(
        self,
        quests: list[dict[str, Any]],
        source: str,
        confidence: float | None = None,
    ) -> None:
        """用手写记录补充或更新任务。

        `source` 必须说明这条补充来自哪里。未出现在记录中的字段保持原状，
        不会被自动补成已确认信息。
        """
        manual_source = source.strip()
        if not manual_source:
            raise ValueError("手动补充必须填写来源")
        editable = {
            "quest_name",
            "min_level",
            "objective",
            "start_npc",
            "target_npc",
            "target_map",
            "required_items",
            "reward_text",
            "reward_items",
            "completion_condition",
            "prerequisite_name",
            "next_quest_name",
            "description",
        }
        for item in quests:
            quest_id = str(item["quest_id"]).strip()
            if not quest_id:
                raise ValueError("手动任务缺少 quest_id")
            existing = self.get(quest_id)
            if existing is None:
                quest_name = str(item.get("quest_name") or "").strip()
                if not quest_name:
                    raise ValueError("新增任务必须填写任务名称")
                existing = QuestRecord(
                    quest_id=quest_id,
                    quest_name=quest_name,
                    source=manual_source,
                    confidence=confidence,
                    unconfirmed_fields=[
                        "min_level",
                        "objective",
                        "start_npc",
                        "target_npc",
                        * _ALWAYS_UNCONFIRMED,
                        "reward_text",
                        "reward_items",
                        "prerequisite_name",
                        "next_quest_name",
                        "description",
                    ],
                )
                self.quests.append(existing)
            else:
                existing.source = f"{existing.source} | 手动更新:{manual_source}"
                existing.confidence = confidence
            for key in editable:
                if key not in item:
                    continue
                if key == "quest_name":
                    renamed = str(item[key]).strip()
                    if renamed:
                        existing.quest_name = renamed
                    continue
                _assign_manual_field(existing, key, item[key])
        self._mark_duplicates()

    def _mark_duplicates(self) -> None:
        """官网重复发布、正文一致的页面只保留文章编号较小的一条参与顺序。"""
        for quest in self.quests:
            quest.duplicate_of = None
        groups: dict[tuple[object, ...], list[QuestRecord]] = defaultdict(list)
        for quest in self.quests:
            groups[_duplicate_signature(quest)].append(quest)
        for grouped in groups.values():
            if len(grouped) < 2:
                continue
            grouped.sort(key=lambda item: item.guide_article_id or 0)
            canonical = grouped[0]
            for duplicate in grouped[1:]:
                duplicate.duplicate_of = canonical.quest_id

    def _consider_link(
        self,
        quest: QuestRecord,
        other_name: str | None,
        field_name: str,
        *,
        forward: bool,
        resolve_name,
        conflicts: list[str],
        unresolved: list[str],
        agreed: set[tuple[str, str]],
        one_sided: set[tuple[str, str]],
    ) -> None:
        """检查一个已确认的前续或后续名称，决定能否连边。"""
        if field_name in quest.unconfirmed_fields or field_name in quest.confirmed_absent:
            return
        if not other_name:
            return
        other, status = resolve_name(other_name)
        if status == "missing":
            unresolved.append(f"{quest.quest_name} 提到了指南中不存在的任务「{other_name}」")
            return
        if status == "ambiguous":
            unresolved.append(f"{quest.quest_name} 提到的「{other_name}」对应多条内容不同的任务")
            return
        assert other is not None
        if forward:
            source_quest, target = quest, other
            opposite_name = target.prerequisite_name
            opposite_field = "prerequisite_name"
            expected = quest.quest_name
        else:
            source_quest, target = other, quest
            opposite_name = source_quest.next_quest_name
            opposite_field = "next_quest_name"
            expected = quest.quest_name
        edge = (source_quest.quest_id, target.quest_id)
        opposite_known = (
            opposite_field not in (source_quest if not forward else target).unconfirmed_fields
        )
        holder = target if forward else source_quest
        if opposite_field in holder.confirmed_absent or (
            opposite_known and opposite_name not in (None, expected)
        ):
            conflicts.append(
                f"{source_quest.quest_name} 与 {target.quest_name} 的前后写法不一致，未采用该链接"
            )
            return
        if opposite_name == expected:
            agreed.add(edge)
            one_sided.discard(edge)
        elif edge not in agreed:
            one_sided.add(edge)


class QuestAnalyzer:
    """解析官方任务页面，并读取已经导入的任务快照。"""

    def parse_html(self, page_html: str, article_id: int, url: str | None = None) -> PageParseResult:
        """解析一篇官网任务指南。

        页面里有多段不同的任务目的时，不把它收成一条已确认任务。
        """
        page_url = url or official_quest_url(article_id)
        title = _page_title(page_html)
        content = _content_text(page_html)
        fields = _collect_fields(content)
        objectives = _unique(fields["任务目的"])
        if len(objectives) != 1:
            reason = "页面没有唯一的任务目的，未导入为已确认任务"
            if len(objectives) > 1:
                reason = "同一页面包含多条任务目的，未导入为已确认的单条任务"
            return PageParseResult(article_id, page_url, None, reason)
        if not title:
            return PageParseResult(article_id, page_url, None, "页面没有任务名称")

        values: dict[str, str | None] = {}
        confirmed_absent: list[str] = []
        unconfirmed = list(_ALWAYS_UNCONFIRMED)
        conflicts: dict[str, list[str]] = {}
        for label in _LABELS:
            field_name = _FIELD_BY_LABEL[label]
            decided, state, candidates = _decide(fields[label])
            if state == "conflict":
                conflicts[label] = candidates
                unconfirmed.append(field_name)
                values[field_name] = None
            elif state == "missing":
                unconfirmed.append(field_name)
                values[field_name] = None
            elif state == "absent":
                confirmed_absent.append(field_name)
                values[field_name] = None
            else:
                values[field_name] = decided

        min_level: int | None = None
        level_text = values["min_level"]
        if level_text is not None:
            if level_text.isdigit():
                min_level = int(level_text)
            else:
                conflicts["任务等级"] = [level_text]
                unconfirmed.append("min_level")
                level_text = None
        reward_text = values["reward_text"]
        quest = QuestRecord(
            quest_id=f"guide-{article_id}",
            quest_name=title,
            source=page_url,
            guide_article_id=article_id,
            min_level=min_level,
            objective=values["objective"],
            start_npc=values["start_npc"],
            target_npc=values["target_npc"],
            target_map=None,
            required_items=None,
            reward_text=reward_text,
            reward_items=_reward_items(reward_text),
            completion_condition=None,
            prerequisite_name=values["prerequisite_name"],
            next_quest_name=values["next_quest_name"],
            description=values["description"],
            confidence=0.5 if conflicts else 1.0,
            confirmed_absent=_unique(confirmed_absent),
            unconfirmed_fields=_unique(unconfirmed),
            conflicts=conflicts,
        )
        return PageParseResult(article_id, page_url, quest, None)

    def load_snapshot(self, path: Path | str | None = None) -> QuestCatalog:
        """读取已经导入的官方任务快照，不访问网络。"""
        snapshot = Path(path) if path is not None else _OFFICIAL_SNAPSHOT
        payload = json.loads(snapshot.read_text(encoding="utf-8"))
        quests = [QuestRecord.from_dict(item) for item in payload["quests"]]
        catalog = QuestCatalog(quests, dataset_source=str(payload["source_site"]))
        catalog.excluded_pages = list(payload.get("excluded_pages") or [])
        return catalog


def _assign_manual_field(quest: QuestRecord, key: str, value: Any) -> None:
    """把用户明确给出的字段写回记录，并调整确认状态。"""
    if key in {"required_items", "reward_items"} and value is not None:
        value = [str(item) for item in value]
    elif isinstance(value, str):
        value = value.strip()
        if value in _NONE_TOKENS:
            value = None
            if key in quest.unconfirmed_fields:
                quest.unconfirmed_fields.remove(key)
            if key not in quest.confirmed_absent:
                quest.confirmed_absent.append(key)
            setattr(quest, key, None)
            return
    setattr(quest, key, value)
    if key in quest.unconfirmed_fields and value is not None:
        quest.unconfirmed_fields.remove(key)
    if key in quest.confirmed_absent and value is not None:
        quest.confirmed_absent.remove(key)
    if value is None and key not in quest.unconfirmed_fields and key not in quest.confirmed_absent:
        quest.unconfirmed_fields.append(key)


def _page_title(page_html: str) -> str:
    match = re.search(r"<title>(.*?)</title>", page_html, re.S | re.I)
    if not match:
        return ""
    title = html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    if title.endswith(_TITLE_SUFFIX):
        title = title[: -len(_TITLE_SUFFIX)].strip()
    return title


def _content_text(page_html: str) -> str:
    match = re.search(r'class="m-content"(.*?)</div>', page_html, re.S)
    if not match:
        return ""
    text = html.unescape(match.group(1))
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return text


def _collect_fields(text: str) -> dict[str, list[str]]:
    found = {label: [] for label in _LABELS}
    matches = list(_LABEL_RE.finditer(text))
    for index, item in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = re.sub(r"\s+", " ", text[item.end() : end]).strip(" |")
        if value:
            found[item.group(1)].append(value)
    return found


def _decide(values: list[str]) -> tuple[str | None, str, list[str]]:
    unique = _unique(values)
    if not unique:
        return None, "missing", []
    if len(unique) > 1:
        return None, "conflict", unique
    if unique[0] in _NONE_TOKENS:
        return None, "absent", []
    return unique[0], "value", []


def _reward_items(reward_text: str | None) -> list[str] | None:
    """只提取奖励原文中明确写出的“物品”一项，不把它当作所需物品。"""
    if not reward_text:
        return None
    match = re.search(r"物品[:：]\s*(\S+)", reward_text)
    if not match:
        return None
    token = match.group(1).strip()
    if token in _NONE_TOKENS:
        return []
    return [part for part in re.split(r"[/、，,]", token) if part and part not in _NONE_TOKENS]


def _duplicate_signature(quest: QuestRecord) -> tuple[object, ...]:
    return (
        quest.quest_name,
        quest.objective,
        quest.prerequisite_name,
        quest.next_quest_name,
        quest.min_level,
        quest.start_npc,
        quest.target_npc,
        quest.description,
        quest.reward_text,
    )


def _topological_order(
    quests: list[QuestRecord],
    edges: set[tuple[str, str]],
) -> tuple[list[str], list[str]]:
    node_ids = [quest.quest_id for quest in quests]
    rank = {quest.quest_id: quest.guide_article_id or 0 for quest in quests}
    outgoing: dict[str, list[str]] = {quest_id: [] for quest_id in node_ids}
    indegree = {quest_id: 0 for quest_id in node_ids}
    for source_id, target_id in edges:
        if source_id not in indegree or target_id not in indegree:
            continue
        outgoing[source_id].append(target_id)
        indegree[target_id] += 1
    ready = deque(sorted((quest_id for quest_id, degree in indegree.items() if degree == 0), key=rank.get))
    ordered: list[str] = []
    while ready:
        current = ready.popleft()
        ordered.append(current)
        for target_id in sorted(outgoing[current], key=rank.get):
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                ready.append(target_id)
    cycle = [quest_id for quest_id in node_ids if quest_id not in ordered]
    cycle.sort(key=rank.get)
    return ordered + cycle, cycle


def _linear_chains(quests: list[QuestRecord], edges: set[tuple[str, str]]) -> list[list[str]]:
    outgoing: dict[str, list[str]] = defaultdict(list)
    incoming: dict[str, list[str]] = defaultdict(list)
    nodes = {quest.quest_id for quest in quests}
    for source_id, target_id in edges:
        if source_id in nodes and target_id in nodes:
            outgoing[source_id].append(target_id)
            incoming[target_id].append(source_id)
    roots = [quest.quest_id for quest in quests if not incoming[quest.quest_id]]
    roots.sort(key=lambda quest_id: next(item.guide_article_id or 0 for item in quests if item.quest_id == quest_id))
    chains: list[list[str]] = []
    for root in roots:
        chain = [root]
        while len(outgoing[chain[-1]]) == 1:
            nxt = outgoing[chain[-1]][0]
            if len(incoming[nxt]) != 1 or nxt in chain:
                break
            chain.append(nxt)
        if len(chain) > 1:
            chains.append(chain)
    return chains


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
