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


def fetch_detail_coords(listing_id: str, client: httpx.Client) -> tuple[float | None, float | None]:
    """抓單一內頁 HTML，提取 (lat, lng)。
    若被 403 阻擋拋出 DetailBlockedError。
    """
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

        lat_m = re.search(r'lat["\']?\s*:\s*["\']?([2-3]\d\.\d+)["\']?', text)
        lng_m = re.search(r'lng["\']?\s*:\s*["\']?(12[0-2]\.\d+)["\']?', text)

        lat = float(lat_m.group(1)) if lat_m else None
        lng = float(lng_m.group(1)) if lng_m else None
        return lat, lng

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            raise DetailBlockedError(f"HTTP 403 on {url}") from exc
        return None, None
    except Exception as exc:
        if isinstance(exc, DetailBlockedError):
            raise
        log.warning("抓取物件 %s 內頁異常：%s", listing_id, exc)
        return None, None
