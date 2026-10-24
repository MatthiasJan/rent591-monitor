"""等時圈判定模組：讀取 commute_union.geojson，判定座標是否在通勤範圍內。"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from shapely.geometry import Point, shape

log = logging.getLogger(__name__)

GEOJSON_PATH = Path(__file__).resolve().parent / "config" / "commute_union.geojson"

# 白名單區域：必定在通勤核心範圍內，直接豁免
EXEMPT_DISTRICTS = {"中山區", "大同區", "松山區"}


class CommuteFilter:
    def __init__(self, geojson_path: Path | str = GEOJSON_PATH):
        self.boundary = None
        p = Path(geojson_path)
        if not p.exists():
            log.warning("找不到等時圈檔案 %s，將略過幾何範圍判定（全部放行）。", p)
            return

        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)

            features = data.get("features", [])
            if features:
                self.boundary = shape(features[0]["geometry"])
                log.info("成功載入等時圈幾何形狀，通勤過濾已啟用。")
            else:
                log.warning("GeoJSON 缺少 features，略過判定。")
        except Exception as exc:
            log.error("載入 GeoJSON 失敗：%s", exc)

    def is_acceptable(self, district: str | None, lat: float | None, lng: float | None) -> bool:
        """判定房源是否符合通勤需求。
        
        1. 若屬於中山、大同、松山區 -> 無條件放行 True
        2. 若無座標或未載入邊界 -> 預設放行 True（防誤殺）
        3. 其餘區域 -> 幾何判定 Point(lng, lat) 是否在多邊形內
        """
        # 1. 白名單行政區檢查
        if district in EXEMPT_DISTRICTS:
            return True

        # 2. 邊界未啟動或缺乏座標
        if self.boundary is None or lat is None or lng is None:
            return True

        # 3. 幾何判定（注意：GeoJSON 標準格式是 x=經度, y=緯度）
        pt = Point(lng, lat)
        return self.boundary.contains(pt)
