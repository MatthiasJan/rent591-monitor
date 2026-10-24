import json
from pathlib import Path
from shapely.geometry import mapping, shape

# 1. 讀取 raw_commute.json
with open("raw_commute.json", "r", encoding="utf-8") as f:
    raw_data = json.load(f)

# 2. 分別取出三個地點的多邊形幾何
geoms = []
for collection in raw_data:
    features = collection.get("features", [])
    if features:
        # 單一地點可能包含多個子多邊形 (MultiPolygon)，先確保為有效幾何
        geom = shape(features[0]["geometry"])
        geoms.append(geom)

if len(geoms) < 2:
    raise ValueError(f"需要至少 2 個地點的多邊形才能求交集，目前只有 {len(geoms)} 個。")

# 3. 逐一計算交集 (A ∩ B ∩ C)
intersection_geom = geoms[0]
for g in geoms[1:]:
    intersection_geom = intersection_geom.intersection(g)

# 4. 檢查是否有重疊區域
if intersection_geom.is_empty:
    print("⚠️ 警告：這三個地點在設定的通勤時間內「完全沒有交集」！請回 CommuteTimeMap 放寬通勤時間上限。")
else:
    # 5. 輸出為交集 GeoJSON
    output_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "name": "commute_intersection_zone",
                    "description": "全員通勤時間皆可到達之共同交集區域",
                },
                "geometry": mapping(intersection_geom),
            }
        ],
    }

    out_dir = Path("config")
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / "commute_union.geojson"  # 檔名維持讓過濾模組讀取

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output_geojson, f, ensure_ascii=False)

    print(f"✅ 成功產出「交集」等時圈檔案：{out_file}")
