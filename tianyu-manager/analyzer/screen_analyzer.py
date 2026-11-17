"""按用户设定的区域裁剪游戏截图。

未配置文字识别时，只返回裁剪结果，不猜测地图名、血量或 NPC 名称。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np


TextReader = Callable[[np.ndarray], tuple[str | None, float | None]]


@dataclass(slots=True)
class ScreenRegion:
    """截图上的一个矩形区域，单位是像素，由用户自行校准。"""

    name: str
    x: int
    y: int
    width: int
    height: int


@dataclass(slots=True)
class RegionObservation:
    """一个区域的观察结果。识别不到文字时 text 为空。"""

    name: str
    text: str | None
    confidence: float | None
    source: str
    note: str


class ScreenAnalyzer:
    """裁剪截图区域。默认区域表是空的，不预置游戏界面坐标。"""

    def analyze(
        self,
        image: np.ndarray | str | Path,
        regions: list[ScreenRegion],
        *,
        source: str,
        reader: TextReader | None = None,
    ) -> list[RegionObservation]:
        """分析一张截图中的指定区域。

        参数:
            image: OpenCV 图像，或截图文件路径。
            regions: 用户校准后的区域。宽或高小于等于 0 视为尚未设置。
            source: 这张截图或这次观察的来源。
            reader: 可选的文字识别函数。不提供时不返回文字。

        异常:
            ValueError: 来源为空，或图像无法读取。
        """
        if not source or not source.strip():
            raise ValueError("画面分析必须填写来源")
        pixels = _load_image(image)
        height, width = pixels.shape[:2]
        observations: list[RegionObservation] = []
        for region in regions:
            observations.append(
                self._observe_region(pixels, region, width, height, source.strip(), reader)
            )
        return observations

    def _observe_region(
        self,
        pixels: np.ndarray,
        region: ScreenRegion,
        image_width: int,
        image_height: int,
        source: str,
        reader: TextReader | None,
    ) -> RegionObservation:
        """裁剪一个区域。越界或未设置时不返回猜测文字。"""
        if region.width <= 0 or region.height <= 0:
            return RegionObservation(region.name, None, None, source, "区域尚未设置")
        right = region.x + region.width
        bottom = region.y + region.height
        if region.x < 0 or region.y < 0 or right > image_width or bottom > image_height:
            return RegionObservation(region.name, None, None, source, "区域超出截图范围")
        crop = pixels[region.y : bottom, region.x : right]
        if reader is None:
            return RegionObservation(region.name, None, None, source, "未进行文字识别，只裁剪了区域")
        text, confidence = reader(crop)
        cleaned = text.strip() if isinstance(text, str) else None
        if not cleaned:
            return RegionObservation(region.name, None, None, source, "文字识别没有得到内容")
        return RegionObservation(region.name, cleaned, confidence, source, "文字识别结果")


def _load_image(image: np.ndarray | str | Path) -> np.ndarray:
    if isinstance(image, np.ndarray):
        if image.size == 0:
            raise ValueError("截图为空")
        return image
    loaded = cv2.imread(str(image), cv2.IMREAD_COLOR)
    if loaded is None:
        raise ValueError(f"无法读取截图: {image}")
    return loaded
