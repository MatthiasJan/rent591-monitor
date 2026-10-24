import httpx
from scraper.detail_scraper import _extract_by_node, _extract_by_regex_fallback

TARGET_ID = "22228503"
URL = f"https://rent.591.com.tw/{TARGET_ID}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
}

print(f"正在抓取測試物件: {URL}")
with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=15.0) as client:
    resp = client.get(URL)
    html = resp.text

    print("\n--- 測試 Node.js 解析 ---")
    node_lat, node_lng = _extract_by_node(html)
    print(f"Node.js 結果: lat={node_lat}, lng={node_lng}")

    print("\n--- 測試 正則備援解析 ---")
    reg_lat, reg_lng = _extract_by_regex_fallback(html)
    print(f"正則結果: lat={reg_lat}, lng={reg_lng}")


from commute_filter import CommuteFilter

commute = CommuteFilter()
mock_item = {
    "listing_id": "22228503",
    "district": "士林區",
    "lat": 25.092009,
    "lng": 121.503258
}

result = commute.check_item(mock_item)
print(f"通勤判定結果: {result}")  # 'pass' 表示符合交集，'out' 表示超出通勤範圍
