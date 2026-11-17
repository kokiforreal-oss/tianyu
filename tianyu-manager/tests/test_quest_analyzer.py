"""任务指南解析测试。快照来自官网页面，测试本身不再访问网络。"""

from __future__ import annotations

from analyzer.quest_analyzer import QuestAnalyzer, QuestCatalog, QuestRecord


def _page(title: str, body: str) -> str:
    return f"<title>{title}-天羽传奇官网</title><div class=\"m-content\">{body}</div>"


def test_parse_official_fields_without_inventing_map_or_items() -> None:
    """抄录指南字段，描述中的坐标不写入地图，奖励物品不算所需物品。"""
    html = _page(
        "新来乍到2",
        "任务目的：拜访鲤鱼村武器店老板"
        "任务等级：1"
        "任务奖励：经验:50物品:青龙衣/青龙裙"
        "起始NPC：鲤鱼村村长结束NPC：鲤鱼村武器店老板"
        "任务前续：新来乍到1任务后续：新来乍到3"
        "任务描述：他就在村子的（197，174）。",
    )
    quest = QuestAnalyzer().parse_html(html, 74).quest
    assert quest is not None
    assert quest.quest_name == "新来乍到2"
    assert quest.quest_id == "guide-74"
    assert quest.min_level == 1
    assert quest.start_npc == "鲤鱼村村长"
    assert quest.target_npc == "鲤鱼村武器店老板"
    assert quest.prerequisite_name == "新来乍到1"
    assert quest.next_quest_name == "新来乍到3"
    assert quest.reward_items == ["青龙衣", "青龙裙"]
    assert quest.required_items is None
    assert quest.target_map is None
    assert quest.completion_condition is None
    assert "197" in (quest.description or "")
    assert "target_map" in quest.unconfirmed_fields
    assert quest.confidence == 1.0


def test_explicit_none_is_not_treated_as_unknown() -> None:
    """指南写明“无”时记为确认缺失，而不是未知。"""
    html = _page(
        "新来乍到1",
        "任务目的：拜访鲤鱼村村长任务等级：0任务奖励：经验:20物品:无"
        "起始NPC：无结束NPC：鲤鱼村村长任务前续：无任务后续：新来乍到2"
        "任务描述：去拜访村长。",
    )
    quest = QuestAnalyzer().parse_html(html, 73).quest
    assert quest is not None
    assert quest.start_npc is None
    assert quest.prerequisite_name is None
    assert "start_npc" in quest.confirmed_absent
    assert "prerequisite_name" in quest.confirmed_absent
    assert quest.reward_items == []


def test_conflicting_values_stay_unconfirmed() -> None:
    """同一字段有两个不同原文时，不挑选其中一个。"""
    html = _page(
        "沼泽迷魂5",
        "任务目的：把羽毛交给王召"
        "任务等级：80 任务等级：经验：160000"
        "起始NPC：郭离 起始NPC：王召"
        "任务前续：沼泽迷魂4 任务前续：记忆之迷1"
        "任务描述：转达歉意。",
    )
    quest = QuestAnalyzer().parse_html(html, 168).quest
    assert quest is not None
    assert quest.min_level is None
    assert quest.start_npc is None
    assert quest.prerequisite_name is None
    assert quest.conflicts["任务前续"] == ["沼泽迷魂4", "记忆之迷1"]
    assert quest.confidence == 0.5


def test_multiple_objectives_are_excluded() -> None:
    """一页里有多条任务目的时，不合并成一条已确认任务。"""
    html = _page(
        "部落任务",
        "1.紧急拯救任务目的：拯救信使。任务描述：送药。"
        "2.护送访客任务目的：护送访客。任务描述：送到 NPC。",
    )
    parsed = QuestAnalyzer().parse_html(html, 265)
    assert parsed.quest is None
    assert parsed.excluded_reason is not None
    assert "多条" in parsed.excluded_reason


def test_execution_order_skips_contradictory_links() -> None:
    """前后任务互相矛盾时不连边，一致的链接仍按顺序排列。"""
    records = [
        _quest("a", "装备计划2", next_name="装备计划3"),
        _quest("b", "装备计划3", previous="装备计划2", next_name="含罪蒙冤"),
        _quest("c", "军备采购", previous="装备计划3", next_name="含罪蒙冤"),
        _quest("d", "含罪蒙冤", previous="军备采购", next_name="军购黑幕"),
    ]
    catalog = QuestCatalog(records, dataset_source="测试")
    report = catalog.execution_report()
    names = catalog.ordered_names()
    assert names.index("装备计划2") < names.index("装备计划3")
    assert names.index("军备采购") < names.index("含罪蒙冤")
    assert any("装备计划3" in item and "含罪蒙冤" in item for item in report.conflicts)
    chain_names = [[catalog.get(item).quest_name for item in chain] for chain in report.chains]
    assert ["装备计划3", "军备采购", "含罪蒙冤"] not in chain_names


def test_official_snapshot_orders_opening_chain_and_keeps_gaps() -> None:
    """已导入的官网快照能排出新来乍到顺序，并保留缺失与冲突。"""
    catalog = QuestAnalyzer().load_snapshot()
    names = catalog.ordered_names()
    assert names.index("新来乍到1") < names.index("新来乍到2") < names.index("新来乍到10")
    assert names.index("新来乍到10") < names.index("城主的委托")
    opening = catalog.get("guide-74")
    assert opening is not None
    assert opening.target_map is None
    assert opening.required_items is None
    assert "197" in (opening.description or "")
    report = catalog.execution_report()
    assert any("乌金秘道2" in item for item in report.unresolved_references)
    assert any("装备计划3" in item for item in report.conflicts)
    assert all(quest.guide_article_id != 265 for quest in catalog.quests)
    assert any(page["article_id"] == 265 for page in catalog.excluded_pages)
    duplicate = catalog.get("guide-184")
    assert duplicate is not None
    assert duplicate.duplicate_of == "guide-183"


def test_manual_update_adds_map_only_when_user_provides_it() -> None:
    """手动补充可以填写指南里没有的地图，并保留补充来源。"""
    catalog = QuestAnalyzer().load_snapshot()
    catalog.apply_manual(
        [
            {
                "quest_id": "guide-74",
                "target_map": "鲤鱼村",
            },
            {
                "quest_id": "manual-note",
                "quest_name": "补充记录",
                "objective": "玩家自行记录的目标",
            },
        ],
        source="玩家对照任务栏补录",
        confidence=0.4,
    )
    updated = catalog.get("guide-74")
    assert updated is not None
    assert updated.target_map == "鲤鱼村"
    assert "target_map" not in updated.unconfirmed_fields
    assert "玩家对照任务栏补录" in updated.source
    assert updated.confidence == 0.4
    added = catalog.get("manual-note")
    assert added is not None
    assert added.target_map is None
    assert "target_map" in added.unconfirmed_fields


def _quest(
    quest_id: str,
    name: str,
    *,
    previous: str | None = None,
    next_name: str | None = None,
) -> QuestRecord:
    unconfirmed = ["target_map", "required_items", "completion_condition"]
    confirmed_absent: list[str] = []
    if previous is None:
        confirmed_absent.append("prerequisite_name")
    if next_name is None:
        confirmed_absent.append("next_quest_name")
    return QuestRecord(
        quest_id=quest_id,
        quest_name=name,
        source="测试",
        guide_article_id=ord(quest_id[-1]),
        prerequisite_name=previous,
        next_quest_name=next_name,
        confirmed_absent=confirmed_absent,
        unconfirmed_fields=unconfirmed,
        confidence=1.0,
    )
