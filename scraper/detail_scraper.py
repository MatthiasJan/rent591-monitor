"""內頁抓取：抓取單一物件內頁，提取經緯度座標與地址。"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import httpx
import config

log = logging.getLogger(__name__)


class DetailBlockedError(Exception):
    """內頁被 591 封鎖（403、驗證碼）時拋出"""
    pass


def _extract_by_node(html: str) -> tuple[float | None, float | None]:
    """利用 Node.js 執行 __NUXT__ 函式，直接取得 positionRound 內解析後的 lat/lng。"""
    # 提取 window.__NUXT__=(function(...){...}(...));
    m = re.search(r"<script>\s*(window\.__NUXT__=\s*\(function\(.*?\)\(.*?\)\));?\s*</script>", html, re.DOTALL)
    if not m:
        return None, None

    js_code = m.group(1)
    # 用 Node.js 執行這段 JS 並輸出 positionRound 的 lat/lng
    runner = f"""
    let window = {{}};
    {js_code}
    try {{
        let d = window.__NUXT__;
        let dataObj = d.data || {{}};
        let lat = null, lng = null;
        for (let k in dataObj) {{
            let p = dataObj[k]?.data?.positionRound;
            if (p && p.lat && p.lng) {{
                lat = parseFloat(p.lat);
                lng = parseFloat(p.lng);
                break;
            }}
        }}
        console.log(JSON.stringify({{lat: lat, lng: lng}}));
    }} catch(e) {{
        console.log(JSON.stringify({{lat: null, lng: null}}));
    }}
    """
    try:
        proc = subprocess.run(
            ["node", "-e", runner],
            capture_output=True,
            text=True,
            timeout=10,
            check=True
        )
        res = json.loads(proc.stdout.strip())
        return res.get("lat"), res.get("lng")
    except Exception as exc:
        log.warning("Node 解析內頁座標失敗: %s", exc)
        return None, None


def _extract_by_regex_fallback(html: str) -> tuple[float | None, float | None]:
    """純 Python 備援方案：若無 Node.js，直接比對尾端經緯度參數。"""
    # 591 台北物件經緯度範圍特徵：24.9~25.2 與 121.4~121.7
    coords = re.findall(r'["\']?(25\.\d{4,8})["\']?\s*,\s*["\']?(121\.\d{4,8})["\']?|["\']?(121\.\d{4,8})["\']?\s*,\s*["\']?(25\.\d{4,8})["\']?', html)
    if coords:
        # 取第一組符合台北經緯度的座標
        for c in coords:
            if c[0] and c[1]:
                return float(c[0]), float(c[1])
            elif c[2] and c[3]:
                return float(c[3]), float(c[2])
    return None, None


def fetch_detail_coords(listing_id: str, client: httpx.Client) -> tuple[float | None, float | None]:
    """抓單一內頁 HTML，提取 (lat, lng)。若被 403 阻擋拋出 DetailBlockedError。"""
    url = f"https://rent.591.com.tw/{listing_id}"
    try:
        resp = client.get(url, timeout=config.REQUEST_TIMEOUT_SEC)
        if resp.status_code == 403:
            raise DetailBlockedError(f"HTTP 403 Forbidden on detail {url}")

        if resp.status_code != 200:
            log.warning("物件 %s 內頁回應異常：%s", listing_id, resp.status_code)
            return None, None

        text = resp.text
        if "驗證碼" in text or "robot" in text.lower():
            raise DetailBlockedError("內頁出現驗證碼反爬")

        # 先嘗試用 Node.js 執行原生 JS（最精準）
        lat, lng = _extract_by_node(text)
        if lat and lng:
            return lat, lng

        # 備援純正則
        return _extract_by_regex_fallback(text)

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            raise DetailBlockedError(f"HTTP 403 on {url}") from exc
        return None, None
    except Exception as exc:
        if isinstance(exc, DetailBlockedError):
            raise
        log.warning("抓取物件 %s 內頁異常：%s", listing_id, exc)
        return None, None
