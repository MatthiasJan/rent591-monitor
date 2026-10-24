"""主流程：讀訂閱 → 逐訂閱抓取 → 比對 → 第二階段 Enrich（等時圈篩選） → 通知 → 存快照。

依類型分派：
  python main.py              # 租屋（預設）
  python main.py --type sale  # 買屋（中古屋）
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone

import httpx

import config
import notify
from commute_filter import CommuteFilter
from diff import diff_snapshots
from scraper.detail_scraper import DetailBlockedError, fetch_detail_coords
from scraper.list_scraper import scrape_subscription
from scraper.sale_scraper import scrape_sale_subscription
from storage import load_latest, load_watchlist, save_snapshot

log = logging.getLogger("main")

# 核心通勤白名單：位於這些區域的新物件，直接認定符合通勤，不抓內頁
EXEMPT_DISTRICTS = {"中山區", "大同區", "松山區"}

# 各類型的差異集中在這裡
KINDS = {
    "rent": {
        "scrape": scrape_subscription,
        "price_key": "total_monthly",
        "latest": config.LATEST_PATH,
        "snapshots": config.SNAPSHOT_DIR,
    },
    "sale": {
        "scrape": scrape_sale_subscription,
        "price_key": "total_price",
        "latest": config.SALE_LATEST_PATH,
        "snapshots": config.SALE_SNAPSHOT_DIR,
    },
}


def load_subscriptions(kind: str) -> tuple[list[dict], dict]:
    data = json.loads(config.SUBSCRIPTIONS_PATH.read_text(encoding="utf-8"))
    subs = [
        s
        for s in data.get("subscriptions", [])
        if s.get("enabled", True) and (s.get("type") or "rent") == kind
    ]
    return subs, data.get("settings", {})


def collect_current(subs, fetched_at, scrape_fn):
    """逐訂閱抓取，跨訂閱以 listing_id 去重、併入歸屬人。"""
    merged: dict[str, dict] = {}
    stats, all_covered, cover_all = [], set(), False
    for sub in subs:
        group = sub.get("group") or "我"
        rows, covered = scrape_fn(sub, fetched_at=fetched_at)
        if covered is None:
            cover_all = True
        else:
            all_covered |= covered
        added = 0
        for r in rows:
            lid = r["listing_id"]
            if lid in merged:
                if group not in merged[lid]["groups"]:
                    merged[lid]["groups"].append(group)
            else:
                r["groups"] = [group]
                merged[lid] = r
                added += 1
        stats.append(
            {
                "id": sub["id"],
                "name": sub.get("name", sub["id"]),
                "group": group,
                "fetched": len(rows),
                "unique_added": added,
            }
        )
        log.info(
            "訂閱 %s（%s）：抓到 %d 筆，新增去重 %d 筆",
            sub["id"],
            group,
            len(rows),
            added,
        )
    return list(merged.values()), stats, (None if cover_all else all_covered)


def enrich_and_filter_new_rentals(
    new_items: list[dict],
    tg_token: str | None,
    tg_chat: str | None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """針對新增租屋物件抓取內頁經緯度並做通勤交集判定。
    
    回傳 (符合通勤名單, 超出通勤名單, 未能判斷交通之名單)。
    """
    commute_filter = CommuteFilter()
    passed_items: list[dict] = []
    out_items: list[dict] = []       # 新增：超出範圍清單
    unknown_items: list[dict] = []
    detail_is_blocked = False

    log.info("開始處理 %d 筆新增物件之交通篩選...", len(new_items))

    client_headers = {
        "User-Agent": config.USER_AGENT,
        "Accept-Language": "zh-TW,zh;q=0.9",
    }

    with httpx.Client(headers=client_headers, follow_redirects=True) as client:
        for item in new_items:
            lid = item["listing_id"]
            district = (item.get("district") or "").strip()

            # 1. 白名單免判斷：中山區、大同區、松山區必在通勤圈內
            if district in EXEMPT_DISTRICTS:
                log.info("[%s] 位於核心白名單區（%s），直接通過免查內頁。", lid, district)
                passed_items.append(item)
                continue

            # 2. 若先前已發現內頁被封鎖，剩下非白名單物件一律納入未判斷交通
            if detail_is_blocked:
                unknown_items.append(item)
                continue

            # 3. 抓取內頁取得經緯度
            time.sleep(config.REQUEST_INTERVAL_SEC)
            try:
                lat, lng = fetch_detail_coords(lid, client)
                item["lat"] = lat
                item["lng"] = lng

                # 4. 幾何交集判定
                status = commute_filter.check_item(item)
                if status == "pass":
                    log.info("[%s] 座標 (%s, %s) 落在交通交集區內，符合條件。", lid, lat, lng)
                    passed_items.append(item)
                elif status == "out":
                    log.info("[%s] 座標 (%s, %s) 超出交通交集區，保留並標註超出。", lid, lat, lng)
                    out_items.append(item)  # <-- 改為保留進 out_items
                else:  # 'unknown'
                    unknown_items.append(item)

            except DetailBlockedError as exc:
                log.error("內頁抓取遭遇 591 封鎖！錯誤：%s", exc)
                detail_is_blocked = True
                unknown_items.append(item)

                if tg_token and tg_chat:
                    notify.send_blocked_alert(tg_token, tg_chat, stage="內頁 Enrich")

    return passed_items, out_items, unknown_items


def run(kind: str = "rent") -> dict:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfgk = KINDS[kind]
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    timestamp = now.strftime("%Y%m%d-%H%M%S")

    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID")

    subs, settings = load_subscriptions(kind)
    if not subs:
        log.warning("沒有啟用中的%s訂閱，結束。", kind)
        return {}

    threshold = settings.get("missing_rounds_before_removed", 2)
    watchlist = load_watchlist()

    # 1. 抓取當前列表頁
    current, stats, covered = collect_current(subs, now, cfgk["scrape"])
    previous = load_latest(cfgk["latest"])

    # 列表頁整輪被擋檢查
    if covered is not None and not covered:
        log.warning("本輪所有區皆未抓到（疑似被擋），發出 Telegram 警報。")
        if tg_token and tg_chat:
            notify.send_blocked_alert(tg_token, tg_chat, stage="列表頁抓取（全區皆空）")

    # 2. 比對新舊快照
    new_state, report = diff_snapshots(
        previous,
        current,
        today=today,
        missing_rounds_before_removed=threshold,
        covered_districts=covered,
        price_key=cfgk["price_key"],
    )

    # 3. 第二階段：僅對租屋的「新增物件（new）」進行內頁 Enrich 與通勤篩選
    report["out_commute"] = []
    report["unknown_commute"] = []
    if kind == "rent" and report.get("new"):
        passed_new, out_new, unknown_new = enrich_and_filter_new_rentals(
            report["new"], tg_token, tg_chat
        )
        report["new"] = passed_new
        report["out_commute"] = out_new
        report["unknown_commute"] = unknown_new

        # 將 enrich 取得的座標同步寫回快照紀錄
        for item in passed_new + out_new + unknown_new:
            lid = item["listing_id"]
            if lid in new_state["listings"]:
                new_state["listings"][lid]["lat"] = item.get("lat")
                new_state["listings"][lid]["lng"] = item.get("lng")
              
    # 4. 關注清單與備註處理
    for lid, rec in new_state["listings"].items():
        rec["watched"] = lid in watchlist
        if lid in watchlist and isinstance(watchlist[lid], dict):
            rec["note"] = watchlist[lid].get("note", rec.get("note", ""))

    # 5. 存檔與推播
   payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "kind": kind,
        "subscriptions": stats,
        "report": report,
        "listings": new_state["listings"],
    }
    save_snapshot(payload, timestamp, cfgk["latest"], cfgk["snapshots"])
    notify.notify(report, subs, kind=kind)

    log.info(
        "[%s] 完成：🆕%d（通過） ❓%d（未判斷） 💰%d ❌%d（狀態共 %d 筆）",
        kind,
        len(report["new"]),
        len(report.get("unknown_commute", [])),
        len(report["price_drop"]),
        len(report["removed"]),
        len(new_state["listings"]),
    )
    return payload


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", choices=list(KINDS), default="rent")
    run(ap.parse_args().type)
