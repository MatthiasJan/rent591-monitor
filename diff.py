"""快照比對：算出新增 / 降價 / 下架與歷史留存。

純函式、無 I/O（快照讀寫在 storage.py），方便單元測試。

狀態模型（state）以 listing_id 為 key 累積：
    {
      "generated_at": "...",
      "listings": {
        "<id>": {
            ...列表欄位..., "lat": ..., "lng": ...,
            "price_history": [{date, price}],
            "missing_count": 0, "status": "active"|"missing"|"removed",
            "first_seen": "...", "last_seen": "...", "removed_at": "..."
        }
      }
    }

比對規則：
- 新 ID 或 已下架重新上架 → 🆕 新增
- 同 ID 且 total_monthly 下降 → 💰 降價（寫入 price_history）
- 舊 ID 消失 → missing_count +1；達門檻（預設 2 輪）才判 ❌ 下架並記錄 removed_at
  （已下架物件永久保留於 listings 中，供網頁歷史分區檢視與估價參考）
- 比價一律用 total_monthly（含額外費用），而非單看租金。
"""
from __future__ import annotations


def _last_price(rec: dict, price_key: str = "total_monthly"):
    hist = rec.get("price_history") or []
    if hist:
        return hist[-1]["price"]
    return rec.get(price_key)


def diff_snapshots(
    previous: dict | None,
    current_listings: list[dict],
    today: str,
    missing_rounds_before_removed: int = 2,
    covered_districts: set | None = None,
    price_key: str = "total_monthly",
) -> tuple[dict, dict]:
    """比對前次狀態與本輪抓取結果。

    回傳 (new_state, report)。report 內每筆保留完整物件 dict，方便通知分組。
    today 為本輪日期字串（YYYY-MM-DD），供 price_history 與 removed_at 記錄。

    covered_districts：這輪「有成功抓到」的行政區集合；None 代表全部涵蓋。
    消失的物件若其所在區這輪沒抓到（被擋），則原狀保留、不算 missing、不會被判下架。
    """
    prev_listings: dict[str, dict] = dict((previous or {}).get("listings", {}))
    current_by_id = {c["listing_id"]: c for c in current_listings}

    new_state_listings: dict[str, dict] = {}
    report = {"new": [], "price_drop": [], "removed": []}

    # 1) 本輪出現的物件：判斷新增 / 重新上架 / 降價 / 續存
    for lid, cur in current_by_id.items():
        cur_total = cur.get(price_key)

        # 情況 A：完全全新的物件
        if lid not in prev_listings:
            rec = {
                **cur,
                "price_history": (
                    [{"date": today, "price": cur_total}] if cur_total is not None else []
                ),
                "missing_count": 0,
                "status": "active",
                "first_seen": cur.get("first_seen", today),
                "last_seen": today,
            }
            new_state_listings[lid] = rec
            report["new"].append(rec)
            continue

        # 情況 B：舊物件再次出現（包含原本 active / missing / removed）
        prev = prev_listings[lid]
        prev_status = prev.get("status", "active")
        prev_price = _last_price(prev, price_key)
        history = list(prev.get("price_history") or [])

        # 合併舊資料與最新抓到的資料（**prev 放在前面，確保舊有 lat, lng, watched 等不被覆蓋）
        rec = {
            **prev,
            **cur,
            "price_history": history,
            "missing_count": 0,
            "status": "active",
            "first_seen": prev.get("first_seen", cur.get("first_seen", today)),
            "last_seen": today,
        }
        # 重新上架者移除原本的下架時間標籤
        rec.pop("removed_at", None)

        # 若先前已被標記為 removed，重新出現時視為「重新上架」，加入 new 報告
        if prev_status == "removed":
            if cur_total is not None and not history:
                history.append({"date": today, "price": cur_total})
            report["new"].append(rec)

        # 價格變動判定：寫入 price_history；價格下降則加入降價報告
        elif cur_total is not None and cur_total != prev_price:
            history.append({"date": today, "price": cur_total})
            if prev_price is not None and cur_total < prev_price:
                drop = prev_price - cur_total
                pct = round(drop / prev_price * 100, 1) if prev_price else 0.0
                report["price_drop"].append({
                    **rec,
                    "old_price": prev_price,
                    "new_price": cur_total,
                    "drop": drop,
                    "drop_pct": pct,
                })

        new_state_listings[lid] = rec

    # 2) 本輪未抓到的物件：累積 missing，達門檻轉為 removed 並下記下架日期
    for lid, prev in prev_listings.items():
        if lid in current_by_id:
            continue

        # 若此物件所在行政區這輪沒抓到（被擋）→ 原狀保留，不算 missing
        if covered_districts is not None and prev.get("district") not in covered_districts:
            new_state_listings[lid] = {**prev}
            continue

        prev_status = prev.get("status", "active")
        
        # 已經是已下架狀態的物件，直接完整留存在快照中（不重複算 missing，也不重複通報）
        if prev_status == "removed":
            new_state_listings[lid] = {**prev}
            continue

        missing = prev.get("missing_count", 0) + 1
        rec = {**prev, "missing_count": missing}

        # 達到下架門檻
        if missing >= missing_rounds_before_removed:
            rec["status"] = "removed"
            rec["removed_at"] = today  # 記錄下架日期 (YYYY-MM-DD)
            # 僅在「剛跨過下架門檻」的那一輪列入推播報告
            if prev_status != "removed":
                report["removed"].append(rec)
        else:
            rec["status"] = "missing"

        new_state_listings[lid] = rec

    new_state = {"generated_at": today, "listings": new_state_listings}
    return new_state, report
