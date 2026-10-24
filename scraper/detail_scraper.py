"""內頁抓取：抓取單一物件內頁，提取經緯度座標。"""
from __future__ import annotations

import logging
import re
import httpx
import config

log = logging.getLogger(__name__)


class DetailBlockedError(Exception):
    """內頁被 591 封鎖（403、驗證碼）時拋出"""
    pass


def _extract_coords(html: str) -> tuple[float | None, float | None]:
    """從 591 HTML 提取經緯度座標。
    
    591 台北物件座標範圍特徵：
    - 緯度 lat: 24.8 ~ 25.3
    - 經度 lng: 121.3 ~ 121.7
    """
    # 匹配相鄰的台北經緯度浮點數組合
    coords = re.findall(
        r'["\']?(25\.\d{4,8})["\']?\s*,\s*["\']?(121\.\d{4,8})["\']?|["\']?(121\.\d{4,8})["\']?\s*,\s*["\']?(25\.\d{4,8})["\']?',
        html
    )
    if coords:
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

        return _extract_coords(text)

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            raise DetailBlockedError(f"HTTP 403 on {url}") from exc
        return None, None
    except Exception as exc:
        if isinstance(exc, DetailBlockedError):
            raise
        log.warning("抓取物件 %s 內頁異常：%s", listing_id, exc)
        return None, None
