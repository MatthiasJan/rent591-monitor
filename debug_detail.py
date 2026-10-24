"""除錯專用：測試內頁座標提取與等時圈判定。"""
import httpx
from commute_filter import CommuteFilter
from scraper.detail_scraper import fetch_detail_coords

TARGET_ID = "22228503"
URL = f"https://rent.591.com.tw/{TARGET_ID}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
}

print(f"正在抓取測試物件: {URL}")
with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=15.0) as client:
    lat, lng = fetch_detail_coords(TARGET_ID, client)
    print(f"\n[座標解析結果]")
    print(f"  lat: {lat}")
    print(f"  lng: {lng}")

    if lat and lng:
        commute = CommuteFilter()
        mock_item = {
            "listing_id": TARGET_ID,
            "district": "士林區",
            "lat": lat,
            "lng": lng,
        }
        status = commute.check_item(mock_item)
        print(f"\n[等時圈通勤判定]")
        print(f"  狀態: {status} （pass: 通過, out: 超出範圍, unknown: 無法判定）")
    else:
        print("\n⚠️ 座標解析失敗，無法進行等時圈比對。")
