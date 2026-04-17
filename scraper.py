"""
同程旅行 (Tongcheng / ly.com) 评论抓取工具
抓取 2025年10月 以前的所有酒店/景点评论
"""

import requests
import json
import csv
import time
import logging
import os
from datetime import datetime
from typing import Optional, Iterator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

CUTOFF_DATE = datetime(2025, 10, 1)

# ---------------------------------------------------------------------------
# HTTP session helpers
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10; Pixel 3) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://m.ly.com/",
    "Origin": "https://m.ly.com",
}


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


# ---------------------------------------------------------------------------
# API endpoints  (同程艺龙 / ly.com)
# ---------------------------------------------------------------------------

# Hotel comment list (GET)
HOTEL_COMMENT_URL = "https://hotelservice.ly.com/Comment/GetCommentList"

# Scenic spot (景点) comment list
SCENIC_COMMENT_URL = "https://scenicservice.ly.com/scenic/comment/list"

# Fallback mobile-web XHR (may need cookie / login)
HOTEL_COMMENT_MOBILE_URL = "https://m.ly.com/hotels/comment/list.htm"


def _parse_date(raw: str) -> Optional[datetime]:
    """Try common date formats returned by ly.com APIs."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.strip(), fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Hotel comment scraper
# ---------------------------------------------------------------------------

def fetch_hotel_comments(
    hotel_id: str,
    session: requests.Session,
    page_size: int = 20,
) -> Iterator[dict]:
    """
    Yield all hotel comments posted before CUTOFF_DATE.
    Stops pagination as soon as a page contains only comments on/after the cutoff
    (since results are sorted newest-first).
    """
    page = 1
    consecutive_new = 0  # pages that are entirely newer than cutoff

    while True:
        params = {
            "hotelId": hotel_id,
            "pageIndex": page,
            "pageSize": page_size,
            "sortType": 1,      # 1 = by date descending
            "commentType": 0,   # 0 = all
        }
        try:
            resp = session.get(HOTEL_COMMENT_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.error("酒店 %s 第%d页请求失败: %s", hotel_id, page, exc)
            break

        comments = _extract_hotel_comment_list(data)
        if not comments:
            log.info("酒店 %s 第%d页无数据，抓取结束", hotel_id, page)
            break

        found_old = False
        for c in comments:
            raw_date = c.get("commentDate") or c.get("createTime") or c.get("checkInDate") or ""
            dt = _parse_date(raw_date)
            if dt is None or dt < CUTOFF_DATE:
                found_old = True
                yield _normalize_hotel_comment(c, hotel_id, dt)
            else:
                log.debug("跳过 %s 的评论（时间 %s ≥ 截止日期）", hotel_id, raw_date)

        if not found_old:
            consecutive_new += 1
            if consecutive_new >= 3:
                # Three consecutive pages with only newer comments — something
                # is wrong (maybe sort order changed).  Stop to avoid runaway.
                log.warning("酒店 %s 连续3页均为截止日期后内容，终止", hotel_id)
                break
        else:
            consecutive_new = 0
            # If the entire page was before the cutoff we've gone far enough back
            if all(
                _parse_date(
                    c.get("commentDate") or c.get("createTime") or ""
                ) is not None
                and _parse_date(
                    c.get("commentDate") or c.get("createTime") or ""
                ) < CUTOFF_DATE
                for c in comments
            ):
                log.info("酒店 %s 第%d页全部为截止日期前内容，继续翻页", hotel_id, page)

        page += 1
        time.sleep(0.8)  # polite delay


def _extract_hotel_comment_list(data: dict) -> list:
    """Handle different response envelope shapes."""
    for key in ("data", "Data", "result", "Result", "commentList", "CommentList"):
        if key in data:
            val = data[key]
            if isinstance(val, list):
                return val
            if isinstance(val, dict):
                for inner in ("list", "List", "items", "commentList"):
                    if inner in val and isinstance(val[inner], list):
                        return val[inner]
    return []


def _normalize_hotel_comment(raw: dict, hotel_id: str, dt: Optional[datetime]) -> dict:
    return {
        "type": "hotel",
        "hotel_id": hotel_id,
        "comment_id": raw.get("commentId") or raw.get("id") or "",
        "user_name": raw.get("userName") or raw.get("nickName") or "",
        "score": raw.get("score") or raw.get("avgScore") or "",
        "content": raw.get("content") or raw.get("commentContent") or "",
        "date": dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "",
        "raw_date": raw.get("commentDate") or raw.get("createTime") or "",
        "room_type": raw.get("roomType") or raw.get("productName") or "",
        "source": "hotel",
    }


# ---------------------------------------------------------------------------
# Scenic spot comment scraper
# ---------------------------------------------------------------------------

def fetch_scenic_comments(
    scenic_id: str,
    session: requests.Session,
    page_size: int = 20,
) -> Iterator[dict]:
    """Yield all scenic-spot comments posted before CUTOFF_DATE."""
    page = 1
    while True:
        params = {
            "scenicId": scenic_id,
            "pageNum": page,
            "pageSize": page_size,
            "sort": "time",
        }
        try:
            resp = session.get(SCENIC_COMMENT_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.error("景点 %s 第%d页请求失败: %s", scenic_id, page, exc)
            break

        comments = _extract_scenic_comment_list(data)
        if not comments:
            break

        all_old = True
        for c in comments:
            raw_date = c.get("commentTime") or c.get("createTime") or ""
            dt = _parse_date(raw_date)
            if dt and dt >= CUTOFF_DATE:
                all_old = False
                continue
            yield _normalize_scenic_comment(c, scenic_id, dt)

        if all_old:
            log.info("景点 %s 第%d页全为截止日期前内容，继续翻页", scenic_id, page)

        page += 1
        time.sleep(0.8)


def _extract_scenic_comment_list(data: dict) -> list:
    for key in ("data", "result", "commentList", "list"):
        if key in data:
            val = data[key]
            if isinstance(val, list):
                return val
            if isinstance(val, dict):
                for inner in ("list", "items", "commentList"):
                    if inner in val and isinstance(val[inner], list):
                        return val[inner]
    return []


def _normalize_scenic_comment(raw: dict, scenic_id: str, dt: Optional[datetime]) -> dict:
    return {
        "type": "scenic",
        "scenic_id": scenic_id,
        "comment_id": raw.get("commentId") or raw.get("id") or "",
        "user_name": raw.get("userName") or raw.get("nickName") or "",
        "score": raw.get("score") or raw.get("rating") or "",
        "content": raw.get("content") or raw.get("commentContent") or "",
        "date": dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "",
        "raw_date": raw.get("commentTime") or raw.get("createTime") or "",
        "source": "scenic",
    }


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

FIELDNAMES = [
    "type", "hotel_id", "scenic_id", "comment_id",
    "user_name", "score", "content", "date", "raw_date",
    "room_type", "source",
]


def save_to_csv(records: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    log.info("已保存 %d 条评论到 %s", len(records), path)


def save_to_json(records: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    log.info("已保存 %d 条评论到 %s", len(records), path)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def scrape(
    hotel_ids: Optional[list[str]] = None,
    scenic_ids: Optional[list[str]] = None,
    output_dir: str = "output",
    output_format: str = "both",  # "csv" | "json" | "both"
) -> list[dict]:
    """
    Scrape Tongcheng comments before 2025-10-01.

    Args:
        hotel_ids:     List of Tongcheng hotel IDs to scrape.
        scenic_ids:    List of Tongcheng scenic-spot IDs to scrape.
        output_dir:    Directory to write results to.
        output_format: "csv", "json", or "both".

    Returns:
        All collected comment records as a list of dicts.
    """
    os.makedirs(output_dir, exist_ok=True)
    session = make_session()
    all_records: list[dict] = []

    for hid in (hotel_ids or []):
        log.info("开始抓取酒店 %s 的评论...", hid)
        recs = list(fetch_hotel_comments(hid, session))
        log.info("酒店 %s 共抓取 %d 条评论", hid, len(recs))
        all_records.extend(recs)

    for sid in (scenic_ids or []):
        log.info("开始抓取景点 %s 的评论...", sid)
        recs = list(fetch_scenic_comments(sid, session))
        log.info("景点 %s 共抓取 %d 条评论", sid, len(recs))
        all_records.extend(recs)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if output_format in ("csv", "both"):
        save_to_csv(all_records, os.path.join(output_dir, f"tongcheng_comments_{ts}.csv"))
    if output_format in ("json", "both"):
        save_to_json(all_records, os.path.join(output_dir, f"tongcheng_comments_{ts}.json"))

    return all_records


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="同程旅行评论抓取工具（截止2025年10月）")
    parser.add_argument(
        "--hotel-ids",
        nargs="+",
        default=[],
        help="酒店ID列表，例如: --hotel-ids 12345 67890",
    )
    parser.add_argument(
        "--scenic-ids",
        nargs="+",
        default=[],
        help="景点ID列表，例如: --scenic-ids 11111 22222",
    )
    parser.add_argument("--output-dir", default="output", help="输出目录（默认: output）")
    parser.add_argument(
        "--format",
        choices=["csv", "json", "both"],
        default="both",
        help="输出格式（默认: both）",
    )
    args = parser.parse_args()

    if not args.hotel_ids and not args.scenic_ids:
        parser.error("请至少提供一个 --hotel-ids 或 --scenic-ids 参数")

    records = scrape(
        hotel_ids=args.hotel_ids,
        scenic_ids=args.scenic_ids,
        output_dir=args.output_dir,
        output_format=args.format,
    )
    print(f"\n抓取完成，共 {len(records)} 条评论（2025年10月前）")
