"""除錯專用：抓取特定物件內頁 HTML，檢視座標與位置資訊實際存放在何處。"""
import re
import httpx

TARGET_ID = "22228503"
URL = f"https://rent.591.com.tw/{TARGET_ID}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
}

def debug_fetch():
    print(f"正在發送請求至: {URL}")
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=15.0) as client:
        resp = client.get(URL)
        print(f"HTTP 狀態碼: {resp.status_code}")
        
        if resp.status_code != 200:
            print("⚠️ 請求失敗或遭遇阻擋")
            return

        html = resp.text
        print(f"成功取得 HTML，總長度: {len(html)} 字元\n")

        # 1. 檢查目前正則比對結果
        lat_m = re.search(r'lat["\']?\s*:\s*["\']?([2-3]\d\.\d+)["\']?', html)
        lng_m = re.search(r'lng["\']?\s*:\s*["\']?(12[0-2]\.\d+)["\']?', html)
        print(f"[目前正則比對結果]")
        print(f"  lat: {lat_m.group(0) if lat_m else '未匹配到'}")
        print(f"  lng: {lng_m.group(0) if lng_m else '未匹配到'}\n")

        # 2. 搜尋關鍵字周圍上下文 (找出實際欄位名稱)
        keywords = ["positionRound", "lat", "lng", "location", "address"]
        print("[關鍵字上下文搜尋]")
        for kw in keywords:
            matches = [m.start() for m in re.finditer(re.escape(kw), html, re.IGNORECASE)]
            print(f"--- 關鍵字 '{kw}' 共出現 {len(matches)} 次 ---")
            for idx, pos in enumerate(matches[:3]):  # 只印前 3 個避免洗版
                start = max(0, pos - 80)
                end = min(len(html), pos + 120)
                snippet = html[start:end].replace("\n", " ").replace("\r", " ")
                print(f"  [{idx + 1}] ...{snippet}...")

if __name__ == "__main__":
    debug_fetch()
