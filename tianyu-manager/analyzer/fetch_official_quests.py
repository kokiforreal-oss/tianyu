"""重新下载天羽传奇官网资料站中的故事任务页，并覆盖本地快照。

只保存页面上的原文。下载失败时不改写已有快照。
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from analyzer.quest_analyzer import official_quest_url, QuestAnalyzer

_SNAPSHOT = Path(__file__).resolve().parent / "data" / "tycq_official_story_quests.json"
_ARTICLE_IDS = list(range(73, 211)) + [265]


def _download(article_id: int) -> tuple[int, str, str | None, str | None]:
    url = official_quest_url(article_id)
    request = Request(url, headers={"User-Agent": "TianyuManager/1.1"})
    try:
        with urlopen(request, timeout=20) as response:
            page = response.read().decode("utf-8")
    except HTTPError as exc:
        return article_id, url, None, f"HTTP {exc.code}"
    return article_id, url, page, None


def build_snapshot() -> dict[str, object]:
    """下载并解析官方任务页。404 的文章编号会被跳过。"""
    analyzer = QuestAnalyzer()
    quests = []
    excluded = []
    errors = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(_download, article_id) for article_id in _ARTICLE_IDS]
        downloaded = [future.result() for future in as_completed(futures)]
    for article_id, url, page, error in sorted(downloaded, key=lambda item: item[0]):
        if error == "HTTP 404":
            continue
        if error or page is None:
            errors.append({"article_id": article_id, "url": url, "error": error or "空页面"})
            continue
        parsed = analyzer.parse_html(page, article_id, url)
        if parsed.quest is None:
            excluded.append(
                {
                    "article_id": article_id,
                    "url": url,
                    "reason": parsed.excluded_reason or "未导入",
                }
            )
            continue
        quests.append(parsed.quest.to_dict())
    if errors:
        raise RuntimeError(f"官方任务页下载不完整: {errors}")
    return {
        "dataset": "天羽传奇官网剧情任务指南",
        "source_site": "http://tycq.laowaner.com/zlz/shownews.php",
        "retrieved_on": date.today().isoformat(),
        "note": (
            "字段抄录自官网页面。同一字段出现多个不同值时记入 conflicts，"
            "不选择其中一个作为已确认值。这些页面没有独立的目标地图、所需物品和完成条件字段。"
        ),
        "quests": quests,
        "excluded_pages": excluded,
    }


def main() -> None:
    """写入快照文件。"""
    payload = build_snapshot()
    _SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    _SNAPSHOT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {_SNAPSHOT}，任务 {len(payload['quests'])} 条，排除 {len(payload['excluded_pages'])} 页")


if __name__ == "__main__":
    main()
