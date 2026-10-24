import json
from pathlib import Path
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

# 1. 讀取剛存的原始資料
with open("raw_commute.json", "r", encoding="utf-8") as f:
    raw_data = json.load(f)

# 2. 收集所有多邊形
all_polygons = []
for collection in raw_data:
    for feature in collection.get("features", []):
        geom = feature.get("geometry")
        if geom:
            all_polygons.append(shape(geom))

# 3. 計算幾何聯集 (A ∪ B ∪ C)
union_geom = unary_union(all_polygons)

# 4. 組裝標準 GeoJSON FeatureCollection
output_geojson = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {
                "name": "commute_union_zone",
                "description": "三人通勤等時圈聯集"
            },
            "geometry": mapping(union_geom)
        }
    ]
}

# 5. 輸出至專案 config 目錄
out_dir = Path("config")
out_dir.mkdir(exist_ok=True)
out_file = out_dir / "commute_union.geojson"

with open(out_file, "w", encoding="utf-8") as f:
    json.dump(output_geojson, f, ensure_ascii=False)

print(f"✅ 成功產出聯集等時圈檔案：{out_file}")
