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


def _extract_coords_from_nuxt(html: str) -> tuple[float | None, float | None]:
    """從 Nuxt 序列化函式中提取 positionRound 的 (lat, lng)。"""
    # 1. 找出 positionRound 中的變數名稱，例如 lat:ch,lng:ci
    pos_match = re.search(r'positionRound:\{[^}]*?lat:([a-zA-Z0-9_$]+),lng:([a-zA-Z0-9_$]+)', html)
    
    # 2. 找出函式結尾傳入的真實引數清單 ( ... }(arg1, arg2, ...))
    args_match = re.search(r'\}\((.*?)\)\)\s*(?:</script>|$)', html, re.DOTALL)

    if pos_match and args_match:
        lat_var = pos_match.group(1)
        lng_var = pos_match.group(2)

        # 3. 找出宣告的參數名稱清單 window.__NUXT__=(function(a,b,c,...){
        params_match = re.search(r'window\.__NUXT__=\(function\(([^)]+)\)', html)
        if params_match:
            params = [p.strip() for p in params_match.group(1).split(",")]
            # 簡易拆解尾端引數（注意處理字串內含逗號）
            # 用正則切分最外層引數
            args_str = args_match.group(1)
            raw_args = [a.strip().strip('"\'') for a in re.split(r',(?=(?:[^\'"]*[\'"][^\'"]*[\'"])*[^\'"]*$)', args_str)]

            if lat_var in params and lng_var in params:
                lat_idx = params.index(lat_var)
                lng_idx = params.index(lng_var)

                if lat_idx < len(raw_args) and lng_idx < len(raw_args):
                    try:
                        lat = float(raw_args[lat_idx])
                        lng = float(raw_args[lng_idx])
                        if 24.5 <= lat <= 25.5 and 121.0 <= lng <= 122.0:
                            return lat, lng
                    except ValueError:
                        pass

    # 4. 備援方案：若 Nuxt 混淆變數比對失敗，直接在 HTML 搜尋台北經緯度數值對
    # 尋找 "25.xxxx" 和 "121.xxxx" 彼此相距在 30 字元以內的組合
    coord_pair = re.search(
        r'["\']?(25\.\d{4,8})["\']?\s*,\s*["\']?(121\.\d{4,8})["\']?|["\']?(121\.\d{4,8})["\']?\s*,\s*["\']?(25\.\d{4,8})["\']?',
        html
    )
    if coord_pair:
        g = coord_pair.groups()
        if g[0] and g[1]:
            return float(g[0]), float(g[1])
        elif g[2] and g[3]:
            return float(g[3]), float(g[2])

    return None, None


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

        return _extract_coords_from_nuxt(text)

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            raise DetailBlockedError(f"HTTP 403 on {url}") from exc
        return None, None
    except Exception as exc:
        if isinstance(exc, DetailBlockedError):
            raise
        log.warning("抓取物件 %s 內頁異常：%s", listing_id, exc)
        return None, None
