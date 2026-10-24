"""等時圈判定模組：判定物件座標是否位於通勤範圍交集內，並豁免核心區域。"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from shapely.geometry import Point, shape

log = logging.getLogger(__name__)

GEOJSON_PATH = Path(__file__).resolve().parent / "config" / "commute_union.geojson"
# 核心豁免區域：位於這些區域的物件，直接判定符合
EXEMPT_DISTRICTS = {"中山區", "大同區", "松山區"}


class CommuteFilter:
    def __init__(self, geojson_path: Path | str = GEOJSON_PATH):
        self.boundary = None
        p = Path(geojson_path)
        if not p.exists():
            log.warning("找不到等時圈檔案 %s，所有物件將歸類為未篩選。", p)
            return

        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)

            features = data.get("features", [])
            if features:
                self.boundary = shape(features[0]["geometry"])
                log.info("成功載入等時圈邊界。")
        except Exception as exc:
            log.error("載入等時圈 GeoJSON 失敗：%s", exc)

    def check_item(self, item: dict) -> str:
        """判定物件通勤狀態：
        - 'pass': 符合通勤要求（或免判斷區）
        - 'out': 座標明確落在範圍外
        - 'unknown': 抓不到座標或被擋，無法判斷
        """
        district = (item.get("district") or "").strip()
        if district in EXEMPT_DISTRICTS:
            return "pass"

        lat = item.get("lat")
        lng = item.get("lng")
        if lat is None or lng is None:
            return "unknown"

        if self.boundary is None:
            return "unknown"

        # GeoJSON 規範為 (lng, lat)
        pt = Point(lng, lat)
        return "pass" if self.boundary.contains(pt) else "out"
